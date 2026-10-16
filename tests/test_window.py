from __future__ import annotations

import os
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from tale.config import load_tasks
from tale.executor import execute
from tale.models import DueTask, Task
from tale.run import main
from tale.scheduler import find_due
from tale.window import within_window

BASE = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def local_timezone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        yield
    finally:
        if original is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original)
        time.tzset()


def load_task(tmp_path: Path, settings: str = "") -> Task:
    source = tmp_path / "tasks.toml"
    source.write_text(
        f'[job]\ncmd = "echo hello"\ndir = "{tmp_path.as_posix()}"\n{settings}'
    )
    tasks, errors = load_tasks(tmp_path)
    assert errors == []
    return tasks[0]


@pytest.mark.parametrize("key", ["not_before", "not_after"])
@pytest.mark.parametrize(
    "value, expected, exclusive",
    [
        ("2026-01-01", BASE, True),
        ('"2026-01-01"', BASE, True),
        ("2026-01-01T00:00:00Z", BASE, False),
        ('"2026-01-01T00:00:00Z"', BASE, False),
        ("2026-01-01T08:00:00+08:00", BASE, False),
        ('"2025-12-31T19:00:00-05:00"', BASE, False),
        ('"2026-01-01 00:00:00+00:00"', BASE, False),
        ('"2026-01-01T00:00:00.123456Z"', BASE.replace(microsecond=123456), False),
    ],
)
def test_accepted_formats(
    tmp_path: Path, key: str, value: str, expected: datetime, exclusive: bool
) -> None:
    task = load_task(tmp_path, f"{key} = {value}\n")
    if key == "not_after" and exclusive:
        expected += timedelta(days=1)
    assert getattr(task, key) == expected
    assert task.not_after_exclusive is (key == "not_after" and exclusive)


@pytest.mark.parametrize("key", ["not_before", "not_after"])
@pytest.mark.parametrize(
    "value",
    [
        "2026-01-01T12:00:00",
        '"2026-01-01T12:00:00"',
        '"20260101"',
        '"2026-02-30"',
        '"tomorrow"',
        '"2026-01-01T12:00Z"',
        '""',
        "42",
        "false",
        "12:00:00",
        '"2026-01-01T00:00:00+99:00"',
    ],
)
def test_invalid_formats(tmp_path: Path, key: str, value: str) -> None:
    source = tmp_path / "tasks.toml"
    source.write_text(f'[job]\ncmd = "true"\n{key} = {value}\n')
    tasks, errors = load_tasks(tmp_path)
    assert tasks == []
    assert len(errors) == 1
    assert f"invalid {key}" in errors[0]


@pytest.mark.parametrize(
    "settings",
    [
        "not_before = 2026-01-02\nnot_after = 2026-01-01\n",
        "not_before = 2026-01-02T00:00:01Z\nnot_after = 2026-01-02T00:00:00Z\n",
    ],
)
def test_empty_window_is_rejected(tmp_path: Path, settings: str) -> None:
    (tmp_path / "tasks.toml").write_text(f'[job]\ncmd = "true"\n{settings}')
    tasks, errors = load_tasks(tmp_path)
    assert tasks == []
    assert "empty execution window" in errors[0]


def test_same_date_bounds_include_entire_day(tmp_path: Path) -> None:
    task = load_task(tmp_path, "not_before = 2026-01-01\nnot_after = 2026-01-01\n")
    assert within_window(task, BASE)
    assert within_window(task, BASE + timedelta(days=1, microseconds=-1))
    assert not within_window(task, BASE - timedelta(microseconds=1))
    assert not within_window(task, BASE + timedelta(days=1))


def test_timestamp_bounds_are_inclusive(tmp_path: Path) -> None:
    task = load_task(
        tmp_path,
        "not_before = 2026-01-01T00:00:00Z\nnot_after = 2026-01-01T00:00:00Z\n",
    )
    assert within_window(task, BASE)
    assert not within_window(task, BASE - timedelta(microseconds=1))
    assert not within_window(task, BASE + timedelta(microseconds=1))


@pytest.mark.parametrize("day, hours", [("2026-03-08", 23), ("2026-11-01", 25)])
def test_date_bounds_use_local_midnights_across_dst(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, day: str, hours: int
) -> None:
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    task = load_task(tmp_path, f"not_before = {day}\nnot_after = {day}\n")
    assert task.not_before is not None and task.not_after is not None
    assert task.not_after - task.not_before == timedelta(hours=hours)
    assert task.not_before.hour == (5 if hours == 23 else 4)


@pytest.mark.parametrize("kind", ["single", "cron", "interval"])
@pytest.mark.parametrize(
    "lower, upper", [(False, False), (True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize("hour", [1, 2, 3, 4, 5])
def test_schedule_window_matrix(
    tmp_path: Path, kind: str, lower: bool, upper: bool, hour: int
) -> None:
    settings = ""
    if kind != "single":
        settings += 'cron = "0 * * * *"\n' if kind == "cron" else 'interval = "1h"\n'
        settings += "last_run = 2026-01-01T00:00:00Z\n"
    if lower:
        settings += "not_before = 2026-01-01T02:00:00Z\n"
    if upper:
        settings += "not_after = 2026-01-01T04:00:00Z\n"
    task = load_task(tmp_path, settings)
    original = task.source.read_text()
    now = BASE + timedelta(hours=hour)
    due, errors = find_due([task], now)
    assert errors == []
    expected = (not lower or hour >= 2) and (not upper or hour <= 4)
    assert bool(due) is expected
    if expected:
        if kind == "single":
            assert due[0].occurrences == (now,)
        else:
            assert due[0].occurrences == tuple(
                BASE + timedelta(hours=index)
                for index in range(2 if lower else 1, hour + 1)
            )
        assert due[0].run_count == 1
    assert task.source.read_text() == original


@pytest.mark.parametrize("kind", ["single", "cron", "interval"])
@pytest.mark.parametrize(
    "lower, upper", [(False, False), (True, False), (False, True), (True, True)]
)
def test_first_discovery_window_matrix(
    tmp_path: Path, kind: str, lower: bool, upper: bool
) -> None:
    settings = ""
    if kind == "cron":
        settings += 'cron = "0 * * * *"\n'
    if kind == "interval":
        settings += 'interval = "1h"\ncollapse = false\n'
    if lower:
        settings += "not_before = 2026-01-01T02:00:00Z\n"
    if upper:
        settings += "not_after = 2026-01-01T04:00:00Z\n"
    task = load_task(tmp_path, settings)
    now = BASE + timedelta(hours=3)
    due, errors = find_due([task], now)
    assert errors == []
    refreshed, _ = load_tasks(tmp_path)
    if kind == "cron":
        assert due == []
        assert refreshed[0].last_run == now
    else:
        expected = (
            (BASE + timedelta(hours=2), now) if kind == "interval" and lower else (now,)
        )
        assert due[0].occurrences == expected
        assert refreshed[0].last_run is None


def test_cron_initialization_is_not_persisted_outside_window_or_during_dry_run(
    tmp_path: Path,
) -> None:
    task = load_task(
        tmp_path,
        'cron = "0 * * * *"\nnot_before = 2026-01-01T02:00:00Z\nnot_after = 2026-01-01T04:00:00Z\n',
    )
    for hour, persist in [(1, True), (5, True), (3, False)]:
        due, errors = find_due(
            [task], BASE + timedelta(hours=hour), persist_initial=persist
        )
        assert errors == []
        assert due == []
        refreshed, _ = load_tasks(tmp_path)
        assert refreshed[0].last_run is None


@pytest.mark.parametrize("kind", ["cron", "interval"])
@pytest.mark.parametrize("collapse", [False, True])
def test_filter_before_collapse_and_ignore_large_out_of_window_history(
    tmp_path: Path, kind: str, collapse: bool
) -> None:
    settings = 'cron = "* * * * *"\n' if kind == "cron" else 'interval = "1m"\n'
    settings += f"collapse = {str(collapse).lower()}\nlast_run = 2020-01-01T00:00:00Z\nnot_before = 2026-01-01T00:01:00Z\n"
    task = load_task(tmp_path, settings)
    due, errors = find_due([task], BASE + timedelta(minutes=3))
    assert errors == []
    assert due[0].occurrences == tuple(BASE + timedelta(minutes=i) for i in (1, 2, 3))
    assert due[0].run_count == (1 if collapse else 3)


@pytest.mark.parametrize("exclusive", [False, True])
def test_recheck_window_before_each_execution_and_allow_running_task_to_finish(
    tmp_path: Path, exclusive: bool
) -> None:
    task = load_task(tmp_path, "collapse = false\n")
    deadline = BASE + timedelta(hours=2)
    task = replace(task, not_after=deadline, not_after_exclusive=exclusive)
    due = DueTask(task, (BASE, BASE + timedelta(hours=1)))
    with patch("tale.executor.datetime") as clock:
        clock.now.side_effect = [
            deadline - timedelta(seconds=1),
            deadline + timedelta(seconds=1),
            deadline + timedelta(seconds=2),
        ]
        assert execute(due) == [0]
    refreshed, _ = load_tasks(tmp_path)
    assert refreshed[0].last_run == BASE
    assert len(list(tmp_path.glob("*.log"))) == 1


def test_executor_does_not_start_at_exclusive_date_deadline(tmp_path: Path) -> None:
    task = load_task(tmp_path, "not_after = 2026-01-01\n")
    with patch("tale.executor.datetime") as clock:
        clock.now.return_value = BASE + timedelta(days=1)
        assert execute(DueTask(task, (BASE,))) == []
    assert list(tmp_path.glob("*.log")) == []
    refreshed, _ = load_tasks(tmp_path)
    assert refreshed[0].last_run is None


@pytest.mark.parametrize("kind", ["cron", "interval"])
def test_non_aligned_lower_bound_preserves_schedule_phase(
    tmp_path: Path, kind: str
) -> None:
    settings = 'cron = "0 * * * *"\n' if kind == "cron" else 'interval = "1h"\n'
    task = load_task(
        tmp_path,
        settings
        + "last_run = 2026-01-01T00:00:00Z\nnot_before = 2026-01-01T01:30:00Z\n",
    )
    due, errors = find_due([task], BASE + timedelta(hours=3))
    assert errors == []
    assert due[0].occurrences == (BASE + timedelta(hours=2), BASE + timedelta(hours=3))


@pytest.mark.parametrize(
    "offset, expected", [(-1, False), (0, True), (3600, True), (3601, False)]
)
def test_executor_enforces_inclusive_timestamp_bounds(
    tmp_path: Path, offset: int, expected: bool
) -> None:
    task = load_task(
        tmp_path,
        "not_before = 2026-01-01T00:00:00Z\nnot_after = 2026-01-01T01:00:00Z\n",
    )
    with patch("tale.executor.datetime") as clock:
        clock.now.return_value = BASE + timedelta(seconds=offset)
        assert execute(DueTask(task, (BASE,))) == ([0] if expected else [])
    assert len(list(tmp_path.glob("*.log"))) == int(expected)
    refreshed, _ = load_tasks(tmp_path)
    assert refreshed[0].last_run == (BASE if expected else None)


def test_executor_filters_occurrences_before_collapsing(tmp_path: Path) -> None:
    task = load_task(
        tmp_path,
        "not_before = 2026-01-01T01:00:00Z\nnot_after = 2026-01-01T03:00:00Z\n",
    )
    occurrences = tuple(BASE + timedelta(hours=i) for i in (0, 1, 2, 4))
    with patch("tale.executor.datetime") as clock:
        clock.now.return_value = BASE + timedelta(hours=2)
        assert execute(DueTask(task, occurrences)) == [0]
    refreshed, _ = load_tasks(tmp_path)
    assert refreshed[0].last_run == BASE + timedelta(hours=2)


def test_delayed_confirmation_cannot_start_an_expired_task(tmp_path: Path) -> None:
    task = load_task(tmp_path, "not_after = 2026-01-01T01:00:00Z\n")
    with (
        patch("tale.run.load_tasks", return_value=([task], [])),
        patch("tale.run.datetime") as schedule_clock,
        patch("tale.executor.datetime") as execution_clock,
        patch("builtins.input", return_value="y"),
    ):
        schedule_clock.now.return_value = BASE
        execution_clock.now.return_value = BASE + timedelta(hours=2)
        assert main([]) == 0
    assert list(tmp_path.glob("*.log")) == []
    refreshed, _ = load_tasks(tmp_path)
    assert refreshed[0].last_run is None
