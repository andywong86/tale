from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Task

DEFAULT_CRON = "0 0 * * *"


class ConfigError(ValueError):
    pass


def config_directory() -> Path:
    return Path.home() / ".config" / "tale"


def load_tasks(directory: Path | None = None) -> tuple[list[Task], list[str]]:
    """Load top-level task tables from every TOML file in the config directory."""
    directory = directory or config_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [], [f"cannot create config directory {directory}: {exc}"]

    tasks: list[Task] = []
    errors: list[str] = []

    for path in sorted(directory.glob("*.toml")):
        try:
            with path.open("rb") as stream:
                document = tomllib.load(stream)
            for name, raw in document.items():
                try:
                    tasks.append(_task_from_table(name, raw, path))
                except ConfigError as exc:
                    errors.append(f"{path}: [{name}]: {exc}")
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{path}: {exc}")

    return tasks, errors


def _task_from_table(name: str, raw: Any, source: Path) -> Task:
    if "." in name:
        raise ConfigError("task names must not contain dots")
    if not isinstance(raw, dict):
        raise ConfigError("task must be a TOML table")

    cmd = raw.get("cmd")
    if not isinstance(cmd, str) or not cmd.strip():
        raise ConfigError("cmd is required")

    cron = raw.get("cron", DEFAULT_CRON)
    if not isinstance(cron, str) or not cron.strip():
        raise ConfigError("cron must be a non-empty string")

    raw_dir = raw.get("dir", "")
    if not isinstance(raw_dir, str):
        raise ConfigError("dir must be a string")
    directory = Path(raw_dir).expanduser() if raw_dir else Path.home()

    once = raw.get("once", False)
    if not isinstance(once, bool):
        raise ConfigError("once must be true or false")

    last_run = raw.get("last_run")
    if isinstance(last_run, str):
        try:
            last_run = datetime.fromisoformat(last_run)
        except ValueError as exc:
            raise ConfigError("last_run must be an ISO datetime") from exc
    if last_run is not None and not isinstance(last_run, datetime):
        raise ConfigError("last_run must be an ISO datetime")

    return Task(name, cmd, cron, directory, once, source, last_run)
