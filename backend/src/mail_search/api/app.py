"""Uvicorn entry point: mail_search.api.app:create_app --factory."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import importlib
import logging
from time import perf_counter
from typing import Annotated
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from ..application.mail import MailService, ServiceError
from ..core.engine import LoadedEngine
from ..core.settings import Settings
from ..storage.database import database_engine
from ..storage.repository import MailStore, UnknownMailbox
from . import cursors
from .models import (ErrorResponse, Health, Mailboxes, Messages, MessageResponse,
                     SearchResponse, SearchBody, SpellingBody, ScenarioDate, PageLimit)

logger = logging.getLogger("mail_search.api")


def create_app(settings=None, *, loader=None, database_factory=database_engine, store_factory=MailStore):
    @asynccontextmanager
    async def lifespan(app):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="search-engine")
        db = loaded = None
        app.state.service = None
        try:
            stage = "settings"
            try:
                config = settings if settings is not None else Settings.from_env()
                stage = "database_configuration"
                db = database_factory(config.database_url.get_secret_value())
                def initialize():
                    factory = loader
                    if factory is None:
                        module, name = config.search_engine_factory.split(":")
                        factory = getattr(importlib.import_module(module), name)
                    result = factory(config)
                    if not isinstance(result, LoadedEngine):
                        raise ValueError("Loader must return LoadedEngine")
                    return result
                stage = "engine_loading"
                loaded = await run_in_threadpool(lambda: executor.submit(initialize).result())
                app.state.service = MailService(store_factory(db), loaded, executor)
                stage = "compatibility"
                await run_in_threadpool(app.state.service.ready)
            except Exception as exc:
                # Never log exception text, paths, SQL, query text or credentials.
                logger.error("startup_not_ready stage=%s category=%s", stage, type(exc).__name__)
            yield
        finally:
            try:
                if loaded is not None:
                    await run_in_threadpool(lambda: executor.submit(loaded.close).result())
            finally:
                await run_in_threadpool(executor.shutdown)
                if db is not None:
                    await run_in_threadpool(db.dispose)

    errors = {status: {"model": ErrorResponse} for status in (404, 422, 500, 503)}
    app = FastAPI(title="Mail Search API", version="1.0.0", lifespan=lifespan, responses=errors)

    def error(status, code):
        return JSONResponse({"error": {"code": code}}, status_code=status)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        logger.warning("request_failed code=%s", exc.code)
        return error(exc.status, exc.code)

    @app.exception_handler(UnknownMailbox)
    async def unknown_mailbox(request, exc):
        return error(404, "mailbox_not_found")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logger.warning("database_unavailable")
        return error(503, "database_unavailable")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(422, "validation_error")

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(exc.status_code, "http_error")

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        logger.error("internal_error category=%s", type(exc).__name__)
        return error(500, "internal_error")

    @app.middleware("http")
    async def timing(request, call_next):
        start = perf_counter()
        response = await call_next(request)
        if request.method == "POST" and request.url.path.endswith("/search"):
            elapsed = (perf_counter() - start) * 1000
            response.headers["Server-Timing"] = f"search;dur={elapsed:.3f}"
            logger.info("search_response status=%d duration_ms=%.3f", response.status_code, elapsed)
        return response

    def service():
        result = app.state.service
        if result is None:
            raise ServiceError(503, "service_unavailable")
        result.ready()
        return result

    @app.post("/api/v1/spelling")
    def spelling(body: SpellingBody):
        from ..application.spelling import spelling_hints
        return spelling_hints(body.query, body.cursor, expand_word_forms=body.expand_word_forms)

    @app.get("/health/live", response_model=Health)
    async def live():
        return {"status": "live"}

    @app.get("/health/ready", response_model=Health)
    def ready():
        service()
        return {"status": "ready"}

    @app.get("/api/v1/mailboxes", response_model=Mailboxes)
    def mailboxes():
        return {"items": service().store.list_mailboxes()}

    @app.get("/api/v1/mailboxes/{synthetic_user}/messages", response_model=Messages)
    def messages(synthetic_user: str, query_date: ScenarioDate,
                 limit: Annotated[PageLimit, Query(ge=1, le=500)] = 50,
                 cursor: Annotated[str | None, Query(max_length=4096)] = None):
        after = cursors.decode(cursor, synthetic_user, query_date)
        page = service().store.list_messages(synthetic_user, query_date=query_date, limit=limit, after=after)
        return {"items": page.items, "next_cursor": cursors.encode(page.next_cursor)}

    @app.get("/api/v1/mailboxes/{synthetic_user}/messages/{doc_id}", response_model=MessageResponse)
    def message(synthetic_user: str, doc_id: str, query_date: ScenarioDate):
        result = service().store.get_message(synthetic_user, doc_id, query_date=query_date)
        if result is None:
            raise ServiceError(404, "message_not_found")
        return {"item": result}

    @app.post("/api/v1/mailboxes/{synthetic_user}/search", response_model=SearchResponse,
              response_model_exclude_unset=True)
    def search(synthetic_user: str, body: SearchBody, explain: bool = False):
        query = body.query
        if body.correct_typos:
            from ..application.spelling import correct_query
            query, _ = correct_query(query, preserve_forms=body.expand_word_forms)
        alternatives = ()
        if body.expand_word_forms:
            from ..application.word_forms import search_queries
            query, *alternatives = search_queries(query)
        return service().search(synthetic_user, query, body.query_date, body.limit,
                                explain=explain, alternatives=alternatives)

    return app
