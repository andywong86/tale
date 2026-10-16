from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from tale import config
from tale.models import DueTask, Task
from tale.run import main
from tale.summary import ExecutionSummary

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def due_task(tmp_path: Path, name: str, count: int = 1) -> DueTask:
    task = Task(
        name, "true", "* * * * *", tmp_path, False, tmp_path / "tasks.toml", NOW
    )
    return DueTask(task, tuple(NOW + timedelta(minutes=i) for i in range(1, count + 1)))


@pytest.mark.parametrize(
    "results, succeeded, failed, deferred, run_successes, run_failures, not_run",
    [
        ([0, 0, 0], 1, 0, 0, 3, 0, 0),
        ([7], 0, 1, 0, 0, 1, 2),
        ([0, 7], 0, 1, 0, 1, 1, 1),
        ([], 0, 0, 1, 0, 0, 3),
        ([0], 0, 0, 1, 1, 0, 2),
        ([-15], 0, 1, 0, 0, 1, 2),
    ],
)
def test_record_results_distinguishes_tasks_from_executions(
    results: list[int],
    succeeded: int,
    failed: int,
    deferred: int,
    run_successes: int,
    run_failures: int,
    not_run: int,
) -> None:
    summary = ExecutionSummary(executions_not_run=3)
    summary.record_results(3, results)
    assert summary.succeeded == succeeded
    assert summary.failed == failed
    assert summary.deferred == deferred
    assert summary.executions_succeeded == run_successes
    assert summary.executions_failed == run_failures
    assert summary.executions_not_run == not_run


def test_mixed_run_summary_and_exit_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    due = [
        due_task(tmp_path, name, count)
        for name, count in [
            ("success", 2),
            ("failure", 3),
            ("declined", 1),
            ("expired_after_confirmation", 1),
        ]
    ]
    tasks = [item.task for item in due] + [
        due_task(tmp_path, "waiting").task,
        due_task(tmp_path, "invalid").task,
    ]
    with (
        patch("tale.run.load_tasks", return_value=(tasks, ["bad configuration"])),
        patch("tale.run.find_due", return_value=(due, ["bad schedule"])),
        patch("builtins.input", side_effect=["y", "y", "n", "y"]),
        patch("tale.run.execute", side_effect=[[0, 0], [0, 7], []]) as execute,
    ):
        assert main([]) == 1
    assert execute.call_count == 3
    output = capsys.readouterr().out
    assert (
        "Summary (tasks): 1 succeeded, 1 failed, 1 skipped, 1 deferred, 1 not due; 2 errors."
        in output
    )
    assert "Executions: 3 succeeded, 1 failed, 3 not run." in output
    assert output.count("Summary (tasks):") == 1
    assert "\n\nSummary (tasks):" in output


@pytest.mark.parametrize("collapsed", [True, False])
def test_collapsed_vs_catch_up_execution_counts(
    tmp_path: Path, collapsed: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    item = due_task(tmp_path, "job", 10)
    item = replace(item, task=replace(item.task, collapse=collapsed))
    count = 1 if collapsed else 10
    with (
        patch("tale.run.load_tasks", return_value=([item.task], [])),
        patch("tale.run.find_due", return_value=([item], [])),
        patch("tale.run.execute", return_value=[0] * count),
    ):
        assert main(["--yes"]) == 0
    output = capsys.readouterr().out
    assert "Summary (tasks): 1 succeeded, 0 failed" in output
    assert f"Executions: {count} succeeded, 0 failed, 0 not run." in output


def test_dry_run_summary_defers_due_tasks_without_running_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    due = [due_task(tmp_path, "first", 3), due_task(tmp_path, "second", 1)]
    with (
        patch("tale.run.load_tasks", return_value=([item.task for item in due], [])),
        patch("tale.run.find_due", return_value=(due, [])),
        patch("tale.run.execute") as execute,
        patch("builtins.input") as prompt,
    ):
        assert main(["--dry-run"]) == 0
    execute.assert_not_called()
    prompt.assert_not_called()
    output = capsys.readouterr().out
    assert (
        "Summary (tasks): 0 succeeded, 0 failed, 0 skipped, 2 deferred, 0 not due; 0 errors."
        in output
    )
    assert "Executions: 0 succeeded, 0 failed, 4 not run." in output


def test_declined_catch_up_task_counts_once_as_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    item = due_task(tmp_path, "job", 3)
    with (
        patch("tale.run.load_tasks", return_value=([item.task], [])),
        patch("tale.run.find_due", return_value=([item], [])),
        patch("tale.run.execute") as execute,
        patch("builtins.input", return_value="n"),
    ):
        assert main([]) == 0
    execute.assert_not_called()
    output = capsys.readouterr().out
    assert "0 succeeded, 0 failed, 1 skipped, 0 deferred, 0 not due" in output
    assert "Executions: 0 succeeded, 0 failed, 3 not run." in output


@pytest.mark.parametrize("results", [[], [0]])
def test_deadline_stops_are_deferred_not_successful_or_failed(
    tmp_path: Path, results: list[int], capsys: pytest.CaptureFixture[str]
) -> None:
    item = due_task(tmp_path, "job", 3)
    with (
        patch("tale.run.load_tasks", return_value=([item.task], [])),
        patch("tale.run.find_due", return_value=([item], [])),
        patch("tale.run.execute", return_value=results),
    ):
        assert main(["--yes"]) == 0
    output = capsys.readouterr().out
    assert "0 succeeded, 0 failed, 0 skipped, 1 deferred, 0 not due" in output
    assert (
        f"Executions: {len(results)} succeeded, 0 failed, {3 - len(results)} not run."
        in output
    )


@pytest.mark.parametrize("errors", [[], ["bad configuration"]])
def test_empty_run_still_has_summary(
    errors: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch("tale.run.load_tasks", return_value=([], errors)),
        patch("tale.run.find_due", return_value=([], [])),
    ):
        assert main(["--yes"]) == bool(errors)
    output = capsys.readouterr().out
    assert "No tasks are due." in output
    assert (
        f"0 succeeded, 0 failed, 0 skipped, 0 deferred, 0 not due; {len(errors)} errors."
        in output
    )
    assert "Executions: 0 succeeded, 0 failed, 0 not run." in output


def test_real_scheduling_not_due_and_error_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = config.config_directory()
    directory.mkdir(parents=True)
    source = directory / "tasks.toml"
    source.write_text(
        '[new_cron]\ncmd = "true"\ncron = "0 * * * *"\n'
        '[completed]\ncmd = "true"\nlast_run = 2026-01-01T00:00:00Z\n'
        '[expired]\ncmd = "true"\nnot_after = 2020-01-01T00:00:00Z\n'
        '[invalid_cron]\ncmd = "true"\ncron = "not cron"\n'
    )
    with patch("tale.run.execute") as execute:
        assert main(["--yes"]) == 1
    execute.assert_not_called()
    output = capsys.readouterr().out
    assert (
        "0 succeeded, 0 failed, 0 skipped, 0 deferred, 3 not due; 1 errors." in output
    )


def test_name_filter_excludes_unselected_tasks_from_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chosen = due_task(tmp_path, "chosen")
    ignored = due_task(tmp_path, "ignored")
    with (
        patch("tale.run.load_tasks", return_value=([chosen.task, ignored.task], [])),
        patch("tale.run.find_due", return_value=([chosen], [])),
        patch("tale.run.execute", return_value=[0]),
    ):
        assert main(["--yes", "chosen"]) == 0
    output = capsys.readouterr().out
    assert "1 succeeded, 0 failed, 0 skipped, 0 deferred, 0 not due" in output


@pytest.mark.parametrize("mode", ["--list", "--cleanup"])
def test_other_modes_do_not_print_execution_summary(
    mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("tale.run.load_tasks", return_value=([], [])):
        assert main([mode, "--yes"]) == 0
    assert "Summary (tasks):" not in capsys.readouterr().out
