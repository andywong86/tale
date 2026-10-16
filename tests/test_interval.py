from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from tale.config import load_tasks
from tale.duration import parse_duration
from tale.executor import execute
from tale.run import main
from tale.scheduler import find_due


@pytest.mark.parametrize(
    "value, seconds",
    [
        ("1s", 1),
        ("30m", 1800),
        ("6h", 21600),
        ("2d", 172800),
        ("1w", 604800),
        ("1h30m", 5400),
        (" 1h 30m ", 5400),
        ("1w 2d 3h 4m 5s", 788645),
    ],
)
def test_parse_duration(value: str, seconds: int) -> None:
    assert parse_duration(value) == timedelta(seconds=seconds)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "60",
        "0s",
        "1h 0m",
        "-1h",
        "+1h",
        "1.5h",
        "1H",
        "1y",
        "1month",
        "1h garbage",
        "garbage 1h",
        "1h 2h",
        "1 h",
        "1h,30m",
        "999999999999999999999999w",
    ],
)
def test_parse_duration_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)


def write_task(tmp_path: Path, settings: str = "", cmd: str = "true") -> Path:
    path = tmp_path / "tasks.toml"
    path.write_text(
        f'[job]\ncmd = "{cmd}"\ndir = "{tmp_path.as_posix()}"\n'
        f'interval = "6h"\n{settings}',
        encoding="utf-8",
    )
    return path


def test_load_interval(tmp_path: Path) -> None:
    write_task(tmp_path)
    tasks, errors = load_tasks(tmp_path)
    assert errors == []
    assert tasks[0].interval == timedelta(hours=6)
    assert tasks[0].cron is None


@pytest.mark.parametrize("value", ['""', '"0s"', '"1h junk"', "42", "false"])
def test_load_invalid_interval(tmp_path: Path, value: str) -> None:
    (tmp_path / "tasks.toml").write_text(f'[job]\ncmd = "true"\ninterval = {value}\n')
    tasks, errors = load_tasks(tmp_path)
    assert tasks == []
    assert len(errors) == 1
    assert "interval" in errors[0]


def test_cron_and_interval_are_mutually_exclusive(tmp_path: Path) -> None:
    write_task(tmp_path, 'cron = "0 0 * * *"\n')
    tasks, errors = load_tasks(tmp_path)
    assert tasks == []
    assert len(errors) == 1
    assert "mutually exclusive" in errors[0]


@pytest.mark.parametrize("persist_initial", [True, False])
def test_first_discovery_is_due_without_persisting(
    tmp_path: Path, persist_initial: bool
) -> None:
    path = write_task(tmp_path)
    original = path.read_text()
    tasks, _ = load_tasks(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    due, errors = find_due(tasks, now, persist_initial=persist_initial)
    assert errors == []
    assert len(due) == 1
    assert due[0].occurrences == (now,)
    assert path.read_text() == original


@pytest.mark.parametrize(
    "elapsed, expected",
    [
        (-1, False),
        (0, False),
        (21599, False),
        (21600, True),
        (21601, True),
        (864000, True),
    ],
)
@pytest.mark.parametrize("collapse", [False, True])
def test_interval_boundary_and_no_catch_up(
    tmp_path: Path, elapsed: int, expected: bool, collapse: bool
) -> None:
    write_task(
        tmp_path,
        f"last_run = 2026-01-01T00:00:00Z\ncollapse = {str(collapse).lower()}\n",
    )
    tasks, _ = load_tasks(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=elapsed)
    due, errors = find_due(tasks, now)
    assert errors == []
    assert bool(due) is expected
    if expected:
        assert due[0].occurrences == (now,)
        assert due[0].run_count == 1


@pytest.mark.parametrize("previous", [None, datetime(2026, 1, 1, tzinfo=UTC)])
@pytest.mark.parametrize("code", [0, 1])
def test_execution_records_completion_only_on_success(
    tmp_path: Path, previous: datetime | None, code: int
) -> None:
    settings = f"last_run = {previous.isoformat()}\n" if previous else ""
    write_task(tmp_path, settings, cmd="true" if code == 0 else "false")
    tasks, _ = load_tasks(tmp_path)
    scheduled = datetime(2026, 1, 2, tzinfo=UTC)
    started = scheduled + timedelta(minutes=2)
    finished = started + timedelta(minutes=5)
    due, errors = find_due(tasks, scheduled)
    assert errors == []
    with patch("tale.executor.datetime") as clock:
        clock.now.side_effect = [started, finished]
        assert execute(due[0]) == [code]

    tasks, _ = load_tasks(tmp_path)
    assert tasks[0].last_run == (finished if code == 0 else previous)
    due, errors = find_due(tasks, finished + timedelta(hours=6) - timedelta(seconds=1))
    assert errors == []
    assert bool(due) is (code != 0)
    due, errors = find_due(tasks, finished + timedelta(hours=6))
    assert errors == []
    assert len(due) == 1


def test_interval_uses_absolute_elapsed_time_across_dst(tmp_path: Path) -> None:
    write_task(tmp_path)
    tasks, _ = load_tasks(tmp_path)
    zone = ZoneInfo("America/New_York")
    last = datetime(2026, 3, 8, 0, tzinfo=zone)
    task = replace(tasks[0], last_run=last)
    # Spring forward: 6 AM is only five elapsed hours after midnight.
    due, errors = find_due([task], datetime(2026, 3, 8, 6, tzinfo=zone))
    assert errors == []
    assert due == []
    due, errors = find_due([task], datetime(2026, 3, 8, 7, tzinfo=zone))
    assert errors == []
    assert len(due) == 1


@pytest.mark.parametrize("dry_run", [True, False])
def test_cli_dry_run_or_decline_does_not_mark_interval_complete(
    tmp_path: Path, dry_run: bool
) -> None:
    path = write_task(tmp_path)
    original = path.read_text()
    tasks, errors = load_tasks(tmp_path)
    with (
        patch("tale.run.load_tasks", return_value=(tasks, errors)),
        patch("builtins.input", return_value="n"),
        patch("tale.run.execute") as run,
    ):
        assert main(["--dry-run"] if dry_run else []) == 0
    run.assert_not_called()
    assert path.read_text() == original
