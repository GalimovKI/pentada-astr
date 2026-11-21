import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mail_search.core.provenance import code_version


class ProvenanceTests(unittest.TestCase):
    def test_source_fingerprint_includes_nested_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "mail_search"
            (package / "core").mkdir(parents=True)
            (package / "search").mkdir()
            provenance = package / "core/provenance.py"
            provenance.write_text("# fixture\n")
            engine = package / "search/bm25.py"
            engine.write_text("value = 1\n")
            with patch("mail_search.core.provenance.__file__", str(provenance)):
                original = code_version()["sha256"]
                engine.write_text("value = 2\n")
                self.assertNotEqual(original, code_version()["sha256"])
