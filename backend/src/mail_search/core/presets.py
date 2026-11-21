"""Search presets shared by interactive dev mail and evaluation runs."""
from .paths import repository_root
from .settings import DEFAULT_SEARCH_FACTORY, LEGACY_SEARCH_FACTORY

MODELS = {
    "bm25-event-aware": ("BM25 с учётом событий", DEFAULT_SEARCH_FACTORY),
    "bm25-improved": ("BM25 с весами запроса", LEGACY_SEARCH_FACTORY),
    "bm25-stemmed": ("BM25 со стеммингом", LEGACY_SEARCH_FACTORY),
    "bm25": ("BM25 базовый", LEGACY_SEARCH_FACTORY),
}


def model_options():
    return [dict(id=key, name=value[0]) for key, value in MODELS.items()]


def model_settings(settings, model):
    return settings.model_copy(update=dict(search_engine_factory=MODELS[model][1],
        search_config=repository_root() / "configs/search" / (model + ".json"), enable_evaluations=False))
