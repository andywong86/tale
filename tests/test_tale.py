from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from tale.config import DEFAULT_CRON, load_tasks
from tale.executor import execute
from tale.models import DueTask, Task
from tale.scheduler import find_due
from tale.storage import update_last_run


def task_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "tasks.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_tasks_applies_defaults_and_reads_last_run(tmp_path: Path) -> None:
    path = task_file(
        tmp_path,
        """
[example]
cmd = "echo hello"
last_run = 2026-01-01T00:00:00Z
""",
    )

    tasks, errors = load_tasks(tmp_path)

    assert errors == []
    assert len(tasks) == 1
    assert tasks[0].cron == DEFAULT_CRON
    assert tasks[0].directory == Path.home()
    assert tasks[0].once is False
    assert tasks[0].last_run == datetime(2026, 1, 1, tzinfo=UTC)
    assert tasks[0].source == path


def test_load_tasks_reports_invalid_task_without_discarding_valid_task(
    tmp_path: Path,
) -> None:
    task_file(
        tmp_path,
        """
[valid]
cmd = "echo hello"

[invalid]
cron = "* * * * *"
""",
    )

    tasks, errors = load_tasks(tmp_path)

    assert [task.name for task in tasks] == ["valid"]
    assert len(errors) == 1
    assert "cmd is required" in errors[0]


def test_load_tasks_creates_missing_config_directory(tmp_path: Path) -> None:
    config = tmp_path / "missing"

    tasks, errors = load_tasks(config)

    assert config.is_dir()
    assert tasks == []
    assert errors == []


def test_update_last_run_preserves_comments_and_updates_only_task(
    tmp_path: Path,
) -> None:
    path = task_file(
        tmp_path,
        """# Keep this comment.
[first]
cmd = "echo first"

[second]
cmd = "echo second"
""",
    )
    value = datetime(2026, 2, 3, 4, 5, tzinfo=UTC)

    update_last_run(path, "first", value)
    text = path.read_text(encoding="utf-8")
    tasks, errors = load_tasks(tmp_path)

    assert "# Keep this comment." in text
    assert tasks[0].last_run == value
    assert tasks[1].last_run is None
    assert errors == []


def test_find_due_initializes_task_without_replaying_history(tmp_path: Path) -> None:
    path = task_file(tmp_path, '[job]\ncmd = "echo hello"\ncron = "* * * * *"\n')
    tasks, _ = load_tasks(tmp_path)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    due, errors = find_due(tasks, now)

    refreshed, _ = load_tasks(tmp_path)
    assert due == []
    assert errors == []
    assert refreshed[0].last_run == now
    assert path.exists()


def test_find_due_returns_all_missed_occurrences(tmp_path: Path) -> None:
    path = task_file(
        tmp_path,
        """[job]
cmd = "echo hello"
cron = "* * * * *"
last_run = 2026-01-01T11:57:00Z
""",
    )
    tasks, _ = load_tasks(tmp_path)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    due, errors = find_due(tasks, now)

    assert errors == []
    assert len(due) == 1
    assert len(due[0].occurrences) == 3
    assert due[0].run_count == 3
    assert due[0].latest_occurrence == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert path.exists()


def test_due_task_once_collapses_missed_occurrences(tmp_path: Path) -> None:
    task = Task(
        "job", "echo hello", "* * * * *", tmp_path, True, tmp_path / "x.toml", None
    )
    occurrences = tuple(
        datetime(2026, 1, 1, minute=minute, tzinfo=UTC) for minute in (1, 2, 3)
    )

    due = DueTask(task, occurrences)

    assert due.run_count == 1
    assert due.latest_occurrence == occurrences[-1]


def test_execute_writes_output_stats_and_last_run(tmp_path: Path) -> None:
    source = task_file(tmp_path, '[job]\ncmd = "echo hello"\n')
    task = Task(
        "job",
        f"{sys.executable} -c \"print('hello')\"",
        "* * * * *",
        tmp_path,
        True,
        source,
        None,
    )
    occurrence = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    result = execute(DueTask(task, (occurrence,)))

    logs = list(tmp_path.glob("tale_job_*.log"))
    assert result == [0]
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert "hello" in text
    assert "---" in text
    assert "exit_code = 0" in text
    tasks, _ = load_tasks(tmp_path)
    assert tasks[0].last_run == occurrence


def test_execute_does_not_advance_last_run_after_failure(tmp_path: Path) -> None:
    source = task_file(tmp_path, '[job]\ncmd = "false"\n')
    task = Task("job", "false", "* * * * *", tmp_path, False, source, None)
    occurrence = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    result = execute(DueTask(task, (occurrence,)))

    assert result == [1]
    tasks, _ = load_tasks(tmp_path)
    assert tasks[0].last_run is None
