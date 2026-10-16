from __future__ import annotations

from datetime import datetime
from pathlib import Path

from croniter import croniter

from .models import Task
from .scheduler import next_occurrence
from .storage import remove_tasks


def obsolete_reason(task: Task, now: datetime) -> str | None:
    """Return why a task cannot execute again, without modifying its state."""
    if task.cron is not None and not croniter.is_valid(task.cron):
        raise ValueError(f"invalid cron expression: {task.cron!r}")
    if task.cron is None and task.interval is None and task.last_run is not None:
        return "single-execution task completed"
    end = task.not_after
    if end is None:
        return None
    if now > end or (task.not_after_exclusive and now == end):
        return "execution window expired"
    if task.cron is None and task.interval is None:
        return None

    if next_occurrence(task, now) is None:
        return "no remaining scheduled occurrences within the execution window"
    return None


def cleanup(
    tasks: list[Task], now: datetime, *, dry_run: bool = False, yes: bool = False
) -> int:
    """Confirm and delete obsolete task tables, grouping writes by source file."""
    removals: dict[Path, list[str]] = {}
    failed = False
    found = False
    for task in tasks:
        try:
            reason = obsolete_reason(task, now)
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            print(f"error: {task.source}: [{task.name}]: {exc}")
            failed = True
            continue
        if reason is None:
            continue
        found = True
        print(f"{task.source}: [{task.name}]: {reason}")
        if dry_run:
            continue
        if not yes:
            answer = input("Delete this task? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Skipped.")
                continue
        removals.setdefault(task.source, []).append(task.name)

    for path, names in removals.items():
        try:
            remove_tasks(path, names)
            print(f"Removed {', '.join(names)} from {path}.")
            if not path.exists():
                print(f"Deleted empty file {path}.")
        except (ValueError, TypeError, OSError) as exc:
            print(f"error: {path}: {exc}")
            failed = True
    if not found:
        print("No obsolete tasks to clean up.")
    return 1 if failed else 0
