import hashlib
import subprocess
from pathlib import Path

from .paths import repository_root


def code_version(engine_module=None) -> dict:
    """Hash all package sources, including nested modules and an external factory."""
    package = Path(__file__).resolve().parents[1]
    files = {p.relative_to(package).as_posix(): p for p in package.rglob("*.py")}
    if engine_module is not None and getattr(engine_module, "__file__", None):
        path = Path(engine_module.__file__).resolve()
        if path not in (p.resolve() for p in files.values()):
            files[f"engine:{engine_module.__name__}"] = path
    digest = hashlib.sha256()
    for name, path in sorted(files.items()):
        digest.update(name.encode() + b"\0" + path.read_bytes())
    result = {"sha256": digest.hexdigest(), "git_commit": None, "git_dirty": None}
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository_root(), capture_output=True, text=True, timeout=5)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repository_root(), capture_output=True, text=True, timeout=5)
        if commit.returncode == status.returncode == 0:
            result.update(git_commit=commit.stdout.strip(), git_dirty=bool(status.stdout.strip()))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result
