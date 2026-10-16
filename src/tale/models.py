from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class Task:
    name: str
    cmd: str
    cron: str | None
    directory: Path
    collapse: bool
    source: Path
    last_run: datetime | None
    interval: timedelta | None = None


@dataclass(frozen=True)
class DueTask:
    task: Task
    occurrences: tuple[datetime, ...]

    @property
    def run_count(self) -> int:
        """Number of invocations required for this task this time."""
        return 1 if self.task.collapse else len(self.occurrences)

    @property
    def latest_occurrence(self) -> datetime:
        return self.occurrences[-1]
