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
from ..core.presets import MODELS, model_options, model_settings
from ..core.provenance import code_version
from ..evaluation.runner import evaluate, validate_ranking, write_run
from ..ingestion.dataset import load_dataset
from .mail import ServiceError

PUBLIC_DATASET = "mail-public"
PUBLIC_FINGERPRINT = "0daa664136d798c1ed2fe50802a7d236f93b4891d56f2353bc5b807b56601665"


class Evaluations:
    def __init__(self, settings, app_factory):
        self.settings = settings
        self.app_factory = app_factory
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evaluation")
        self.lock = Lock()
        self.latest = None
        self.datasets = {PUBLIC_DATASET: ("Почтовый поиск · публичный dev", settings.search_dataset, settings.database_url)}
        for lang, name, url in (("ru", "русский перевод", settings.enronqa_ru_database_url),
                                ("en", "английский оригинал", settings.enronqa_en_database_url)):
            if url:
                archive = settings.enronqa_directory / f"enronqa-{lang}-{lang}.zip"
                self.datasets[f"enronqa-{lang}"] = (f"EnronQA · {name}", archive, url)
        self.comparisons = {}
        for path in settings.evaluation_dir.glob("*/run.json"):
            try:
                metadata = json.loads(path.read_text())
                if metadata.get("status") == "ok":
                    self._remember(metadata, json.loads(path.with_name("metrics.json").read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                logging.getLogger(__name__).warning("Skipping unreadable evaluation %s", path.parent.name)

    def _remember(self, meta, metrics):
        dataset = meta.get("dataset_id")
        if dataset is None and meta["dataset"]["fingerprint"] == PUBLIC_FINGERPRINT:
            dataset = PUBLIC_DATASET
        if dataset not in self.datasets or meta["engine"] not in MODELS:
            return
        key = (dataset, meta["engine"])
        row = dict(dataset=dataset, model=meta["engine"], created_at=meta["created_at"],
                   fingerprint=meta["dataset"]["fingerprint"], **metrics["by_k"]["10"],
                   p99_ms=meta["server_latency"]["p99"])
        if key not in self.comparisons or self.comparisons[key]["created_at"] < row["created_at"]:
            self.comparisons[key] = row

    def catalog(self):
        with self.lock:
            return dict(models=model_options(),
                        datasets=[dict(id=key, name=value[0]) for key, value in self.datasets.items()],
                        comparisons=list(self.comparisons.values()),
                        run=self.latest)

    def start(self, model, dataset):
        if model not in MODELS or dataset not in self.datasets:
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
        _, archive, database_url = self.datasets[job["dataset"]]
        settings = model_settings(self.settings, model).model_copy(update=dict(
            search_dataset=archive, database_url=database_url))
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
                        engine=model, engine_config=json.loads(settings.search_config.read_text()), ks=DEFAULT_KS,
                        dataset_id=job["dataset"], dataset=ds.summary, code=code_version(), server_latency=latency)
        root = settings.evaluation_dir
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=root) as scratch:
            output = Path(scratch) / job["id"]
            write_run(output, metadata, metrics, rows, predictions)
            output.rename(root / job["id"])
        if not errors:
            with self.lock:
                self._remember(metadata, metrics)
        self._update(status="completed" if not errors else "partial", phase="Прогон завершён",
                     metrics=metrics, p99_ms=latency["p99"], samples=len(samples))

    def close(self):
        self.worker.shutdown(wait=True)
