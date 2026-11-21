"""Server loader contract, separate from the unchanged offline factory."""
from dataclasses import dataclass
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


def _load_engine(settings: Settings, factory, config_path) -> LoadedEngine:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Expected configuration object")
    dataset = load_dataset(settings.search_dataset)
    return LoadedEngine(factory(tuple(dataset.documents.values()), config),
                        dataset.summary["fingerprint"])


def load_bm25(settings: Settings) -> LoadedEngine:
    path = settings.search_config if "search_config" in settings.model_fields_set else LEGACY_SEARCH_CONFIG
    return _load_engine(settings, create_engine, path)


def load_event_aware(settings: Settings) -> LoadedEngine:
    from ..search.event_aware import create_engine as create_event_aware_engine

    return _load_engine(settings, create_event_aware_engine, settings.search_config)
