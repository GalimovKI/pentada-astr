"""Server-only settings; never imported by offline commands."""
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from .paths import repository_root


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database_url: SecretStr
    search_engine_factory: str = Field(default="mail_search.core.engine:load_bm25", pattern=r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")
    search_config: Path = repository_root() / "configs/search/bm25-stemmed.json"
    search_dataset: Path = repository_root() / "data/raw/mipt_mail_search_participants.zip"

    @classmethod
    def from_env(cls):
        return cls(**{name: os.environ[name.upper()] for name in cls.model_fields
                      if name.upper() in os.environ})
