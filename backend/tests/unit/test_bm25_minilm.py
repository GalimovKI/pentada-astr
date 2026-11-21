from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import sys
from types import SimpleNamespace

from mail_search.core.presets import available_models
from mail_search.core.settings import Settings
from mail_search.domain.models import Document, SearchHit, SearchRequest
from mail_search.search.bm25_minilm import BM25MiniLMEngine, MiniLM


class BM25MiniLMTests(TestCase):
    def test_fixed_prefix_keeps_tail_and_reorders_by_weighted_ranks(self):
        day = date(2028, 11, 20)
        documents = tuple(Document(str(i), "box", f"Письмо {i}", day) for i in range(21))
        model = Mock()
        model.score.return_value = [0, 20, *range(1, 19)]
        engine = BM25MiniLMEngine(documents, model, {"minilm_weight": 0.25, "rerank_depth": 20})
        engine.baseline = Mock()
        engine.baseline.search.return_value = [SearchHit(str(i), 21 - i) for i in range(21)]
        request = SearchRequest("заказ, полученный вчера", "box", date(2028, 11, 21))

        output = engine.search(request, 21)
        self.assertEqual({hit.doc_id for hit in output}, {doc.doc_id for doc in documents})
        self.assertEqual(output[0].doc_id, "1")
        self.assertEqual(output[-1].doc_id, "20")
        model.score.assert_called_once_with("заказ", [doc.doc for doc in documents[:20]])

        relevance = engine.relevance_scores(request)
        self.assertEqual([hit.doc_id for hit in relevance], [hit.doc_id for hit in output])
        self.assertAlmostEqual(relevance[1].score, 0.75 + 0.25 * 0.5)
        self.assertAlmostEqual(relevance[-1].score, 0.75 / 21)
        self.assertNotEqual(relevance[1].score, output[1].score)

    def test_date_only_skips_minilm(self):
        day = date(2028, 11, 20)
        model = Mock()
        documents = (Document("a", "box", "Письмо", day), Document("b", "box", "Другое письмо", day))
        engine = BM25MiniLMEngine(documents, model, {"minilm_weight": 0.25, "rerank_depth": 20})
        request = SearchRequest("вчера", "box", date(2028, 11, 21))

        self.assertEqual(engine.search(request, 10), engine.baseline.search(request, 10))
        model.score.assert_not_called()

    def test_preset_requires_local_artifacts_and_runtime(self):
        with TemporaryDirectory() as root:
            path = Path(root)
            settings = Settings(database_url="postgresql://unused", minilm_model_dir=path)
            self.assertNotIn("bm25-minilm", available_models(settings))
            (path / "model.onnx").touch()
            (path / "tokenizer.json").touch()
            with patch("mail_search.core.presets.find_spec", return_value=None):
                self.assertNotIn("bm25-minilm", available_models(settings))
            with patch("mail_search.core.presets.find_spec", return_value=object()):
                self.assertIn("bm25-minilm", available_models(settings))


class MiniLMDeviceTests(TestCase):
    def runtime(self, available, active):
        runtime = Mock(__version__="test")
        runtime.get_available_providers.return_value = available
        runtime.InferenceSession.return_value.get_providers.return_value = active
        runtime.InferenceSession.return_value.get_inputs.return_value = []
        tokenizer = Mock()
        tokenizer.from_file.return_value.token_to_id.return_value = 1
        return runtime, {"numpy": Mock(), "onnxruntime": runtime,
                         "tokenizers": SimpleNamespace(Tokenizer=tokenizer)}

    def test_cpu_does_not_load_cuda_libraries(self):
        runtime, modules = self.runtime(["CPUExecutionProvider"], ["CPUExecutionProvider"])
        with patch.dict(sys.modules, modules):
            MiniLM(Path("model.onnx"), 4)
        runtime.preload_dlls.assert_not_called()

    def test_cuda_rejects_missing_provider(self):
        runtime, modules = self.runtime(["CPUExecutionProvider"], ["CPUExecutionProvider"])
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(RuntimeError, "requires"):
            MiniLM(Path("model.onnx"), 4, device="cuda")
        runtime.InferenceSession.assert_not_called()

    def test_cuda_rejects_silent_initialization_fallback(self):
        _, modules = self.runtime(["CUDAExecutionProvider"], ["CPUExecutionProvider"])
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(RuntimeError, "refusing"):
            MiniLM(Path("model.onnx"), 4, device="cuda")

    def test_cuda_limits_arena_and_disables_runtime_fallback(self):
        runtime, modules = self.runtime(["CUDAExecutionProvider"], ["CUDAExecutionProvider", "CPUExecutionProvider"])
        with patch.dict(sys.modules, modules):
            MiniLM(Path("model.onnx"), 4, device="cuda", gpu_memory_mb=1024)
        options = runtime.InferenceSession.call_args.kwargs["providers"][0][1]
        self.assertEqual(options["gpu_mem_limit"], 1024**3)
        self.assertEqual(options["device_id"], 0)
        self.assertEqual(options["use_tf32"], 0)
        runtime.InferenceSession.return_value.disable_fallback.assert_called_once()
