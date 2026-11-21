"""Rerank a fixed BM25 prefix with locally evaluated MiniLM."""

from hashlib import file_digest
import math
from pathlib import Path

from ..core.paths import repository_root
from ..domain.models import Document, SearchHit, SearchRequest
from .relevance import relative_scores
from .dates import receipt_day
from .fuzzy import query_terms
from .routed_bm25 import RoutedBM25Engine

MAX_TOKENS = 192
RRF_CONSTANT = 60


class MiniLM:
    def __init__(self, model_path: Path, threads: int, *, device="cpu", gpu_memory_mb=2048, profile_prefix=None):
        import numpy as np
        import onnxruntime
        from tokenizers import Tokenizer

        self.np = np
        self.runtime = onnxruntime.__version__
        self.tokenizer = Tokenizer.from_file(str(model_path.with_name("tokenizer.json")))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        pad_id = self.tokenizer.token_to_id("<pad>")
        if pad_id is None:
            raise ValueError("MiniLM tokenizer is missing the <pad> token")
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token="<pad>")

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        if device not in ("cpu", "cuda"):
            raise ValueError("MiniLM device must be cpu or cuda")
        providers = ["CPUExecutionProvider"]
        if device == "cuda":
            if "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
                raise RuntimeError("MiniLM CUDA requires the minilm-gpu extra and a visible NVIDIA GPU")
            onnxruntime.preload_dlls(directory="")
            providers = [("CUDAExecutionProvider", {
                "device_id": 0, "gpu_mem_limit": gpu_memory_mb * 1024 * 1024,
                "arena_extend_strategy": "kSameAsRequested", "use_tf32": 0,
            }), "CPUExecutionProvider"]
        if profile_prefix is not None:
            options.enable_profiling = True
            options.profile_file_prefix = str(profile_prefix)
        self.session = onnxruntime.InferenceSession(
            str(model_path), sess_options=options, providers=providers,
        )
        if device == "cuda":
            if self.session.get_providers()[0] != "CUDAExecutionProvider":
                raise RuntimeError("MiniLM CUDA initialization failed; refusing CPU fallback")
            self.session.disable_fallback()
        self.providers = self.session.get_providers()
        self.inputs = tuple(item.name for item in self.session.get_inputs())

    def score(self, query: str, texts: list[str]) -> list[float]:
        scores = []
        for start in range(0, len(texts), 12):
            pairs = [(query, text) for text in texts[start:start + 12]]
            encodings = self.tokenizer.encode_batch(pairs)
            tokens = {
                "input_ids": [item.ids for item in encodings],
                "attention_mask": [item.attention_mask for item in encodings],
                "token_type_ids": [item.type_ids for item in encodings],
            }
            output, = self.session.run(None, {
                name: self.np.asarray(tokens[name], dtype=self.np.int64) for name in self.inputs
            })
            scores.extend(output.reshape(-1).tolist())
        return scores


class BM25MiniLMEngine:
    def __init__(self, documents: tuple[Document, ...], reranker: MiniLM, config: dict):
        self.documents = {document.doc_id: document for document in documents}
        self.baseline = RoutedBM25Engine(documents)
        self.reranker = reranker
        self.config = config

    def relevance_scores(self, request):
        return self.search(request, len(self.documents), blend_scores=True)

    def search(self, request: SearchRequest, k: int, *, blend_scores=False) -> list[SearchHit]:
        if k < 1 or not request.query.strip():
            raise ValueError("nonempty query and positive K required")
        _, content = receipt_day(request.query, request.query_date)
        if not query_terms(content):
            hits = self.baseline.search(request, k)
            return relative_scores(hits) if blend_scores else hits

        depth = self.config["rerank_depth"]
        hits = self.baseline.search(request, max(k, depth))
        prefix = hits[:depth]
        if not prefix or (len(prefix) < 2 and not blend_scores):
            return hits[:k]

        scores = self.reranker.score(content.strip(" ,.!?;:"), [self.documents[h.doc_id].doc for h in prefix])
        if len(scores) != len(prefix) or not all(math.isfinite(score) for score in scores):
            raise ValueError("Invalid MiniLM scores")
        minilm_order = sorted(range(len(prefix)), key=lambda i: -scores[i])
        minilm_ranks = {index: rank for rank, index in enumerate(minilm_order, 1)}
        weight = self.config["minilm_weight"]
        order = sorted(range(len(prefix)), key=lambda i: -(
            (1 - weight) / (RRF_CONSTANT + i + 1) + weight / (RRF_CONSTANT + minilm_ranks[i])
        ))
        if blend_scores:
            lexical = relative_scores(hits)
            # The cross-encoder only sees the reranked prefix. Tail candidates
            # retain the lexical component of the same 75/25 blend.
            strength = [(1 - weight) * hit.score for hit in lexical]
            for i, logit in enumerate(scores):
                strength[i] += weight / (1 + math.exp(-max(-700, logit)))
            return [SearchHit(hits[i].doc_id, strength[i]) for i in [*order, *range(depth, len(hits))]][:k]
        reordered = [prefix[i] for i in order] + hits[depth:]
        return [SearchHit(hit.doc_id, 1 / rank) for rank, hit in enumerate(reordered[:k], 1)]


def create_engine(documents: tuple[Document, ...], config: dict, *, model_dir: Path | None = None,
                  device: str | None = None, gpu_memory_mb: int | None = None) -> BM25MiniLMEngine:
    defaults = {
        "minilm_model": "artifacts/models/minilm/model.onnx", "minilm_weight": 0.25,
        "rerank_depth": 20, "inference_threads": 4, "inference_device": "cpu", "gpu_memory_mb": 2048,
    }
    unknown = config.keys() - defaults.keys()
    if unknown:
        raise ValueError(f"Unknown BM25 + MiniLM options: {sorted(unknown)}")
    options = {**defaults, **config}
    if device is not None:
        options["inference_device"] = device
    if gpu_memory_mb is not None:
        options["gpu_memory_mb"] = gpu_memory_mb
    if options["inference_device"] not in ("cpu", "cuda"):
        raise ValueError("inference_device must be cpu or cuda")
    weight = options["minilm_weight"]
    if type(weight) not in (float, int) or not 0 < weight <= 1:
        raise ValueError("minilm_weight must be in (0, 1]")
    for name in ("rerank_depth", "inference_threads", "gpu_memory_mb"):
        if type(options[name]) is not int or options[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    model_path = model_dir / "model.onnx" if model_dir is not None else repository_root() / options["minilm_model"]
    with model_path.open("rb") as weights, model_path.with_name("tokenizer.json").open("rb") as tokenizer:
        identity = {"weights_sha256": file_digest(weights, "sha256").hexdigest(),
                    "tokenizer_sha256": file_digest(tokenizer, "sha256").hexdigest()}
    reranker = MiniLM(model_path, options["inference_threads"], device=options["inference_device"],
                      gpu_memory_mb=options["gpu_memory_mb"])
    options.update(minilm_model=str(model_path), model_identity=identity, runtime=reranker.runtime,
                   providers=reranker.providers, max_tokens=MAX_TOKENS, rrf_constant=RRF_CONSTANT)
    return BM25MiniLMEngine(documents, reranker, options)
