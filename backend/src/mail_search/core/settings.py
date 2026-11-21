"""Server-only settings; never imported by offline commands."""
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from .paths import DEFAULT_SEARCH_CONFIG, repository_root

DEFAULT_SEARCH_FACTORY = "mail_search.core.engine:load_event_aware"
LEGACY_SEARCH_FACTORY = "mail_search.core.engine:load_bm25"
LEGACY_SEARCH_CONFIG = repository_root() / "configs/search/bm25-stemmed.json"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enable_evaluations: bool = False
    evaluation_dir: Path = Path.home() / ".local/state/pentada/evaluations"
    database_url: SecretStr
    search_engine_factory: str = Field(default=DEFAULT_SEARCH_FACTORY, pattern=r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")
    search_config: Path = DEFAULT_SEARCH_CONFIG
    search_dataset: Path = repository_root() / "data/raw/mipt_mail_search_participants.zip"

    @model_validator(mode="before")
    @classmethod
    def search_defaults(cls, values):
        if not isinstance(values, dict):
            return values
        if "search_config" in values and "search_engine_factory" not in values:
            return {**values, "search_engine_factory": LEGACY_SEARCH_FACTORY}
        if values.get("search_engine_factory", DEFAULT_SEARCH_FACTORY) != DEFAULT_SEARCH_FACTORY:
            return {"search_config": LEGACY_SEARCH_CONFIG, **values}
        return values

    @classmethod
    def from_env(cls):
        return cls(**{name: os.environ[name.upper()] for name in cls.model_fields
                      if name.upper() in os.environ})
