"""Single-worker dev benchmarks. Each run owns its search engine and artifacts."""
import asyncio
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from urllib.parse import quote
from uuid import uuid4

import httpx

from ..benchmarks.latency import percentile
from ..cli import DEFAULT_KS
from ..core.paths import repository_root
from ..core.provenance import code_version
from ..core.settings import DEFAULT_SEARCH_FACTORY, LEGACY_SEARCH_FACTORY
from ..evaluation.runner import evaluate, validate_ranking, write_run
from ..ingestion.dataset import load_dataset
from .mail import ServiceError

DATASET = "mail-public"
MODELS = {
    "bm25-event-aware": ("BM25 с учётом событий", DEFAULT_SEARCH_FACTORY),
    "bm25-improved": ("BM25 с весами запроса", LEGACY_SEARCH_FACTORY),
    "bm25-stemmed": ("BM25 со стеммингом", LEGACY_SEARCH_FACTORY),
    "bm25": ("BM25 базовый", LEGACY_SEARCH_FACTORY),
}


class Evaluations:
    def __init__(self, settings, app_factory):
        self.settings = settings
        self.app_factory = app_factory
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evaluation")
        self.lock = Lock()
        self.latest = None

    def catalog(self):
        with self.lock:
            return dict(models=[dict(id=k, name=v[0]) for k, v in MODELS.items()],
                        datasets=[dict(id=DATASET, name="Почтовый поиск · публичный dev")],
                        run=self.latest)

    def start(self, model, dataset):
        if model not in MODELS or dataset != DATASET:
            raise ServiceError(422, "unknown_evaluation_option")
        with self.lock:
            if self.latest and self.latest["status"] == "running":
                raise ServiceError(409, "evaluation_running")
            self.latest = dict(id=uuid4().hex, model=model, dataset=dataset, status="running",
                               phase="Подготовка модели", completed=0, total=None)
            self.worker.submit(self._run, self.latest)

    def _update(self, **values):
        with self.lock:
            self.latest = {**self.latest, **values}

    def _run(self, job):
        try:
            asyncio.run(self._evaluate(job))
        except Exception as exc:
            logging.getLogger(__name__).error("evaluation_failed run=%s category=%s",
                                              job["id"], type(exc).__name__)
            self._update(status="failed", phase="Не удалось завершить прогон. Проверьте корпус, базу и каталог результатов.")

    async def _evaluate(self, job):
        model = job["model"]
        path = repository_root() / "configs/search" / (model + ".json")
        settings = self.settings.model_copy(update=dict(search_engine_factory=MODELS[model][1],
                                                        search_config=path, enable_evaluations=False))
        ds = load_dataset(settings.search_dataset)
        self._update(total=len(ds.queries))
        predictions, times, errors = {}, {}, {}
        # Exercise the same ASGI route, SQL reads and middleware as interactive search.
        # The isolated app loads the selected model without changing the mail session.
        app = self.app_factory(settings)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=transport, base_url="http://benchmark") as client:
            (await client.get("/health/ready")).raise_for_status()
            for i, query in enumerate(ds.queries, 1):
                qid = query.query_id
                response = await client.post(f"/api/v1/mailboxes/{quote(query.synthetic_user, safe='')}/search",
                                       json=dict(query=query.query, query_date=query.query_date.isoformat(),
                                                 limit=max(DEFAULT_KS)))
                ranking = []
                try:
                    if response.status_code != 200:
                        raise ValueError(f"HTTP {response.status_code}")
                    duration = float(response.headers["Server-Timing"].removeprefix("search;dur="))
                    if not math.isfinite(duration) or duration < 0:
                        raise ValueError("Invalid server duration")
                    ranking = [hit["doc_id"] for hit in response.json()["items"]]
                    validate_ranking(ds, query, ranking)
                    times[qid] = duration
                except (KeyError, ValueError, TypeError) as exc:
                    errors[qid] = str(exc)
                    ranking = []
                predictions[qid] = ranking
                self._update(completed=i, phase="Выполняется поиск")
        metrics, rows = evaluate(ds, predictions, DEFAULT_KS, durations=times, errors=errors)
        samples = list(times.values())
        latency = dict(samples=len(samples), p99=percentile(samples, .99),
                       scope="ASGI Server-Timing, sequential, no explicit warmup, limit=100")
        metadata = dict(created_at=datetime.now(timezone.utc).isoformat(), status="failed" if errors else "ok",
                        engine=model, engine_config=json.loads(path.read_text()), ks=DEFAULT_KS,
                        dataset=ds.summary, code=code_version(), server_latency=latency)
        root = settings.evaluation_dir
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=root) as scratch:
            output = Path(scratch) / job["id"]
            write_run(output, metadata, metrics, rows, predictions)
            output.rename(root / job["id"])
        self._update(status="completed" if not errors else "partial", phase="Прогон завершён",
                     metrics=metrics, p99_ms=latency["p99"], samples=len(samples))

    def close(self):
        self.worker.shutdown(wait=True)
