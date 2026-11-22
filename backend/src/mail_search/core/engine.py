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

    model_dir = settings.minilm_model_dir
    if settings.minilm_device == "cpu" and settings.minilm_cpu_model_dir is not None:
        model_dir = settings.minilm_cpu_model_dir
    factory = partial(create_bm25_minilm_engine, model_dir=model_dir,
                      device=settings.minilm_device, gpu_memory_mb=settings.minilm_gpu_memory_mb)
    return _load_engine(settings, factory, settings.search_config, single_mailbox)


def load_e5(settings: Settings, *, single_mailbox=None) -> LoadedEngine:
    from ..search.e5 import dataset_engine

    dataset = load_dataset(settings.search_dataset)
    engine = dataset_engine(dataset, settings.e5_model_dir, settings.e5_index_dir, single_mailbox,
                            device=settings.e5_device)
    return LoadedEngine(engine, dataset.summary["fingerprint"])


def combine_e5_hybrid(settings, lexical: LoadedEngine, dense: LoadedEngine) -> LoadedEngine:
    from ..search.e5_hybrid import E5HybridEngine

    if lexical.fingerprint != dense.fingerprint:
        raise ValueError("E5 and BM25 require the same corpus")
    config = json.loads(settings.search_config.read_text(encoding="utf-8"))
    return LoadedEngine(E5HybridEngine(lexical.engine, dense.engine, config), dense.fingerprint)


def load_e5_hybrid(settings: Settings, *, single_mailbox=None) -> LoadedEngine:
    from .presets import model_settings

    lexical = load_event_aware(model_settings(settings, "bm25-event-aware"), single_mailbox=single_mailbox)
    dense = load_e5(settings, single_mailbox=single_mailbox)
    return combine_e5_hybrid(settings, lexical, dense)
