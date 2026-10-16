from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .cleanup import obsolete_reason
from .models import Task
from .scheduler import find_due, next_occurrence


@dataclass(frozen=True)
class TaskStatus:
    state: str
    reason: str
    next_run: datetime | None = None


def describe_task(task: Task, now: datetime) -> TaskStatus:
    """Explain a task using execution/cleanup rules without persisting metadata."""
    obsolete = obsolete_reason(task, now)
    if obsolete is not None:
        if task.cron is None and task.interval is None and task.last_run is not None:
            state = "completed"
        elif task.not_after is not None and (
            now > task.not_after or (task.not_after_exclusive and now == task.not_after)
        ):
            state = "expired"
        else:
            state = "exhausted"
        return TaskStatus(state, obsolete)

    due, errors = find_due([task], now, persist_initial=False)
    if errors:
        raise ValueError(errors[0])
    if due:
        item = due[0]
        next_run = item.latest_occurrence if task.collapse else item.occurrences[0]
        return TaskStatus(
            "due",
            f"{len(item.occurrences)} occurrence(s) pending; will run {item.run_count} time(s)",
            next_run,
        )

    upcoming = next_occurrence(task, now)
    if task.not_before is not None and now < task.not_before:
        reason = f"not_before is {task.not_before.isoformat()}"
        if task.cron is not None and task.last_run is None:
            reason += "; cron will initialize on its first invocation within the window"
        return TaskStatus("waiting", reason, upcoming)
    if task.cron is not None and task.last_run is None:
        return TaskStatus(
            "new",
            "cron will initialize on next invocation without replaying history",
            upcoming,
        )
    return TaskStatus("waiting", "next scheduled occurrence is in the future", upcoming)


def list_tasks(tasks: list[Task], now: datetime) -> int:
    """Print statuses and next execution candidates; never execute or update tasks."""
    if not tasks:
        print("No tasks found.")
        return 0
    failed = False
    for task in tasks:
        try:
            status = describe_task(task, now)
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            status = TaskStatus("error", str(exc))
            failed = True
        if task.cron is not None:
            schedule = f"cron {task.cron} (collapse={str(task.collapse).lower()})"
        elif task.interval is not None:
            schedule = (
                f"interval {task.interval} (collapse={str(task.collapse).lower()})"
            )
        else:
            schedule = "single execution"
        print(f"{task.name}: {status.state}")
        print(f"  schedule: {schedule}")
        print(f"  command: {task.cmd}")
        print(f"  last_run: {task.last_run.isoformat() if task.last_run else 'never'}")
        print(f"  next: {status.next_run.isoformat() if status.next_run else 'none'}")
        print(f"  reason: {status.reason}")
        print(f"  source: {task.source}")
    return 1 if failed else 0
