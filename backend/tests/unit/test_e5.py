from datetime import date
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock

from mail_search.domain.models import Document, SearchRequest


@skipUnless(find_spec("numpy"), "requires dense retrieval dependencies")
class E5Tests(TestCase):
    def test_cuda_profile_requires_transformer_kernels_on_gpu(self):
        from mail_search.search.e5 import verify_cuda_profile

        def node(op, provider):
            return {"cat": "Node", "args": {"op_name": op, "provider": provider}}
        gpu = node("MatMul", "CUDAExecutionProvider")
        cpu = node("Gemm", "CPUExecutionProvider")
        shape = node("Shape", "CPUExecutionProvider")
        verify_cuda_profile([gpu, shape])
        for events in ([], [shape], [cpu], [gpu, cpu]):
            with self.subTest(events=events), self.assertRaises(RuntimeError):
                verify_cuda_profile(events)

    def test_similarity_counts_all_matches_before_paging_and_includes_boundary(self):
        import numpy as np
        from mail_search.search.e5 import E5Engine

        day = date(2029, 1, 1)
        docs = [Document(str(i), "box", "text", day) for i in range(120)]
        vectors = np.array([[0.5, 0.5]] * 119 + [[0.25, 0.75]], dtype=np.float32)
        model = Mock()
        model.encode.return_value = np.array([[1, 0]], dtype=np.float32)
        engine = E5Engine(docs, vectors, model)
        query = SearchRequest("query", "box", day)
        pages = [engine.search_page(query, 50, min_similarity=0.5, offset=i) for i in (0, 50, 100)]
        self.assertEqual([total for _, total in pages], [119] * 3)
        self.assertEqual([hit.doc_id for hits, _ in pages for hit in hits], [str(i) for i in range(119)])
        self.assertEqual(engine.search_page(query, 50, min_similarity=0.50001), ([], 0))
        self.assertEqual(engine.search(query, 10), pages[0][0][:10])

    def test_full_mailbox_search_availability_archive_and_index_reuse(self):
        import numpy as np
        from mail_search.search.e5 import DIMENSION, E5Engine, passage_vectors

        day = date(2029, 1, 1)
        docs = [
            Document("a", "mine", "покупка", day),
            Document("b", "other", "счёт", day),
            Document("c", "mine", "платёж", None),
            Document("d", "mine", "счёт из будущего", date(2030, 1, 1)),
        ]
        def encode(texts):
            values = np.zeros((len(texts), DIMENSION), dtype=np.float32)
            for i, text in enumerate(texts):
                values[i, int(text == "passage: покупка")] = 1
            return values
        model = Mock(identity="test", encode=Mock(side_effect=encode))
        with TemporaryDirectory() as directory:
            vectors = passage_vectors(docs, "corpus", model, Path(directory))
            self.assertEqual(set(model.encode.call_args.args[0]), {"passage: " + d.doc for d in docs})
            model.encode.reset_mock()
            cached = passage_vectors(docs, "corpus", model, Path(directory))
            np.testing.assert_equal(vectors, cached)
            model.encode.assert_not_called()
            engine = E5Engine(docs, cached, model)
            hits = engine.search(SearchRequest("оплата", "mine", day), 10)
            self.assertEqual([(hit.doc_id, hit.score) for hit in hits], [("c", 1), ("a", 0)])
            model.encode.assert_called_once_with(["query: оплата"])
            archive = E5Engine(docs, cached, model, single_mailbox="@archive")
            hits = archive.search(SearchRequest("оплата", "@archive", day), 2)
            self.assertEqual([hit.doc_id for hit in hits], ["b", "c"])
            self.assertEqual(engine.search(SearchRequest("оплата", "@archive", day), 2), [])
