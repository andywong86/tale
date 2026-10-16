from __future__ import annotations

from datetime import UTC, datetime, timedelta

from croniter import CroniterBadDateError, croniter

from .models import DueTask, Task
from .storage import update_last_run
from .window import within_window

MAX_CATCH_UP = 10_000


def next_occurrence(task: Task, now: datetime) -> datetime | None:
    """Find the first eligible occurrence, including pending work, without writes."""
    if task.interval is not None:
        base = task.last_run if task.last_run is not None else task.not_before
        if base is None:
            candidate = now
        else:
            if base.utcoffset() is not None:
                base = base.astimezone(UTC)
            first = 1 if task.last_run is not None else 0
            if task.not_before is not None:
                first = max(first, (task.not_before - base) // task.interval)
                if base + task.interval * first < task.not_before:
                    first += 1
            candidate = base + task.interval * first
    elif task.cron is not None:
        if not croniter.is_valid(task.cron):
            raise ValueError(f"invalid cron expression: {task.cron!r}")
        base = task.last_run
        if base is None:
            # First discovery initializes at the first possible invocation.
            base = max(now, task.not_before) if task.not_before is not None else now
        elif task.not_before is not None and base < task.not_before:
            base = task.not_before - timedelta(microseconds=1)
        end = task.not_after
        try:
            candidate = croniter(
                task.cron,
                base,
                max_years_between_matches=(
                    max(1, end.year - base.year + 1) if end is not None else 50
                ),
            ).get_next(datetime)
        except CroniterBadDateError:
            if end is None:
                raise
            return None
    else:
        if task.last_run is not None:
            return None
        candidate = max(now, task.not_before) if task.not_before is not None else now
    return candidate if within_window(task, candidate) else None


def find_due(
    tasks: list[Task], now: datetime, *, persist_initial: bool = True
) -> tuple[list[DueTask], list[str]]:
    due: list[DueTask] = []
    errors: list[str] = []

    for task in tasks:
        try:
            if not within_window(task, now):
                continue

            if task.interval is not None:
                last = task.last_run
                base = last if last is not None else task.not_before
                if base is None:
                    due.append(DueTask(task, (now,)))
                    continue

                # Build boundaries in absolute time, including across DST changes.
                if now.utcoffset() is not None and base.utcoffset() is not None:
                    base = base.astimezone(UTC)
                    elapsed = now.astimezone(UTC) - base
                else:
                    elapsed = now - base
                first = 1 if last is not None else 0
                if task.not_before is not None:
                    offset = task.not_before - base
                    first = max(first, offset // task.interval)
                    if base + task.interval * first < task.not_before:
                        first += 1
                final = elapsed // task.interval
                count = final - first + 1
                if count >= MAX_CATCH_UP:
                    raise ValueError("too many missed occurrences")
                if count > 0:
                    interval_occurrences = tuple(
                        base + task.interval * index
                        for index in range(first, final + 1)
                    )
                    due.append(DueTask(task, interval_occurrences))
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
            if task.not_before is not None and last < task.not_before:
                # Include a cron boundary exactly at the inclusive lower bound.
                last = task.not_before - timedelta(microseconds=1)
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
