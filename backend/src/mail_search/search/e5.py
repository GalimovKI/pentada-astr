"""Exact cosine retrieval with precomputed multilingual E5 passage embeddings."""
from collections import defaultdict
from functools import lru_cache
from hashlib import file_digest, sha256
import json
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import numpy as np

from ..domain.models import SearchHit

DIMENSION = 384
MAX_TOKENS = 512


@lru_cache(maxsize=2)
def encoder(model_dir: Path, device="cpu"):
    return E5Encoder(model_dir, device)


class E5Encoder:
    def __init__(self, directory, device):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model = directory / "model.onnx"
        tokenizer = directory / "tokenizer.json"
        self.tokenizer = Tokenizer.from_file(str(tokenizer))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        provider = {"cpu": "CPUExecutionProvider", "cuda": "CUDAExecutionProvider"}[device]
        if device == "cuda":
            if provider not in ort.get_available_providers():
                raise RuntimeError("E5 requires ONNX Runtime with CUDA")
            ort.preload_dlls(directory="")
        with TemporaryDirectory() as temp:
            if device == "cuda":
                options.enable_profiling = True
                options.profile_file_prefix = str(Path(temp) / "e5")
            self.session = ort.InferenceSession(str(model), options, providers=[provider])
            self.inputs = [item.name for item in self.session.get_inputs()]
            if self.session.get_providers()[0] != provider:
                raise RuntimeError(f"E5 could not activate {provider}")
            if device == "cuda":
                self.session.disable_fallback()
                self.encode(["query: проверка"])
                events = json.loads(Path(self.session.end_profiling()).read_text())
                verify_cuda_profile(events)
                print("E5 verified CUDAExecutionProvider on transformer inference", flush=True)
        with model.open("rb") as weights, tokenizer.open("rb") as vocab:
            self.identity = (file_digest(weights, "sha256").hexdigest() +
                             file_digest(vocab, "sha256").hexdigest())

    def encode(self, texts):
        batch = self.tokenizer.encode_batch(texts)
        tokens = {"input_ids": [row.ids for row in batch],
                  "attention_mask": [row.attention_mask for row in batch],
                  "token_type_ids": [row.type_ids for row in batch]}
        inputs = {name: np.asarray(tokens[name], dtype=np.int64) for name in self.inputs}
        hidden, = self.session.run([self.session.get_outputs()[0].name], inputs)
        mask = inputs["attention_mask"][:, :, None].astype(np.float32)
        pooled = (hidden * mask).sum(axis=1) / mask.sum(axis=1)
        return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)


def verify_cuda_profile(events):
    providers = {args["provider"] for event in events if event.get("cat") == "Node"
                 for args in [event.get("args", {})] if "provider" in args and
                 args.get("op_name") in {"MatMul", "FusedMatMul", "Gemm", "Attention", "MultiHeadAttention"}}
    if providers != {"CUDAExecutionProvider"}:
        raise RuntimeError("E5 transformer computation was not verified on CUDA")


def passage_vectors(documents, corpus_hash, model, directory):
    # Row order is canonical (doc_id) for archive and individual mailbox views.
    key = sha256(f"passage-mean-l2-v1/{MAX_TOKENS}/{model.identity}/{corpus_hash}".encode()).hexdigest()
    path = directory / f"{key}.npy"
    shape = (len(documents), DIMENSION)
    if path.is_file():
        matrix = np.load(path, mmap_mode="r", allow_pickle=False)
        if matrix.shape == shape and matrix.dtype == np.float32:
            return matrix
    directory.mkdir(parents=True, exist_ok=True)
    order = sorted(range(len(documents)), key=lambda i: len(documents[i].doc))
    matrix = np.empty(shape, dtype=np.float32)
    for start in range(0, len(order), 12):
        indices = order[start:start + 12]
        matrix[indices] = model.encode(["passage: " + documents[i].doc for i in indices])
        if start % 1200 == 0:
            print(f"E5 indexing {start}/{len(order)}", flush=True)
    if not np.isfinite(matrix).all():
        raise ValueError("Non-finite E5 passage vectors")
    with NamedTemporaryFile(dir=directory, delete=False) as output:
        temporary = Path(output.name)
        try:
            np.save(output, matrix, allow_pickle=False)
            output.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return np.load(path, mmap_mode="r", allow_pickle=False)


class E5Engine:
    config = {"date_mode": "availability_only"}

    def __init__(self, documents, vectors, model, single_mailbox=None):
        self.vectors = vectors
        self.model = model
        self.ids = [doc.doc_id for doc in documents]
        self.dates = np.array([doc.doc_dt.toordinal() if doc.doc_dt else 0 for doc in documents])
        boxes = defaultdict(list)
        for i, doc in enumerate(documents):
            boxes[single_mailbox or doc.synthetic_user].append(i)
        self.boxes = {user: np.array(rows) for user, rows in boxes.items()}

    def search(self, request, k):
        hits, _ = self.search_page(request, k)
        return hits

    def search_page(self, request, k, *, min_similarity=None, offset=0):
        if k < 1 or not request.query.strip():
            raise ValueError("nonempty query and positive K required")
        rows = self.boxes.get(request.synthetic_user)
        if rows is None:
            return [], 0
        eligible = rows[self.dates[rows] <= request.query_date.toordinal()]
        if not len(eligible):
            return [], 0
        query, = self.model.encode(["query: " + request.query])
        scores = self.vectors[eligible] @ query
        if min_similarity is not None:
            keep = scores.astype(np.float64) >= min_similarity
            eligible, scores = eligible[keep], scores[keep]
        order = np.argsort(-scores, kind="stable")[offset:offset + k]
        hits = [SearchHit(self.ids[eligible[i]], float(scores[i])) for i in order]
        return hits, len(scores)


def dataset_engine(dataset, model_dir, index_dir, single_mailbox=None, *, device="cpu"):
    documents = sorted(dataset.documents.values(), key=lambda doc: doc.doc_id)
    model = encoder(model_dir, device)
    vectors = passage_vectors(documents, dataset.summary["sha256"]["documents.jsonl"], model, index_dir)
    return E5Engine(documents, vectors, model, single_mailbox)
