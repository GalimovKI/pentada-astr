"""Search presets shared by interactive dev mail and evaluation runs."""
from importlib.util import find_spec

from .paths import repository_root
from .settings import DEFAULT_SEARCH_FACTORY, LEGACY_SEARCH_FACTORY

MODELS = {
    "bm25-event-aware": ("BM25 с учётом событий", DEFAULT_SEARCH_FACTORY),
    "bm25-minilm": ("BM25 по дате + MiniLM (75/25)", "mail_search.core.engine:load_bm25_minilm"),
    "bm25-improved": ("BM25 с весами запроса", LEGACY_SEARCH_FACTORY),
    "bm25-stemmed": ("BM25 со стеммингом", LEGACY_SEARCH_FACTORY),
    "bm25": ("BM25 базовый", LEGACY_SEARCH_FACTORY),
}


def available_models(settings):
    directory = settings.minilm_model_dir or repository_root() / "artifacts/models/minilm"
    has_minilm = ((directory / "model.onnx").is_file() and (directory / "tokenizer.json").is_file()
                  and find_spec("onnxruntime") is not None and find_spec("tokenizers") is not None)
    return {key: value for key, value in MODELS.items() if key != "bm25-minilm" or has_minilm}


def model_options(models):
    return [dict(id=key, name=value[0]) for key, value in models.items()]


def model_settings(settings, model):
    return settings.model_copy(update=dict(search_engine_factory=MODELS[model][1],
        search_config=repository_root() / "configs/search" / (model + ".json"), enable_evaluations=False))
