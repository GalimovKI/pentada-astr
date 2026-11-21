from pathlib import Path


def repository_root() -> Path:
    """Locate the editable checkout independently of the command's cwd."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "backend" / "pyproject.toml").is_file() and (candidate / "PROJECT.md").is_file():
            return candidate
    return Path.cwd()


DEFAULT_SEARCH_CONFIG = repository_root() / "configs/search/bm25-event-aware.json"
