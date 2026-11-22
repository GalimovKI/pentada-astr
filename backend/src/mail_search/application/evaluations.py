"""Single-worker dev benchmarks. Each run owns its search engine and artifacts."""
import asyncio
import ctypes
import json
import logging
import math
import platform
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
from ..core.datasets import mail_datasets, PUBLIC_DATASET
from ..core.presets import available_models, model_options, model_settings
from ..core.provenance import code_version
from ..evaluation.runner import evaluate, validate_ranking, write_run
from ..ingestion.dataset import load_dataset
from .mail import ServiceError

PUBLIC_FINGERPRINT = "0daa664136d798c1ed2fe50802a7d236f93b4891d56f2353bc5b807b56601665"


QUANTILES = {"p50": .50, "p90": .90, "p95": .95, "p99": .99}


def measured_latency(samples):
    return {name: percentile(samples, q) for name, q in QUANTILES.items()}


def server_hardware(cuda_enabled):
    cpu = platform.machine()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name") and ":" in line:
                cpu = line.split(":", 1)[1].strip()
                break
    hardware = {"cpu": cpu}
    if cuda_enabled:
        # Use the same visible CUDA ordinal (0) as ONNX Runtime, including CDI remapping.
        try:
            driver = ctypes.CDLL("libcuda.so.1")
            device = ctypes.c_int()
            name = ctypes.create_string_buffer(256)
            if (driver.cuInit(0) == 0 and driver.cuDeviceGet(ctypes.byref(device), 0) == 0
                    and driver.cuDeviceGetName(name, len(name), device) == 0):
                hardware["cuda"] = name.value.decode(errors="replace")
        except (OSError, AttributeError):
            pass
    return hardware


def recorded_device(model, config):
    if model == "e5-cosine":
        return config.get("device")
    if model == "bm25-minilm":
        return config.get("inference_device")
    return "cpu"


class Evaluations:
    def __init__(self, settings, app_factory):
        self.settings = settings
        self.app_factory = app_factory
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evaluation")
        self.lock = Lock()
        self.latest = None
        self.datasets = mail_datasets(settings)
        self.models = available_models(settings)
        self.hardware = server_hardware("cuda" in (settings.e5_device, settings.minilm_device))
        self.comparisons = {}
        reference = settings.enronqa_directory / "comparisons.json"
        if reference.is_file():
            for row in json.loads(reference.read_text()):
                if row["dataset"] in self.datasets and row["model"] in self.models:
                    device = recorded_device(row["model"], {})
                    self.comparisons[row["dataset"], row["model"], device] = {**row, "device": device}
        for path in settings.evaluation_dir.glob("*/run.json"):
            try:
                metadata = json.loads(path.read_text())
                if metadata.get("status") == "ok":
                    latency = metadata["server_latency"]
                    samples_path = path.with_name("per_query.jsonl")
                    if "p50" not in latency and samples_path.is_file():
                        with samples_path.open() as stream:
                            samples = [r["latency_ms"] for line in stream if (r := json.loads(line)).get("latency_ms") is not None
                                       and not r.get("error")]
                        if samples and len(samples) == latency.get("samples"):
                            latency.update(measured_latency(samples))
                    self._remember(metadata, json.loads(path.with_name("metrics.json").read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                logging.getLogger(__name__).warning("Skipping unreadable evaluation %s", path.parent.name)

    def _remember(self, meta, metrics):
        dataset = meta.get("dataset_id")
        if dataset is None and meta["dataset"]["fingerprint"] == PUBLIC_FINGERPRINT:
            dataset = PUBLIC_DATASET
        if dataset not in self.datasets or meta["engine"] not in self.models:
            return
        device = recorded_device(meta["engine"], meta.get("engine_config", {}))
        config = meta.get("engine_config", {})
        precision = None
        if meta["engine"] == "bm25-minilm":
            # Only label known, SHA-verified assets (including historical runs).
            weights = config.get("model_identity", {}).get("weights_sha256")
            precision = {
                "3e9a03ed1e966f7c5288dd4230e3d6a9bf5e3a170a06f1f4241c5bca12c6487c": "FP32",
                "6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b": "INT8",
                "1825907d6c1a9001ff78124780bbde20a614a8c3df3b63409cf3c72c6fe5c8b4": "INT8",
            }.get(weights)
        key = (dataset, meta["engine"], device)
        row = dict(dataset=dataset, model=meta["engine"], created_at=meta["created_at"],
                   fingerprint=meta["dataset"]["fingerprint"], **metrics["by_k"]["10"],
                   device=device, precision=precision, source=meta.get("hardware"), samples=meta["server_latency"].get("samples"),
                   **{f"{name}_ms": meta["server_latency"].get(name) for name in QUANTILES})
        if key not in self.comparisons or self.comparisons[key]["created_at"] < row["created_at"]:
            self.comparisons[key] = row

    def _devices(self, model):
        if model == "bm25-minilm" and self.settings.minilm_device == "cuda":
            return ["cuda", "cpu"]
        if model == "e5-cosine":
            if self.settings.e5_device == "cuda":
                return ["cuda", "cpu"]
            graph = self.settings.evaluation_e5_cuda_dir
            if self.settings.minilm_device == "cuda" and graph and (graph / "model.onnx").is_file():
                return ["cpu", "cuda"]
        return ["cpu"]

    def catalog(self):
        with self.lock:
            return dict(hardware=self.hardware, models=[{**m, "devices": self._devices(m["id"])} for m in model_options(self.models)],
                        datasets=[dict(id=key, name=value[0]) for key, value in self.datasets.items()],
                        comparisons=list(self.comparisons.values()),
                        run=self.latest)

    def start(self, model, dataset, device=None):
        if model not in self.models or dataset not in self.datasets:
            raise ServiceError(422, "unknown_evaluation_option")
        devices = self._devices(model)
        device = devices[0] if device is None else device
        if device not in devices:
            raise ServiceError(422, "unsupported_evaluation_device")
        with self.lock:
            if self.latest and self.latest["status"] == "running":
                raise ServiceError(409, "evaluation_running")
            self.latest = dict(id=uuid4().hex, model=model, dataset=dataset, device=device, status="running",
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
        if model == "bm25-minilm":
            settings = settings.model_copy(update={"minilm_device": job["device"]})
        if model == "e5-cosine":
            graph = settings.e5_model_dir
            if settings.e5_device == "cpu" and "cuda" in self._devices(model):
                graph = settings.evaluation_e5_cuda_dir
            settings = settings.model_copy(update={"e5_device": job["device"], "e5_model_dir": graph})
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
            # The isolated app exposes the selected corpus as its primary dataset.
            loaded = app.state.services[PUBLIC_DATASET].loaded
            engine_config = {**json.loads(settings.search_config.read_text()),
                             **getattr(loaded.engine, "config", {})}
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
        latency = dict(samples=len(samples), **measured_latency(samples), percentile_method="nearest_rank",
                       scope="ASGI Server-Timing, sequential, no explicit warmup, limit=100")
        if model == "e5-cosine":
            engine_config["device"] = settings.e5_device
            engine_config["model_identity"] = loaded.engine.model.identity
            if "cuda" in self._devices(model):
                engine_config["graph"] = "onnx/model.onnx"
        metadata = dict(created_at=datetime.now(timezone.utc).isoformat(), status="failed" if errors else "ok",
                        hardware=self.hardware.get(job["device"]),
                        engine=model, engine_config=engine_config, ks=DEFAULT_KS,
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
                     metrics=metrics, **{f"{name}_ms": latency[name] for name in QUANTILES}, samples=len(samples))

    def close(self):
        self.worker.shutdown(wait=True)
