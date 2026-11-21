#!/usr/bin/env python3
"""Prove CUDA compute using ORT profiling, not just a visible GPU/provider."""
import argparse
from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mail_search.search.bm25_minilm import MiniLM


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=Path("/opt/mailsearch/minilm"))
    args = parser.parse_args()
    with TemporaryDirectory() as temp:
        model = MiniLM(args.model_dir / "model.onnx", 4, device="cuda", profile_prefix=Path(temp) / "ort")
        scores = model.score("оплата заказа", ["Счёт на оплату заказа", "Письмо о встрече"])
        events = json.loads(Path(model.session.end_profiling()).read_text())
        compute = Counter(event.get("args", {}).get("op_name") for event in events
                          if event.get("args", {}).get("provider") == "CUDAExecutionProvider")
        if not any("MatMul" in op or "Attention" in op or "Gemm" in op for op in compute if op):
            raise SystemExit("FAIL: profile has no CUDA matrix/attention compute")
        if len(scores) != 2:
            raise SystemExit("FAIL: missing scores")
        print(json.dumps(dict(runtime=model.runtime, providers=model.providers, cuda_operations=dict(compute)), indent=2))


if __name__ == "__main__":
    main()
