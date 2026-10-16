from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import tomlkit

from tale import config
from tale.listing import describe_task, list_tasks
from tale.models import Task
from tale.run import main
from tale.scheduler import MAX_CATCH_UP

NOW = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
BOUNDARY = NOW.replace(minute=0)


def task(tmp_path: Path, kind: str = "single") -> Task:
    return Task(
        "job",
        "true",
        "0 * * * *" if kind == "cron" else None,
        tmp_path,
        True,
        tmp_path / "tasks.toml",
        None,
        interval=timedelta(hours=1) if kind == "interval" else None,
    )


@pytest.mark.parametrize("kind", ["single", "interval"])
def test_new_immediately_due_tasks(tmp_path: Path, kind: str) -> None:
    status = describe_task(task(tmp_path, kind), NOW)
    assert status.state == "due"
    assert status.next_run == NOW
    assert "will run 1" in status.reason


def test_completed_single_task(tmp_path: Path) -> None:
    status = describe_task(replace(task(tmp_path), last_run=NOW), NOW)
    assert status.state == "completed"
    assert status.next_run is None


def test_new_cron_explains_initialization_without_writing(tmp_path: Path) -> None:
    item = task(tmp_path, "cron")
    status = describe_task(item, NOW)
    assert status.state == "new"
    assert "initialize" in status.reason
    assert status.next_run == BOUNDARY + timedelta(hours=1)
    assert not item.source.exists()


@pytest.mark.parametrize("kind", ["cron", "interval"])
@pytest.mark.parametrize("collapse", [True, False])
def test_due_status_reflects_catch_up_and_selected_next_execution(
    tmp_path: Path, kind: str, collapse: bool
) -> None:
    item = replace(
        task(tmp_path, kind), last_run=BOUNDARY - timedelta(hours=2), collapse=collapse
    )
    status = describe_task(item, NOW)
    assert status.state == "due"
    assert "2 occurrence(s) pending" in status.reason
    assert f"will run {1 if collapse else 2}" in status.reason
    assert status.next_run == (BOUNDARY if collapse else BOUNDARY - timedelta(hours=1))


@pytest.mark.parametrize("kind", ["cron", "interval"])
def test_waiting_for_next_schedule(tmp_path: Path, kind: str) -> None:
    item = replace(task(tmp_path, kind), last_run=BOUNDARY)
    status = describe_task(item, NOW)
    assert status.state == "waiting"
    assert status.next_run == BOUNDARY + timedelta(hours=1)


@pytest.mark.parametrize("kind", ["single", "cron", "interval"])
def test_future_not_before_explained(tmp_path: Path, kind: str) -> None:
    lower = BOUNDARY + timedelta(hours=1)
    item = replace(task(tmp_path, kind), not_before=lower)
    status = describe_task(item, NOW)
    assert status.state == "waiting"
    assert "not_before" in status.reason
    assert status.next_run == (lower + timedelta(hours=1) if kind == "cron" else lower)
    if kind == "cron":
        assert "initialize" in status.reason


@pytest.mark.parametrize("kind", ["single", "cron", "interval"])
def test_expired_tasks_have_no_next_execution(tmp_path: Path, kind: str) -> None:
    item = replace(task(tmp_path, kind), not_after=NOW - timedelta(seconds=1))
    status = describe_task(item, NOW)
    assert status.state == "expired"
    assert status.next_run is None


@pytest.mark.parametrize("kind", ["cron", "interval"])
def test_exhausted_schedules_have_no_next_execution(tmp_path: Path, kind: str) -> None:
    item = replace(
        task(tmp_path, kind), last_run=BOUNDARY, not_after=NOW + timedelta(minutes=10)
    )
    status = describe_task(item, NOW)
    assert status.state == "exhausted"
    assert "no remaining" in status.reason
    assert status.next_run is None


def test_never_run_interval_uses_lower_bound_anchor(tmp_path: Path) -> None:
    item = replace(task(tmp_path, "interval"), not_before=BOUNDARY)
    status = describe_task(item, NOW)
    assert status.state == "due"
    assert status.next_run == BOUNDARY


@pytest.mark.parametrize("kind", ["cron", "interval"])
def test_listing_filters_occurrences_before_not_before(
    tmp_path: Path, kind: str
) -> None:
    item = replace(
        task(tmp_path, kind), last_run=BOUNDARY - timedelta(days=1), not_before=BOUNDARY
    )
    status = describe_task(item, NOW)
    assert status.state == "due"
    assert "1 occurrence(s)" in status.reason
    assert status.next_run == BOUNDARY


def test_schedule_errors_are_reported_without_hiding_other_tasks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = replace(task(tmp_path, "cron"), name="invalid", cron="bad expression")
    assert list_tasks([invalid, task(tmp_path)], NOW) == 1
    output = capsys.readouterr().out
    assert "invalid: error" in output
    assert "invalid cron expression" in output
    assert "job: due" in output


@pytest.mark.parametrize("kind", ["cron", "interval"])
def test_catch_up_limit_is_reported_as_error(
    tmp_path: Path, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    item = replace(
        task(tmp_path, kind), last_run=BOUNDARY - timedelta(hours=MAX_CATCH_UP)
    )
    assert list_tasks([item], NOW) == 1
    assert "too many missed occurrences" in capsys.readouterr().out


def test_impossible_unbounded_cron_is_an_error_not_silently_exhausted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    item = replace(task(tmp_path, "cron"), cron="0 0 31 2 *")
    assert list_tasks([item], NOW) == 1
    assert "job: error" in capsys.readouterr().out


def invoke(argv: list[str]) -> int:
    with patch("tale.run.datetime") as clock:
        clock.now.return_value = NOW
        return main(argv)


def write_tasks() -> tuple[Path, bytes]:
    directory = config.config_directory()
    directory.mkdir(parents=True)
    source = directory / "tasks.toml"
    source.write_text(
        tomlkit.dumps(
            {
                "ready": {
                    "cmd": "echo ready",
                    "env": {"SECRET": "private-listing-value"},
                },
                "new_cron": {"cmd": "true", "cron": "0 * * * *"},
                "finished": {"cmd": "true", "last_run": NOW},
                "expired": {"cmd": "true", "not_after": NOW - timedelta(days=1)},
                "waiting": {"cmd": "true", "interval": "1h", "last_run": BOUNDARY},
            }
        )
    )
    return source, source.read_bytes()


@pytest.mark.parametrize(
    "args", [["--list"], ["--list", "--dry-run"], ["--list", "--yes"]]
)
def test_cli_listing_is_read_only_and_does_not_expose_env(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    source, original = write_tasks()
    with (
        patch("tale.run.execute") as run,
        patch("tale.run.cleanup") as clean,
        patch("builtins.input") as prompt,
    ):
        assert invoke(args) == 0
    run.assert_not_called()
    clean.assert_not_called()
    prompt.assert_not_called()
    assert source.read_bytes() == original
    output = capsys.readouterr().out
    for name, state in [
        ("ready", "due"),
        ("new_cron", "new"),
        ("finished", "completed"),
        ("expired", "expired"),
        ("waiting", "waiting"),
    ]:
        assert f"{name}: {state}" in output
    assert "private-listing-value" not in output
    assert "SECRET" not in output
    assert str(source) in output
    assert "schedule: interval 1:00:00" in output
    assert "last_run: never" in output
    assert "next:" in output


def test_cli_listing_task_name_filter(capsys: pytest.CaptureFixture[str]) -> None:
    source, original = write_tasks()
    assert invoke(["--list", "waiting"]) == 0
    output = capsys.readouterr().out
    assert "waiting: waiting" in output
    assert "ready: due" not in output
    assert source.read_bytes() == original


def test_listing_empty_directory(capsys: pytest.CaptureFixture[str]) -> None:
    assert invoke(["--list"]) == 0
    assert "No tasks found." in capsys.readouterr().out


def test_listing_reports_config_errors_while_showing_valid_tasks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, original = write_tasks()
    with source.open("a") as stream:
        stream.write('\n[invalid]\nenv = { KEY = "value" }\n')
    assert invoke(["--list"]) == 1
    output = capsys.readouterr().out
    assert "cmd is required" in output
    assert "ready: due" in output
    assert source.read_bytes().startswith(original)


def test_list_and_cleanup_are_mutually_exclusive() -> None:
    with patch("tale.run.invocation_lock") as lock, pytest.raises(SystemExit) as error:
        main(["--list", "--cleanup"])
    assert error.value.code == 2
    lock.assert_not_called()
