import argparse
import hashlib
import importlib
import json
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

from .benchmarks.latency import latency_summary
from .core.errors import ValidationError
from .core.paths import repository_root
from .core.provenance import code_version
from .ingestion.dataset import load_dataset
from .evaluation.runner import evaluate, format_report, read_predictions, run_engine, write_run

DEFAULT_DATASET = repository_root() / "data/raw/mipt_mail_search_participants.zip"
DEFAULT_ENGINE = "mail_search.search.bm25:create_engine"
DEFAULT_KS = [1, 5, 10, 20, 50, 100]


def compare_runs(left: Path, right: Path) -> str:
    def read(folder, name):
        return json.loads((folder / name).read_text(encoding="utf-8"))
    a_run, b_run = read(left, "run.json"), read(right, "run.json")
    a, b = read(left, "metrics.json"), read(right, "metrics.json")
    if a_run["dataset"]["fingerprint"] != b_run["dataset"]["fingerprint"]:
        raise ValidationError("cannot compare runs on different dataset fingerprints")
    if a["by_k"].keys() != b["by_k"].keys() or a["aggregation"] != b["aggregation"]:
        raise ValidationError("cannot compare runs with different K values or aggregation")
    lines = [f"Сравнение: {left} → {right}", f"Ошибок: {a['failed_queries']} → {b['failed_queries']}", "",
             "| K | Δ Recall | Δ nDCG | Δ MRR | Δ MRR single |", "| --- | ---: | ---: | ---: | ---: |"]
    for k in a["by_k"]:
        values = []
        for key in ("recall", "ndcg", "mrr", "mrr_single"):
            av, bv = a["by_k"][k][key], b["by_k"][k][key]
            values.append("—" if av is None or bv is None else f"{bv-av:+.6f}")
        lines.append(f"| {k} | " + " | ".join(values) + " |")
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Validate mail-search data, evaluate an engine, compare runs.")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "run", "score"):
        command = commands.add_parser(name)
        command.add_argument("--dataset", type=Path, default=Path(DEFAULT_DATASET), help="Official ZIP or extracted directory")
        if name == "validate":
            continue
        command.add_argument("--output", type=Path, required=True, help="New run directory; existing directories are not overwritten")
        command.add_argument("--ks", nargs="+", type=int, default=DEFAULT_KS)
        if name == "run":
            command.add_argument("--engine", default=DEFAULT_ENGINE, help="Python module:factory; factory(documents, config)")
            command.add_argument("--config", type=Path, help="JSON object passed to engine factory")
        else:
            command.add_argument("--predictions", type=Path, required=True)
    command = commands.add_parser("compare")
    command.add_argument("left", type=Path)
    command.add_argument("right", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(compare_runs(args.left, args.right))
            return 0
        if args.command != "validate":
            if args.output.exists():
                raise ValidationError(f"output already exists: {args.output}; choose a new directory")
            if any(k <= 0 for k in args.ks) or len(set(args.ks)) != len(args.ks):
                raise ValidationError("K values must be distinct positive integers")
        dataset = load_dataset(args.dataset)
        if args.command == "validate":
            print(json.dumps(dataset.summary, ensure_ascii=False, indent=2))
            return 0
        run = {
            "format_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset": dataset.summary, "python": platform.python_version(),
            "platform": platform.platform(), "machine": platform.machine(),
            "ks": sorted(args.ks), "source": args.dataset.name,
        }
        durations, errors = {}, {}
        if args.command == "run":
            config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
            if not isinstance(config, dict):
                raise ValidationError("engine config must be a JSON object")
            module_name, separator, factory_name = args.engine.partition(":")
            if not separator or not module_name or not factory_name:
                raise ValidationError("engine must be module:factory")
            module = importlib.import_module(module_name)
            factory = getattr(module, factory_name)
            start = perf_counter_ns()
            engine = factory(tuple(dataset.documents.values()), config)
            build_ms = (perf_counter_ns() - start) / 1_000_000
            predictions, durations, errors = run_engine(dataset, engine, max(args.ks))
            run.update(engine=args.engine, engine_config=getattr(engine, "config", config),
                       supplied_config=config, engine_build_ms=build_ms,
                       engine_latency=latency_summary(durations), code=code_version(module))
        else:
            predictions = read_predictions(args.predictions)
            run.update(engine="external_predictions", code=code_version(),
                       predictions_sha256=hashlib.sha256(args.predictions.read_bytes()).hexdigest())
        metrics, per_query = evaluate(dataset, predictions, sorted(args.ks), durations=durations, errors=errors)
        run["status"] = "failed" if errors else "ok"
        write_run(args.output, run, metrics, per_query, predictions)
        print(format_report(run, metrics, per_query))
        print(f"Артефакты: {args.output}")
        return 1 if errors else 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, zipfile.BadZipFile) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
