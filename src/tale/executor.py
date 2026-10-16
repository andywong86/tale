from __future__ import annotations

import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import DueTask
from .storage import update_last_run


def execute(due: DueTask) -> list[int]:
    """Execute a due task and persist progress after each successful run."""
    due.task.directory.mkdir(parents=True, exist_ok=True)
    occurrences = (due.latest_occurrence,) if due.task.collapse else due.occurrences
    results: list[int] = []

    for occurrence in occurrences:
        started = datetime.now(tz=ZoneInfo("UTC"))
        stamp = started.strftime("%Y%m%dT%H%M%S%z")
        log_path = due.task.directory / f"tale_{due.task.name}_{stamp}.log"
        with log_path.open("w", encoding="utf-8") as log:
            log.write(
                f"task = {due.task.name}\ncommand = {due.task.cmd}\ndir = {due.task.directory}\n"
            )
            log.write(
                f"scheduled = {occurrence.isoformat()}\nstarted = {started.isoformat()}\n---\n"
            )
            # Flush metadata before the child writes directly to this file.
            log.flush()
            completed = subprocess.run(
                due.task.cmd,
                shell=True,
                cwd=due.task.directory,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                text=True,
            )
            finished = datetime.now(tz=ZoneInfo("UTC"))
            log.write(
                f"\n---\nfinished = {finished.isoformat()}\nexit_code = {completed.returncode}\n"
            )

        results.append(completed.returncode)
        if completed.returncode != 0:
            break
        update_last_run(due.task.source, due.task.name, occurrence)

    return results
