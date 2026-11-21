"""Build a local index using the encoder from the team's pinned E5 prototype."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from mailsearch.encoder import Encoder


def read_rows(archive, filename):
    with ZipFile(archive) as z:
        raw = z.read(filename)
        expected = json.loads(z.read("manifest.json"))["sha256"][filename]
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch: {filename}")
    return [json.loads(row) for row in raw.splitlines()]


def encode_sorted(encoder, texts, batch=48, *, query=False):
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    result = np.empty((len(texts), encoder.dimensions), dtype=np.float32)
    for start in range(0, len(order), batch):
        indices = order[start:start + batch]
        result[indices] = encoder.encode([texts[i] for i in indices], query=query)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("archive", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    docs = sorted(read_rows(args.archive, "documents.jsonl"), key=lambda d: d["doc_id"])
    encoder = Encoder("e5", "cuda")
    vectors = encode_sorted(encoder, [d["doc"] for d in docs])
    with args.output.open("xb") as dest:
        np.savez(dest, vectors=vectors, ids=[d["doc_id"] for d in docs],
                 archive_sha=hashlib.sha256(args.archive.read_bytes()).hexdigest(), encoder=encoder.key)
