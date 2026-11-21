from datetime import date
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock

from mail_search.domain.models import Document, SearchRequest


@skipUnless(find_spec("numpy"), "requires dense retrieval dependencies")
class E5Tests(TestCase):
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
