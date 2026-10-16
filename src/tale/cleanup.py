from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from croniter import CroniterBadDateError, croniter

from .models import Task
from .storage import remove_tasks
from .window import within_window


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

    if task.interval is not None:
        base = task.last_run if task.last_run is not None else task.not_before
        if base is None:
            # Never run and no lower bound: first execution can happen now.
            return None
        if base.utcoffset() is not None:
            base = base.astimezone(UTC)
        first = 1 if task.last_run is not None else 0
        if task.not_before is not None:
            first = max(first, (task.not_before - base) // task.interval)
            if base + task.interval * first < task.not_before:
                first += 1
        candidate = base + task.interval * first
    else:
        assert task.cron is not None
        base = task.last_run
        if base is None:
            # Cron first discovery initializes at the first possible invocation.
            base = max(now, task.not_before) if task.not_before is not None else now
        elif task.not_before is not None and base < task.not_before:
            base = task.not_before - timedelta(microseconds=1)
        try:
            candidate = croniter(
                task.cron,
                base,
                max_years_between_matches=max(1, end.year - base.year + 1),
            ).get_next(datetime)
        except CroniterBadDateError:
            return "no remaining scheduled occurrences within the execution window"

    if not within_window(task, candidate):
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
