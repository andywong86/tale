from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from tale.config import load_tasks
from tale.executor import execute
from tale.models import DueTask, Task
from tale.run import main


def test_same_timestamp_executions_preserve_separate_logs(tmp_path: Path) -> None:
    source = tmp_path / "tasks.toml"
    source.write_text('[job]\ncmd = "echo hello"\n')
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    task = Task("job", "echo hello", "* * * * *", tmp_path, False, source, None)
    occurrences = (now - timedelta(minutes=1), now)
    existing = tmp_path / "tale_job_20260101T120000+0000.log"
    existing.write_text("keep existing log")

    with patch("tale.executor.datetime") as clock:
        clock.now.return_value = now
        # Catch-up runs followed by a separate invocation at the same instant.
        assert execute(DueTask(task, occurrences)) == [0, 0]
        assert execute(DueTask(task, (now,))) == [0]

    assert existing.read_text() == "keep existing log"
    logs = [path for path in tmp_path.glob("tale_job_*.log") if path != existing]
    assert len(logs) == 3
    texts = [path.read_text() for path in logs]
    assert all("hello" in text and "exit_code = 0" in text for text in texts)
    assert (
        sum(f"scheduled = {occurrences[0].isoformat()}" in text for text in texts) == 1
    )
    assert sum(f"scheduled = {now.isoformat()}" in text for text in texts) == 2


@pytest.mark.parametrize(
    "commands, expected_status",
    [
        (("true", "true"), 0),
        (("false", "true"), 1),
        (("true", "false"), 1),
        (("false", "false"), 1),
    ],
)
def test_cli_exit_status_and_continued_execution(
    tmp_path: Path, commands: tuple[str, str], expected_status: int
) -> None:
    source = tmp_path / "tasks.toml"
    source.write_text(
        "\n".join(
            f'[{name}]\ncmd = "{cmd}"\ndir = "{tmp_path.as_posix()}"\n'
            for name, cmd in zip(("first", "second"), commands)
        )
    )
    tasks, errors = load_tasks(tmp_path)
    with patch("tale.run.load_tasks", return_value=(tasks, errors)):
        assert main(["--yes"]) == expected_status

    refreshed, errors = load_tasks(tmp_path)
    assert errors == []
    for task, cmd in zip(refreshed, commands):
        assert (task.last_run is not None) is (cmd == "true")
        logs = list(tmp_path.glob(f"tale_{task.name}_*.log"))
        assert len(logs) == 1
        assert f"exit_code = {0 if cmd == 'true' else 1}" in logs[0].read_text()


@pytest.mark.parametrize("args", [[], ["--yes"], ["--dry-run"]])
def test_blank_line_between_tasks_only_in_interactive_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tasks = [
        Task(name, "true", None, tmp_path, True, tmp_path / "tasks.toml", None)
        for name in ("first", "second")
    ]
    due = [DueTask(task, (now,)) for task in tasks]
    with (
        patch("tale.run.load_tasks", return_value=(tasks, [])),
        patch("tale.run.find_due", return_value=(due, [])),
        patch("tale.run.execute", return_value=[0]),
        patch("builtins.input", return_value="n"),
    ):
        assert main(args) == 0
    output = capsys.readouterr().out
    assert output.startswith("first:")
    assert ("\n\nsecond:" in output) is (not args)


def test_cli_detects_failure_after_successful_catch_up_run(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    task = Task("job", "true", "* * * * *", tmp_path, False, tmp_path / "x.toml", now)
    due = DueTask(task, (now, now + timedelta(minutes=1)))
    with (
        patch("tale.run.load_tasks", return_value=([task], [])),
        patch("tale.run.find_due", return_value=([due], [])),
        patch("tale.run.execute", return_value=[0, 7]) as run,
    ):
        assert main(["--yes"]) == 1
    run.assert_called_once_with(due)


@pytest.mark.parametrize(
    "config_errors, schedule_errors",
    [([], []), (["bad config"], []), ([], ["bad schedule"])],
)
def test_cli_exit_status_when_nothing_is_due(
    config_errors: list[str], schedule_errors: list[str]
) -> None:
    with (
        patch("tale.run.load_tasks", return_value=([], config_errors)),
        patch("tale.run.find_due", return_value=([], schedule_errors)),
        patch("tale.run.execute") as run,
    ):
        assert main(["--yes"]) == (1 if config_errors or schedule_errors else 0)
    run.assert_not_called()
