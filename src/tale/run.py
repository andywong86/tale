from __future__ import annotations

import argparse
import sys
from datetime import datetime

from tale.cleanup import cleanup
from tale.config import config_directory, load_tasks
from tale.executor import execute
from tale.listing import list_tasks
from tale.locking import LockError, invocation_lock
from tale.scheduler import find_due
from tale.summary import ExecutionSummary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run due Tale tasks on demand.")
    parser.add_argument("task", nargs="*", help="task names to consider (default: all)")
    parser.add_argument(
        "-y", "--yes", action="store_true", help="run without prompting"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview execution or cleanup without changes",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--list",
        dest="list_tasks",
        action="store_true",
        help="list task statuses without changes",
    )
    mode.add_argument(
        "--cleanup",
        action="store_true",
        help="delete obsolete tasks instead of running tasks",
    )
    args = parser.parse_args(argv)

    try:
        with invocation_lock(config_directory()):
            return _run(args)
    except LockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    tasks, config_errors = load_tasks()
    for error in config_errors:
        print(f"error: {error}")
    if args.task:
        wanted = set(args.task)
        tasks = [task for task in tasks if task.name in wanted]

    now = datetime.now().astimezone()
    if args.list_tasks:
        status = list_tasks(tasks, now)
        return 1 if config_errors or status else 0
    if args.cleanup:
        status = cleanup(tasks, now, dry_run=args.dry_run, yes=args.yes)
        return 1 if config_errors or status else 0

    due, schedule_errors = find_due(tasks, now, persist_initial=not args.dry_run)
    for error in schedule_errors:
        print(f"error: {error}")

    summary = ExecutionSummary(
        not_due=max(0, len(tasks) - len(due) - len(schedule_errors)),
        errors=len(config_errors) + len(schedule_errors),
        executions_not_run=sum(item.run_count for item in due),
    )
    if not due:
        print("No tasks are due.")
        summary.print()
        return 1 if summary.errors else 0

    for index, item in enumerate(due):
        if index and not args.yes and not args.dry_run:
            print()
        count = item.run_count
        if item.task.cron is not None or item.task.interval is not None:
            detail = f"{len(item.occurrences)} missed, will run {count} time(s)"
        else:
            detail = f"due, will run {count} time(s)"
        print(f"{item.task.name}: {item.task.cmd} ({detail})")
        if args.dry_run:
            summary.deferred += 1
            continue
        if not args.yes:
            answer = input("Run this task? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Skipped.")
                summary.skipped += 1
                continue
        results = execute(item)
        summary.record_results(count, results)
        if results:
            print(f"Finished {item.task.name}: {results}")
        else:
            print(f"Skipped {item.task.name}: outside its execution window.")

    summary.print()
    return 1 if summary.errors or summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
