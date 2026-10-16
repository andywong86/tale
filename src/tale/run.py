from __future__ import annotations

import argparse
import sys
from datetime import datetime

from tale.cleanup import cleanup
from tale.config import config_directory, load_tasks
from tale.executor import execute
from tale.locking import LockError, invocation_lock
from tale.scheduler import find_due


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
    parser.add_argument(
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
    if args.cleanup:
        status = cleanup(tasks, now, dry_run=args.dry_run, yes=args.yes)
        return 1 if config_errors or status else 0

    due, schedule_errors = find_due(tasks, now, persist_initial=not args.dry_run)
    for error in schedule_errors:
        print(f"error: {error}")

    if not due:
        print("No tasks are due.")
        return 1 if config_errors or schedule_errors else 0

    execution_failed = False
    for item in due:
        count = item.run_count
        if item.task.cron is not None or item.task.interval is not None:
            detail = f"{len(item.occurrences)} missed, will run {count} time(s)"
        else:
            detail = f"due, will run {count} time(s)"
        print(f"{item.task.name}: {item.task.cmd} ({detail})")
        if args.dry_run:
            continue
        if not args.yes:
            answer = input("Run this task? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Skipped.")
                continue
        results = execute(item)
        if any(code != 0 for code in results):
            execution_failed = True
        if results:
            print(f"Finished {item.task.name}: {results}")
        else:
            print(f"Skipped {item.task.name}: outside its execution window.")

    return 1 if config_errors or schedule_errors or execution_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
