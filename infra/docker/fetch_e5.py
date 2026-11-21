"""Download the pinned E5 CPU graph and its tokenizer for offline use."""
import argparse
from pathlib import Path

from fetch_minilm import fetch

MODEL = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
ASSETS = (
    ("onnx/model_qint8_avx512_vnni.onnx", "model.onnx", "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"),
    ("onnx/tokenizer.json", "tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    directory = parser.parse_args().output
    directory.mkdir(parents=True, exist_ok=True)
    for source, name, sha in ASSETS:
        fetch(source, directory / name, sha, model=MODEL, revision=REVISION)
