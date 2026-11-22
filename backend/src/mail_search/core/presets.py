"""Search presets shared by interactive dev mail and evaluation runs."""
from importlib.util import find_spec

from .paths import repository_root
from .settings import DEFAULT_SEARCH_FACTORY, LEGACY_SEARCH_FACTORY

E5_HYBRIDS = {
    "e5-bm25-rrf": "BM25 + E5 · объединение рангов",
    "e5-then-bm25": "E5 → BM25 · пересортировка кандидатов",
    "bm25-then-e5": "BM25 → E5 · пересортировка по смыслу",
}
E5_MODELS = {"e5-cosine", *E5_HYBRIDS}

MODELS = {
    "bm25-event-aware": ("BM25 с учётом событий", DEFAULT_SEARCH_FACTORY),
    "e5-cosine": ("E5 · косинусная близость", "mail_search.core.engine:load_e5"),
    **{key: (name, "mail_search.core.engine:load_e5_hybrid") for key, name in E5_HYBRIDS.items()},
    "bm25-minilm": ("BM25 по дате + MiniLM (75/25)", "mail_search.core.engine:load_bm25_minilm"),
    "bm25-improved": ("BM25 с весами запроса", LEGACY_SEARCH_FACTORY),
    "bm25-stemmed": ("BM25 со стеммингом", LEGACY_SEARCH_FACTORY),
    "bm25": ("BM25 базовый", LEGACY_SEARCH_FACTORY),
}


# Mail defaults calibrated separately from the fixed-K evaluation protocol.
MAIL_THRESHOLDS = {
    "bm25-event-aware": 0.84,
    "e5-cosine": 0.835,
    "e5-bm25-rrf": 0.80,
    "e5-then-bm25": 0.84,
    "bm25-then-e5": 0.84,
    "bm25-minilm": 0.63,
    "bm25-improved": 0.84,
    "bm25-stemmed": 0.75,
    "bm25": 0.76,
}


def available_models(settings):
    directories = {
        "bm25-minilm": settings.minilm_model_dir or repository_root() / "artifacts/models/minilm",
        **dict.fromkeys(E5_MODELS, settings.e5_model_dir),
    }
    runtime = all(find_spec(module) is not None for module in ("onnxruntime", "tokenizers", "numpy"))
    return {key: value for key, value in MODELS.items() if key not in directories or
            (runtime and all((directories[key] / name).is_file() for name in ("model.onnx", "tokenizer.json")))}


def model_options(models):
    return [dict(id=key, name=value[0]) for key, value in models.items()]


def model_settings(settings, model):
    return settings.model_copy(update=dict(search_engine_factory=MODELS[model][1],
        search_config=repository_root() / "configs/search" / (model + ".json"), enable_evaluations=False))
