from __future__ import annotations

import argparse
from datetime import datetime

from tale.config import load_tasks
from tale.executor import execute
from tale.scheduler import find_due


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run due Tale tasks on demand.")
    parser.add_argument("task", nargs="*", help="task names to consider (default: all)")
    parser.add_argument(
        "-y", "--yes", action="store_true", help="run without prompting"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show due tasks without running them"
    )
    args = parser.parse_args(argv)

    tasks, config_errors = load_tasks()
    for error in config_errors:
        print(f"error: {error}")
    if args.task:
        wanted = set(args.task)
        tasks = [task for task in tasks if task.name in wanted]

    now = datetime.now().astimezone()
    due, schedule_errors = find_due(tasks, now, persist_initial=not args.dry_run)
    for error in schedule_errors:
        print(f"error: {error}")

    if not due:
        print("No tasks are due.")
        return 1 if config_errors or schedule_errors else 0

    for item in due:
        count = item.run_count
        missed = len(item.occurrences)
        print(
            f"{item.task.name}: {item.task.cmd} ({missed} missed, will run {count} time(s))"
        )
        if args.dry_run:
            continue
        if not args.yes:
            answer = input("Run this task? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Skipped.")
                continue
        results = execute(item)
        print(f"Finished {item.task.name}: {results}")

    return 1 if config_errors or schedule_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
