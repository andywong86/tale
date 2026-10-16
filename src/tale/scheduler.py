from __future__ import annotations

from datetime import UTC, datetime

from croniter import croniter

from .models import DueTask, Task
from .storage import update_last_run

MAX_CATCH_UP = 10_000


def find_due(
    tasks: list[Task], now: datetime, *, persist_initial: bool = True
) -> tuple[list[DueTask], list[str]]:
    due: list[DueTask] = []
    errors: list[str] = []

    for task in tasks:
        try:
            if task.interval is not None:
                last = task.last_run
                if last is None:
                    due.append(DueTask(task, (now,)))
                else:
                    # Compare absolute elapsed time, including across DST changes.
                    if now.utcoffset() is not None and last.utcoffset() is not None:
                        elapsed = now.astimezone(UTC) - last.astimezone(UTC)
                    else:
                        elapsed = now - last
                    if elapsed >= task.interval:
                        due.append(DueTask(task, (now,)))
                continue

            if task.cron is None:
                if task.last_run is None:
                    due.append(DueTask(task, (now,)))
                continue

            if not croniter.is_valid(task.cron):
                raise ValueError(f"invalid cron expression: {task.cron!r}")
            last = task.last_run
            if last is None:
                # Do not unexpectedly execute historical work on first discovery.
                if persist_initial:
                    update_last_run(task.source, task.name, now)
                continue

            occurrences: list[datetime] = []
            iterator = croniter(task.cron, last)
            while len(occurrences) < MAX_CATCH_UP:
                occurrence = iterator.get_next(datetime)
                if occurrence > now:
                    break
                occurrences.append(occurrence)

            if len(occurrences) == MAX_CATCH_UP:
                raise ValueError("too many missed occurrences")
            if occurrences:
                due.append(DueTask(task, tuple(occurrences)))
        except (TypeError, ValueError, OSError) as exc:
            errors.append(f"{task.source}: [{task.name}]: {exc}")

    return due, errors
