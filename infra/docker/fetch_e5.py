"""Download the pinned E5 graph and its tokenizer for offline use."""
import argparse
from pathlib import Path

from fetch_minilm import fetch

MODEL = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
GRAPHS = {
    "cpu": ("onnx/model_qint8_avx512_vnni.onnx", "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"),
    "cuda": ("onnx/model.onnx", "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665"),
}
TOKENIZER_SHA = "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=GRAPHS, default="cpu")
    args = parser.parse_args()
    directory = args.output
    directory.mkdir(parents=True, exist_ok=True)
    source, sha = GRAPHS[args.device]
    fetch(source, directory / "model.onnx", sha, model=MODEL, revision=REVISION)
    fetch("onnx/tokenizer.json", directory / "tokenizer.json", TOKENIZER_SHA, model=MODEL, revision=REVISION)
