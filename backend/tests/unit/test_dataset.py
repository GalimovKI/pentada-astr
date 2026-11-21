import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mail_search.core.errors import ValidationError
from mail_search.ingestion.dataset import load_dataset
from tests.fixtures.dataset import fixture


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture(Path(self.temp.name) / "data")

    def test_zip_and_directory_have_same_fingerprint(self):
        archive = Path(self.temp.name) / "data.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for path in self.root.iterdir():
                z.write(path, path.name)
        a, b = load_dataset(self.root), load_dataset(archive)
        self.assertEqual(a.summary, b.summary)
        self.assertEqual(a.summary["documents"], 5)
        self.assertEqual(a.summary["unknown_document_dates"], 1)

    def test_integrity_failure_precedes_evaluation(self):
        with (self.root / "documents.jsonl").open("ab") as f:
            f.write(b"\n")
        with self.assertRaisesRegex(ValidationError, "SHA-256 mismatch"):
            load_dataset(self.root)

    def test_manifest_counts_checked(self):
        path = self.root / "manifest.json"
        data = json.loads(path.read_text())
        data["documents"] = 999
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValidationError, "row count mismatch"):
            load_dataset(self.root)

    def test_duplicate_ids_rejected_even_with_valid_hashes(self):
        records = [json.loads(line) for line in (self.root / "documents.jsonl").read_text().splitlines()]
        fixture(self.root, documents=records + [records[0]])
        with self.assertRaisesRegex(ValidationError, "duplicate doc_id"):
            load_dataset(self.root)

    def test_bad_positive_qrels_rejected(self):
        for did, message in (("missing", "unknown"), ("other-box", "another mailbox"), ("future", "unavailable")):
            with self.subTest(doc_id=did):
                fixture(self.root, qrels=[{"query_id": "q1", "doc_id": did, "relevance": 1}])
                with self.assertRaisesRegex(ValidationError, message):
                    load_dataset(self.root)

    def test_schema_and_calendar_validation(self):
        records = [json.loads(line) for line in (self.root / "documents.jsonl").read_text().splitlines()]
        records[0]["doc_dt"] = "2025-02-30"
        fixture(self.root, documents=records)
        with self.assertRaisesRegex(ValidationError, "invalid calendar date"):
            load_dataset(self.root)
        del records[0]["doc_dt"]
        fixture(self.root, documents=records)
        with self.assertRaisesRegex(ValidationError, "missing doc_dt"):
            load_dataset(self.root)
