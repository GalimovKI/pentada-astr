"""Server loader contract, separate from the unchanged offline factory."""
from dataclasses import dataclass, replace
from functools import partial
from typing import Callable
import json
from ..domain.models import SearchEngine
from ..ingestion.dataset import load_dataset
from ..search.bm25 import create_engine
from .settings import LEGACY_SEARCH_CONFIG, Settings


@dataclass(frozen=True)
class LoadedEngine:
    engine: SearchEngine
    fingerprint: str
    close: Callable[[], None] = lambda: None


def _load_engine(settings: Settings, factory, config_path, single_mailbox) -> LoadedEngine:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Expected configuration object")
    dataset = load_dataset(settings.search_dataset)
    documents = tuple(dataset.documents.values())
    if single_mailbox is not None:
        documents = tuple(replace(doc, synthetic_user=single_mailbox) for doc in documents)
    return LoadedEngine(factory(documents, config),
                        dataset.summary["fingerprint"])


def load_bm25(settings: Settings, *, single_mailbox=None) -> LoadedEngine:
    path = settings.search_config if "search_config" in settings.model_fields_set else LEGACY_SEARCH_CONFIG
    return _load_engine(settings, create_engine, path, single_mailbox)


def load_event_aware(settings: Settings, *, single_mailbox=None) -> LoadedEngine:
    from ..search.event_aware import create_engine as create_event_aware_engine

    return _load_engine(settings, create_event_aware_engine, settings.search_config, single_mailbox)


def load_bm25_minilm(settings: Settings, *, single_mailbox=None) -> LoadedEngine:
    from ..search.bm25_minilm import create_engine as create_bm25_minilm_engine

    factory = partial(create_bm25_minilm_engine, model_dir=settings.minilm_model_dir)
    return _load_engine(settings, factory, settings.search_config, single_mailbox)
