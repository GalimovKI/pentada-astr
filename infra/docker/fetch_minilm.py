"""Fetch the pinned MiniLM model used by the dev search preset."""

import argparse
from hashlib import file_digest
from pathlib import Path
import platform
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
MODELS = {
    "arm64": ("onnx/model_qint8_arm64.onnx", "1825907d6c1a9001ff78124780bbde20a614a8c3df3b63409cf3c72c6fe5c8b4"),
    "amd64": ("onnx/model_quint8_avx2.onnx", "6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b"),
}
TOKENIZER_SHA = "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def fetch(source: str, target: Path, expected: str):
    if target.is_file() and digest(target) == expected:
        return
    url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{source}?download=true"
    for attempt in range(3):
        with NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                with urlopen(url, timeout=90) as response:
                    copyfileobj(response, output)
                output.close()
                if digest(temporary) != expected:
                    raise ValueError(f"MiniLM digest mismatch for {source}")
                temporary.chmod(0o644)
                temporary.replace(target)
                return
            except OSError:
                if attempt == 2:
                    raise
            finally:
                temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", default=platform.machine(), choices=("arm64", "aarch64", "amd64", "x86_64"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    arch = {"aarch64": "arm64", "x86_64": "amd64"}.get(args.arch, args.arch)
    model, sha = MODELS[arch]
    args.output.mkdir(parents=True, exist_ok=True)
    fetch("tokenizer.json", args.output / "tokenizer.json", TOKENIZER_SHA)
    fetch(model, args.output / "model.onnx", sha)


if __name__ == "__main__":
    main()
