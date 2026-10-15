from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import tomlkit


def update_last_run(path: Path, task_name: str, value: datetime) -> None:
    """Update one task's runtime metadata without replacing the whole file in place."""
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    table = document.get(task_name)
    if not isinstance(table, tomlkit.items.Table):
        raise TypeError(f"task [{task_name}] is not a TOML table")
    table["last_run"] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            temporary.write(tomlkit.dumps(document))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
