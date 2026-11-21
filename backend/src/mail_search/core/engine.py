"""Server loader contract, separate from the unchanged offline factory."""
from dataclasses import dataclass
from typing import Callable
import json
from ..domain.models import SearchEngine
from ..ingestion.dataset import load_dataset
from ..search.bm25 import create_engine
from .settings import Settings


@dataclass(frozen=True)
class LoadedEngine:
    engine: SearchEngine
    fingerprint: str
    close: Callable[[], None] = lambda: None


def load_bm25(settings: Settings) -> LoadedEngine:
    config = json.loads(settings.search_config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Expected configuration object")
    dataset = load_dataset(settings.search_dataset)
    return LoadedEngine(create_engine(tuple(dataset.documents.values()), config),
                        dataset.summary["fingerprint"])
