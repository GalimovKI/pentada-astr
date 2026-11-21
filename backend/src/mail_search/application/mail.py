"""Application policy. SQL runs in HTTP workers; engine calls on its owning thread."""
import math
import re
from itertools import islice
from ..domain.models import SearchRequest, SearchHit
from ..storage.repository import UnknownMailbox


class ServiceError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class MailService:
    def __init__(self, store, loaded, executor):
        self.store, self.loaded, self.executor = store, loaded, executor

    def ready(self):
        if self.loaded is None or not callable(getattr(self.loaded.engine, "search", None)):
            raise ServiceError(503, "engine_unavailable")
        if not isinstance(self.loaded.fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", self.loaded.fingerprint):
            raise ServiceError(503, "engine_metadata_missing")
        fingerprint = self.store.import_fingerprint()
        if not fingerprint:
            raise ServiceError(503, "import_metadata_missing")
        if fingerprint != self.loaded.fingerprint:
            raise ServiceError(503, "dataset_mismatch")

    def search(self, user, query, query_date, limit):
        self.ready()
        if user not in self.store.list_mailboxes():
            raise UnknownMailbox(user)
        def invoke():
            # Bound materialization, including a misbehaving lazy engine result.
            hits = list(islice(self.loaded.engine.search(SearchRequest(query, user, query_date), limit), limit + 1))
            if len(hits) > limit or any(
                not isinstance(h, SearchHit) or not isinstance(h.doc_id, str) or not h.doc_id
                or type(h.score) not in (int, float) or not math.isfinite(h.score) for h in hits
            ) or len({h.doc_id for h in hits}) != len(hits):
                raise ServiceError(500, "engine_contract_violation")
            return hits
        try:
            hits = self.executor.submit(invoke).result()
        except ServiceError:
            raise
        except Exception:
            raise ServiceError(500, "engine_failure") from None
        previews = self.store.get_previews(user, [h.doc_id for h in hits], query_date=query_date)
        if [p.doc_id for p in previews] != [h.doc_id for h in hits]:
            raise ServiceError(500, "engine_contract_violation")
        return [dict(doc_id=p.doc_id, synthetic_user=p.synthetic_user, doc_dt=p.doc_dt,
                     snippet=p.snippet, score=h.score) for h, p in zip(hits, previews)]
