from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import tomlkit

from tale.cleanup import cleanup, obsolete_reason
from tale.config import load_tasks
from tale.models import Task
from tale.run import main
from tale.storage import remove_tasks

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def task(
    tmp_path: Path,
    kind: str = "single",
    *,
    last_run: datetime | None = None,
    not_before: datetime | None = None,
    not_after: datetime | None = None,
    not_after_exclusive: bool = False,
    collapse: bool = True,
    interval: timedelta | None = None,
) -> Task:
    return Task(
        "job",
        "true",
        "0 * * * *" if kind == "cron" else None,
        tmp_path,
        collapse,
        tmp_path / "tasks.toml",
        last_run,
        interval=interval or (timedelta(hours=1) if kind == "interval" else None),
        not_before=not_before,
        not_after=not_after,
        not_after_exclusive=not_after_exclusive,
    )


@pytest.mark.parametrize("completed", [False, True])
def test_single_execution_cleanup(tmp_path: Path, completed: bool) -> None:
    item = task(tmp_path, last_run=NOW if completed else None)
    assert bool(obsolete_reason(item, NOW)) is completed


@pytest.mark.parametrize("kind", ["single", "cron", "interval"])
@pytest.mark.parametrize("exclusive", [False, True])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_expiration_boundary(
    tmp_path: Path, kind: str, exclusive: bool, offset: int
) -> None:
    item = task(
        tmp_path,
        kind,
        not_after=NOW + timedelta(seconds=offset),
        not_after_exclusive=exclusive,
        last_run=NOW - timedelta(hours=2) if kind != "single" else None,
    )
    assert bool(obsolete_reason(item, NOW)) is (
        offset < 0 or (exclusive and offset == 0)
    )


@pytest.mark.parametrize("kind", ["single", "cron", "interval"])
def test_no_deadline_and_future_lower_bound_are_not_obsolete(
    tmp_path: Path, kind: str
) -> None:
    item = task(tmp_path, kind, not_before=NOW + timedelta(days=1))
    assert obsolete_reason(item, NOW) is None


@pytest.mark.parametrize("kind", ["cron", "interval"])
@pytest.mark.parametrize("exclusive", [False, True])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_next_boundary_against_deadline(
    tmp_path: Path, kind: str, exclusive: bool, offset: int
) -> None:
    # Next occurrence at 1 PM, after a 12 PM success.
    item = task(
        tmp_path,
        kind,
        last_run=NOW,
        not_after=NOW + timedelta(hours=1, seconds=offset),
        not_after_exclusive=exclusive,
    )
    assert bool(obsolete_reason(item, NOW)) is (
        offset < 0 or (offset == 0 and exclusive)
    )


@pytest.mark.parametrize("kind", ["cron", "interval"])
@pytest.mark.parametrize("collapse", [False, True])
def test_pending_catch_up_is_retained(
    tmp_path: Path, kind: str, collapse: bool
) -> None:
    item = task(
        tmp_path,
        kind,
        last_run=NOW - timedelta(days=1000),
        not_after=NOW + timedelta(minutes=30),
        collapse=collapse,
    )
    assert obsolete_reason(item, NOW) is None


@pytest.mark.parametrize("kind", ["cron", "interval"])
@pytest.mark.parametrize("after_last_boundary", [False, True])
def test_lower_bound_filters_obsolete_history_without_resetting_phase(
    tmp_path: Path, kind: str, after_last_boundary: bool
) -> None:
    item = task(
        tmp_path,
        kind,
        last_run=NOW - timedelta(days=1000),
        not_before=NOW + timedelta(minutes=60 if not after_last_boundary else 61),
        not_after=NOW + timedelta(minutes=90),
    )
    assert bool(obsolete_reason(item, NOW)) is after_last_boundary


def test_never_run_interval_with_lower_bound_keeps_initial_occurrence(
    tmp_path: Path,
) -> None:
    item = task(
        tmp_path,
        "interval",
        not_before=NOW + timedelta(minutes=10),
        not_after=NOW + timedelta(minutes=20),
    )
    assert obsolete_reason(item, NOW) is None


def test_never_run_interval_without_lower_bound_is_due_immediately(
    tmp_path: Path,
) -> None:
    assert obsolete_reason(task(tmp_path, "interval", not_after=NOW), NOW) is None


@pytest.mark.parametrize("future_lower_bound", [False, True])
def test_never_run_cron_accounts_for_first_discovery_initialization(
    tmp_path: Path, future_lower_bound: bool
) -> None:
    item = task(
        tmp_path,
        "cron",
        not_before=NOW + timedelta(hours=1) if future_lower_bound else None,
        not_after=NOW + timedelta(hours=1, minutes=30)
        if future_lower_bound
        else NOW + timedelta(minutes=30),
    )
    assert obsolete_reason(item, NOW) is not None


def test_interval_cleanup_uses_absolute_elapsed_time(tmp_path: Path) -> None:
    zone = ZoneInfo("America/New_York")
    last = datetime(2026, 3, 8, 0, tzinfo=zone)
    item = task(
        tmp_path,
        "interval",
        interval=timedelta(hours=6),
        last_run=last,
        not_after=datetime(2026, 3, 8, 6, 30, tzinfo=zone).astimezone(UTC),
    )
    assert obsolete_reason(item, last) is not None
    item = replace(item, not_after=datetime(2026, 3, 8, 7, tzinfo=zone).astimezone(UTC))
    assert obsolete_reason(item, last) is None


def write_mixed_file(tmp_path: Path) -> Path:
    source = tmp_path / "tasks.toml"
    source.write_text(
        '# keep this comment\n[done]\ncmd = "true"\nlast_run = 2026-01-01T00:00:00Z\n'
        '[done.env]\nSECRET = "private-value"\n'
        '\n# keep remaining task\n[keep]\ncmd = "true"\n'
        '[keep.env]\nLEVEL = "debug"\n'
    )
    return source


def invoke(tmp_path: Path, argv: list[str]) -> int:
    with (
        patch("tale.run.load_tasks", side_effect=lambda: load_tasks(tmp_path)),
        patch("tale.run.datetime") as clock,
    ):
        clock.now.return_value = NOW
        return main(argv)


def test_cleanup_removes_nested_env_and_preserves_other_tasks_and_comments(
    tmp_path: Path,
) -> None:
    source = write_mixed_file(tmp_path)
    assert invoke(tmp_path, ["--cleanup", "--yes"]) == 0
    tasks, errors = load_tasks(tmp_path)
    assert errors == []
    assert [item.name for item in tasks] == ["keep"]
    assert tasks[0].env == {"LEVEL": "debug"}
    text = source.read_text()
    assert "keep this comment" in text
    assert "keep remaining task" in text
    assert "private-value" not in text
    assert "[done" not in text
    assert tasks[0].last_run is None


def test_cleanup_deletes_expired_and_exhausted_schedules_but_keeps_pending_work(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tasks.toml"
    end = NOW + timedelta(minutes=30)
    source.write_text(
        tomlkit.dumps(
            {
                "expired": {
                    "cmd": "true",
                    "not_after": NOW - timedelta(seconds=1),
                    "env": {"KEY": "value"},
                },
                "cron_done": {
                    "cmd": "true",
                    "cron": "0 * * * *",
                    "last_run": NOW,
                    "not_after": end,
                },
                "interval_done": {
                    "cmd": "true",
                    "interval": "1h",
                    "last_run": NOW,
                    "not_after": end,
                },
                "pending": {
                    "cmd": "true",
                    "cron": "0 * * * *",
                    "last_run": NOW - timedelta(hours=1),
                    "not_after": end,
                },
            }
        )
    )
    assert invoke(tmp_path, ["--cleanup", "--yes"]) == 0
    tasks, errors = load_tasks(tmp_path)
    assert errors == []
    assert [item.name for item in tasks] == ["pending"]
    assert tasks[0].last_run == NOW - timedelta(hours=1)
    assert "KEY" not in source.read_text()


def test_cleanup_deletes_empty_file_but_not_other_files(tmp_path: Path) -> None:
    source = write_mixed_file(tmp_path)
    (tmp_path / "finished.toml").write_text(
        '# comments alone do not keep the file\n[finished]\ncmd = "true"\n'
        'last_run = 2026-01-01T00:00:00Z\n[finished.env]\nKEY = "value"\n'
    )
    assert invoke(tmp_path, ["--cleanup", "--yes"]) == 0
    assert not (tmp_path / "finished.toml").exists()
    assert source.exists()


@pytest.mark.parametrize(
    "argv", [["--cleanup", "--dry-run"], ["--cleanup", "--dry-run", "--yes"]]
)
def test_cleanup_dry_run_never_writes_or_executes(
    tmp_path: Path, argv: list[str]
) -> None:
    source = write_mixed_file(tmp_path)
    original = source.read_bytes()
    with (
        patch("builtins.input") as prompt,
        patch("tale.run.execute") as run,
        patch("tale.run.find_due") as schedule,
    ):
        assert invoke(tmp_path, argv) == 0
    prompt.assert_not_called()
    run.assert_not_called()
    schedule.assert_not_called()
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "answer, removed", [("y", True), ("YES", True), ("n", False), ("", False)]
)
def test_cleanup_prompts_before_deleting(
    tmp_path: Path, answer: str, removed: bool
) -> None:
    source = write_mixed_file(tmp_path)
    with patch("builtins.input", return_value=answer) as prompt:
        assert invoke(tmp_path, ["--cleanup"]) == 0
    prompt.assert_called_once()
    assert ("[done]" not in source.read_text()) is removed


def test_cleanup_task_name_filter(tmp_path: Path) -> None:
    source = write_mixed_file(tmp_path)
    original = source.read_bytes()
    assert invoke(tmp_path, ["--cleanup", "--yes", "keep"]) == 0
    assert source.read_bytes() == original
    assert invoke(tmp_path, ["--cleanup", "--yes", "done"]) == 0
    assert "[done]" not in source.read_text()


def test_invalid_configuration_is_retained_and_exit_is_nonzero(tmp_path: Path) -> None:
    source = write_mixed_file(tmp_path)
    with source.open("a") as stream:
        stream.write('\n[invalid]\nenv = { KEY = "value" }\n')
    assert invoke(tmp_path, ["--cleanup", "--yes"]) == 1
    assert "[invalid]" in source.read_text()
    assert "[done]" not in source.read_text()


def test_invalid_cron_is_not_deleted_even_if_expired(tmp_path: Path) -> None:
    source = tmp_path / "tasks.toml"
    source.write_text(
        '[bad]\ncmd = "true"\ncron = "not cron"\nnot_after = 2020-01-01T00:00:00Z\n'
    )
    original = source.read_bytes()
    assert invoke(tmp_path, ["--cleanup", "--yes"]) == 1
    assert source.read_bytes() == original


def test_cron_with_no_possible_date_before_deadline_is_obsolete(tmp_path: Path) -> None:
    item = replace(
        task(tmp_path, "cron", last_run=NOW, not_after=NOW + timedelta(days=60)),
        cron="0 0 31 2 *",
    )
    assert obsolete_reason(item, NOW) is not None


def test_leap_day_cron_with_future_occurrence_is_retained(tmp_path: Path) -> None:
    item = replace(
        task(tmp_path, "cron", last_run=NOW, not_after=NOW.replace(year=2120)),
        cron="0 0 29 2 *",
    )
    assert obsolete_reason(item, NOW) is None


def test_schedule_error_is_conservative(tmp_path: Path) -> None:
    item = task(tmp_path, "cron", last_run=NOW, not_after=NOW + timedelta(days=1))
    with patch("tale.scheduler.croniter") as iterator:
        iterator.is_valid.return_value = True
        iterator.return_value.get_next.side_effect = ValueError(
            "cannot determine next date"
        )
        assert cleanup([item], NOW, yes=True) == 1


def test_cleanup_write_failure_is_reported_without_changes(tmp_path: Path) -> None:
    source = write_mixed_file(tmp_path)
    original = source.read_bytes()
    with patch("tale.storage.os.replace", side_effect=OSError("write failed")):
        assert invoke(tmp_path, ["--cleanup", "--yes"]) == 1
    assert source.read_bytes() == original
    assert list(tmp_path.glob(".tasks.toml.*")) == []


def test_remove_tasks_preserves_unrecognized_top_level_settings(tmp_path: Path) -> None:
    source = tmp_path / "tasks.toml"
    source.write_text('unknown = "preserve me"\n[job]\ncmd = "true"\n')
    remove_tasks(source, ["job"])
    assert source.exists()
    assert source.read_text().strip() == 'unknown = "preserve me"'


def test_remove_tasks_rejects_missing_task_without_changes(tmp_path: Path) -> None:
    source = write_mixed_file(tmp_path)
    original = source.read_bytes()
    with pytest.raises(TypeError):
        remove_tasks(source, ["done", "missing"])
    assert source.read_bytes() == original


def test_remove_inline_task_and_delete_empty_file(tmp_path: Path) -> None:
    source = tmp_path / "tasks.toml"
    source.write_text('job = { cmd = "true", env = { KEY = "value" } }\n')
    remove_tasks(source, ["job"])
    assert not source.exists()
