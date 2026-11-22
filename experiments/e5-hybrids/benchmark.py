"""Benchmark deployed engine presets on the project's fixed-K evaluation protocol."""
import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import platform
from time import perf_counter

from mail_search.cli import DEFAULT_KS
from mail_search.benchmarks.latency import latency_summary
from mail_search.core.presets import MODELS, model_settings
from mail_search.core.provenance import code_version
from mail_search.core.settings import Settings
from mail_search.evaluation.runner import evaluate, run_engine, write_run
from mail_search.ingestion.dataset import load_dataset
from mail_search.search.dates import receipt_day


class ReceiptDayControl:
    """Isolate the shared date filter from lexical ranking in hybrid retrieval."""

    def __init__(self, dense):
        self.dense = dense

    def search(self, request, k):
        day, _ = receipt_day(request.query, request.query_date)
        hits, _ = self.dense.search_page(request, k, receipt_date=day)
        return hits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("models", nargs="+", choices=[*MODELS, "e5-receipt-day-control"])
    args = parser.parse_args()
    settings = Settings(database_url="offline", search_dataset=args.dataset,
                        e5_model_dir=args.model_dir, e5_index_dir=args.index_dir)
    dataset = load_dataset(args.dataset)
    for model in args.models:
        output = args.output / model
        if output.exists():
            parser.error(f"Output already exists: {output}")
        is_control = model == "e5-receipt-day-control"
        selected = model_settings(settings, "e5-cosine" if is_control else model)
        module, name = selected.search_engine_factory.split(":")
        start = perf_counter()
        loaded = getattr(importlib.import_module(module), name)(selected)
        build_ms = (perf_counter() - start) * 1000
        try:
            assert loaded.fingerprint == dataset.summary["fingerprint"]
            engine = ReceiptDayControl(loaded.engine) if is_control else loaded.engine
            predictions, durations, errors = run_engine(dataset, engine, max(DEFAULT_KS))
            config = {**json.loads(selected.search_config.read_text()), **getattr(loaded.engine, "config", {})}
            if hasattr(loaded.engine, "model"):
                config["model_identity"] = loaded.engine.model.identity
            if is_control:
                config["date_mode"] = "contextual_receipt_day"
        finally:
            loaded.close()
        metrics, rows = evaluate(dataset, predictions, DEFAULT_KS, durations=durations, errors=errors)
        status = "failed" if errors else "ok"
        metadata = dict(format_version=1, created_at=datetime.now(timezone.utc).isoformat(),
                        dataset=dataset.summary, platform=platform.platform(), python=platform.python_version(),
                        machine=platform.machine(), device="cpu", code=code_version(), ks=DEFAULT_KS,
                        status=status, engine=model, factory=selected.search_engine_factory,
                        engine_config=config, engine_build_ms=build_ms, engine_latency=latency_summary(durations), source=args.dataset.name,
                        timing_scope="Sequential in-process search, no explicit warmup, limit 100")
        write_run(output, metadata, metrics, rows, predictions)
        print(model, status, metrics["by_k"]["10"], flush=True)
        if errors:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
