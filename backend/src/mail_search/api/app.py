"""Uvicorn entry point: mail_search.api.app:create_app --factory."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import asyncio
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
from ..application.evaluations import Evaluations
from ..core.datasets import ARCHIVE_USER, mail_datasets, PUBLIC_DATASET
from ..application.mail import MailService, ServiceError
from ..core.engine import LoadedEngine
from ..core.presets import MODELS, model_options, model_settings
from ..core.settings import Settings
from ..storage.database import database_engine
from ..storage.repository import ArchiveStore, MailStore, UnknownMailbox
from . import cursors
from .models import (ErrorResponse, Health, Mailboxes, Messages, MessageResponse,
                     SearchResponse, SearchBody, ScenarioDate, PageLimit, EvaluationSelection)

logger = logging.getLogger("mail_search.api")


def create_app(settings=None, *, loader=None, database_factory=database_engine, store_factory=MailStore):
    @asynccontextmanager
    async def lifespan(app):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="search-engine")
        databases = []
        engines = []
        configs = {}
        cached_models = {}
        app.state.services = {}
        app.state.mail_groups = []
        app.state.archive_stores = {}
        app.state.archives = []
        app.state.evaluations = None
        try:
            stage = "settings"
            try:
                config = settings if settings is not None else Settings.from_env()
                if config.enable_evaluations:
                    app.state.evaluations = Evaluations(config, create_app)
                stage = "database_configuration"
                datasets = mail_datasets(config)

                def initialize(settings, factory=None, *, archive=False):
                    if factory is None:
                        module, name = settings.search_engine_factory.split(":")
                        factory = getattr(importlib.import_module(module), name)
                    result = factory(settings, single_mailbox=ARCHIVE_USER) if archive else factory(settings)
                    if not isinstance(result, LoadedEngine):
                        raise ValueError("Loader must return LoadedEngine")
                    return result
                def select_model(dataset, model, archive):
                    if model not in MODELS:
                        raise ServiceError(422, "unknown_search_model")
                    scoped = configs[dataset]
                    active = app.state.services[dataset]
                    chosen = model_settings(scoped, model)
                    if (not archive and chosen.search_config == scoped.search_config and
                            chosen.search_engine_factory == scoped.search_engine_factory):
                        return active
                    key = (dataset, model, archive)
                    if key not in cached_models:
                        cached_models[key] = initialize(chosen, archive=archive)
                    store = app.state.archive_stores[dataset] if archive else active.store
                    return MailService(store, cached_models[key], executor)

                app.state.mail_model = lambda dataset, model, archive: executor.submit(select_model, dataset, model, archive).result()

                for dataset, (label, archive, url) in datasets.items():
                    scoped = config.model_copy(update=dict(search_dataset=archive, database_url=url))
                    db = database_factory(url.get_secret_value())
                    databases.append(db)
                    stage = "engine_loading"
                    loaded = await asyncio.wrap_future(executor.submit(initialize, scoped, loader))
                    engines.append(loaded)
                    active = MailService(store_factory(db), loaded, executor)
                    app.state.services[dataset] = active
                    configs[dataset] = scoped
                    stage = "compatibility"
                    await run_in_threadpool(active.ready)
                    if config.enable_evaluations:
                        store = ArchiveStore(db)
                        total, latest_date = await run_in_threadpool(store.summary)
                        app.state.archive_stores[dataset] = store
                        app.state.archives.append(dict(id=dataset, name=label, mailbox=ARCHIVE_USER,
                                                       total=total, latest_date=latest_date))
                    if dataset != PUBLIC_DATASET:
                        users = await run_in_threadpool(active.store.list_mailboxes)
                        app.state.mail_groups.append(dict(id=dataset, name=label, items=users))
            except Exception as exc:
                # Never log exception text, paths, SQL, query text or credentials.
                logger.error("startup_not_ready stage=%s category=%s", stage, type(exc).__name__)
            yield
        finally:
            try:
                for preset in [*cached_models.values(), *engines]:
                    await asyncio.wrap_future(executor.submit(preset.close))
            finally:
                if app.state.evaluations is not None:
                    await run_in_threadpool(app.state.evaluations.close)
                await run_in_threadpool(executor.shutdown)
                for db in databases:
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

    def service(dataset=PUBLIC_DATASET):
        if dataset != PUBLIC_DATASET and dataset not in app.state.services:
            raise ServiceError(404, "unknown_mail_dataset")
        result = app.state.services.get(dataset)
        if result is None:
            raise ServiceError(503, "service_unavailable")
        result.ready()
        return result

    def mail_store(dataset, user):
        active = service(dataset)
        if user == ARCHIVE_USER and dataset in app.state.archive_stores:
            return app.state.archive_stores[dataset]
        return active.store

    @app.get("/api/v1/features")
    def features():
        if app.state.evaluations is None:
            return {"evaluations": False}
        return {"evaluations": True, "mail_models": model_options()}

    def evaluations():
        if app.state.evaluations is None:
            raise ServiceError(404, "evaluations_disabled")
        return app.state.evaluations

    @app.get("/api/v1/evaluations")
    def evaluation_catalog():
        return evaluations().catalog()

    @app.post("/api/v1/evaluations", status_code=202)
    def start_evaluation(selection: EvaluationSelection):
        manager = evaluations()
        manager.start(selection.model, selection.dataset)
        return manager.catalog()

    @app.get("/health/live", response_model=Health)
    async def live():
        return {"status": "live"}

    @app.get("/health/ready", response_model=Health)
    def ready():
        service()
        if app.state.evaluations and len(app.state.mail_groups) + 1 != len(app.state.evaluations.datasets):
            raise ServiceError(503, "mail_datasets_unavailable")
        return {"status": "ready"}

    @app.get("/api/v1/mailboxes", response_model=Mailboxes, response_model_exclude_none=True)
    def mailboxes():
        return {"items": service().store.list_mailboxes(), "groups": app.state.mail_groups or None,
                "archives": app.state.archives or None}

    @app.get("/api/v1/mailboxes/{synthetic_user}/messages", response_model=Messages)
    def messages(synthetic_user: str, query_date: ScenarioDate,
                 limit: Annotated[PageLimit, Query(ge=1, le=500)] = 50,
                 cursor: Annotated[str | None, Query(max_length=4096)] = None, dataset: str = PUBLIC_DATASET):
        after = cursors.decode(cursor, synthetic_user, query_date, dataset)
        page = mail_store(dataset, synthetic_user).list_messages(synthetic_user, query_date=query_date, limit=limit, after=after)
        return {"total": page.total, "items": page.items, "next_cursor": cursors.encode(page.next_cursor, dataset)}

    @app.get("/api/v1/mailboxes/{synthetic_user}/messages/{doc_id:path}", response_model=MessageResponse)
    def message(synthetic_user: str, doc_id: str, query_date: ScenarioDate, dataset: str = PUBLIC_DATASET):
        result = mail_store(dataset, synthetic_user).get_message(synthetic_user, doc_id, query_date=query_date)
        if result is None:
            raise ServiceError(404, "message_not_found")
        return {"item": result}

    @app.post("/api/v1/mailboxes/{synthetic_user}/search", response_model=SearchResponse,
              response_model_exclude_unset=True)
    def search(synthetic_user: str, body: SearchBody, explain: bool = False,
               model: Annotated[str | None, Query(max_length=64)] = None, dataset: str = PUBLIC_DATASET):
        active = service(dataset)
        archive = synthetic_user == ARCHIVE_USER and dataset in app.state.archive_stores
        if model is not None or archive:
            if app.state.evaluations is None:
                raise ServiceError(422, "model_selection_disabled")
            active = app.state.mail_model(dataset, model if model is not None else next(iter(MODELS)), archive)
        return active.search(synthetic_user, body.query, body.query_date, body.limit, explain=explain)

    return app
