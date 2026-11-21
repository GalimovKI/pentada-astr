"""Application policy. SQL runs in HTTP workers; engine calls on its owning thread."""
import math
import re
from itertools import islice
from .passages import find_passage, query_terms
from ..search.dates import receipt_day, target_day
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

    def search(self, user, query, query_date, limit, *, explain=False, min_similarity=None, offset=0, relevance_threshold=None):
        self.ready()
        if user not in self.store.list_mailboxes():
            raise UnknownMailbox(user)
        def invoke():
            # Bound materialization, including a misbehaving lazy engine result.
            request = SearchRequest(query, user, query_date)
            total = None
            if relevance_threshold is not None:
                hits = [hit for hit in self.loaded.engine.relevance_scores(request)
                        if hit.score >= relevance_threshold]
                total = len(hits)
            elif min_similarity is None:
                result = self.loaded.engine.search(request, limit)
                hits = list(islice(result, limit + 1))
            else:
                result, total = self.loaded.engine.search_page(request, limit, min_similarity=min_similarity, offset=offset)
                hits = list(islice(result, limit + 1))
            if (relevance_threshold is None and len(hits) > limit) or any(
                not isinstance(h, SearchHit) or not isinstance(h.doc_id, str) or not h.doc_id
                or type(h.score) not in (int, float) or not math.isfinite(h.score) for h in hits
            ) or len({h.doc_id for h in hits}) != len(hits):
                raise ServiceError(500, "engine_contract_violation")
            return hits, total
        try:
            hits, total = self.executor.submit(invoke).result()
        except ServiceError:
            raise
        except Exception:
            raise ServiceError(500, "engine_failure") from None
        ids = [h.doc_id for h in hits]
        page = {} if total is None else {"total": total}
        if explain:
            config = getattr(self.loaded.engine, "config", {})
            parser = target_day if isinstance(config, dict) and config.get("date_mode") == "legacy" else receipt_day
            day, content = ((None, query) if isinstance(config, dict) and config.get("date_mode") == "availability_only"
                            else parser(query, query_date))
            terms = query_terms(content)
            documents = self.store.get_messages(user, ids, query_date=query_date)
            if [doc.doc_id for doc in documents] != ids:
                raise ServiceError(500, "engine_contract_violation")
            return dict(**page, receipt_date=day, items=[
                dict(doc_id=d.doc_id, synthetic_user=d.synthetic_user, doc_dt=d.doc_dt,
                     snippet=d.doc[:200], score=h.score, passage=find_passage(d.doc, terms))
                for h, d in zip(hits, documents)])
        previews = self.store.get_previews(user, ids, query_date=query_date)
        if [p.doc_id for p in previews] != ids:
            raise ServiceError(500, "engine_contract_violation")
        return dict(**page, items=[dict(doc_id=p.doc_id, synthetic_user=p.synthetic_user, doc_dt=p.doc_dt,
                                snippet=p.snippet, score=h.score) for h, p in zip(hits, previews)])
