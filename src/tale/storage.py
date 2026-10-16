from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import tomlkit
from tomlkit.items import Comment, InlineTable, Table
from tomlkit.toml_document import TOMLDocument


def update_last_run(path: Path, task_name: str, value: datetime) -> None:
    """Update one task's runtime metadata without replacing the whole file in place."""
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    table = document.get(task_name)
    if not isinstance(table, tomlkit.items.Table):
        raise TypeError(f"task [{task_name}] is not a TOML table")
    table["last_run"] = value
    _write_document(path, document)


def remove_tasks(path: Path, names: list[str]) -> None:
    """Remove complete task tables, deleting the file if no settings remain."""
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    for name in names:
        if not isinstance(document.get(name), (Table, InlineTable)):
            raise TypeError(f"task [{name}] is not a TOML table")

    remaining = tomlkit.document()
    for key, item in document.body:
        if key is not None and key.key in names:
            assert isinstance(item, (Table, InlineTable))
            # TOML attaches comments preceding a later table to the previous
            # table's body. Keep standalone comments rather than losing them.
            for comment in _standalone_comments(item):
                remaining.append(None, comment)
        else:
            remaining.append(key, item)
    if not remaining:
        path.unlink()
    else:
        _write_document(path, remaining)


def _standalone_comments(table: Table | InlineTable) -> list[Comment]:
    comments: list[Comment] = []
    for _, item in table.value.body:
        if isinstance(item, Comment):
            comments.append(item)
        elif isinstance(item, (Table, InlineTable)):
            comments.extend(_standalone_comments(item))
    return comments


def _write_document(path: Path, document: TOMLDocument) -> None:
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
