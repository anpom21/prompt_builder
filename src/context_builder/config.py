from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_SCHEMA_VERSION = 1
CONFIG_DIR = Path.home() / ".context_builder"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _default_config() -> dict[str, Any]:
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "opened_repositories": [],
    }


def load_config() -> dict[str, Any]:
    """Load the user-level Context Builder configuration."""
    try:
        payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_config()

    if not isinstance(payload, dict):
        return _default_config()

    repositories = payload.get("opened_repositories", [])
    if not isinstance(repositories, list):
        repositories = []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in repositories:
        if not isinstance(value, str) or not value.strip():
            continue
        path = _normalize_repository_path(value)
        if path in seen:
            continue
        seen.add(path)
        normalized.append(path)

    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "opened_repositories": normalized,
    }


def save_config(config: dict[str, Any]) -> None:
    """Persist configuration atomically in ~/.context_builder/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    normalized = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "opened_repositories": list(config.get("opened_repositories", [])),
    }
    temporary = CONFIG_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(CONFIG_FILE)


def opened_repositories(*, existing_only: bool = True) -> list[Path]:
    """Return repositories in most-recently-opened order."""
    paths = [Path(value).expanduser() for value in load_config()["opened_repositories"]]
    if existing_only:
        paths = [path for path in paths if path.is_dir()]
    return paths


def record_opened_repository(repository_root: str | Path) -> list[Path]:
    """Move a repository to the front of the persisted history."""
    normalized = _normalize_repository_path(repository_root)
    config = load_config()
    repositories = [
        value
        for value in config["opened_repositories"]
        if _normalize_repository_path(value) != normalized
    ]
    repositories.insert(0, normalized)
    config["opened_repositories"] = repositories
    save_config(config)
    return [Path(value) for value in repositories]


def _normalize_repository_path(path: str | Path) -> str:
    candidate = Path(path).expanduser()
    try:
        candidate = candidate.resolve()
    except OSError:
        pass
    return candidate.as_posix()
