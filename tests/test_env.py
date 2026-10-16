from __future__ import annotations

import json
import os
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import tomlkit

from tale.config import load_tasks
from tale.executor import execute
from tale.models import DueTask
from tale.run import main


def write_config(tmp_path: Path, env: object, cmd: str = "true") -> Path:
    path = tmp_path / "tasks.toml"
    path.write_text(
        tomlkit.dumps({"job": {"cmd": cmd, "dir": str(tmp_path), "env": env}}),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("env", [{}, {"NAME": "value"}, {"EMPTY": "", "NUMBER": "42"}])
def test_load_env_table(tmp_path: Path, env: dict[str, str]) -> None:
    write_config(tmp_path, env)
    tasks, errors = load_tasks(tmp_path)
    assert errors == []
    assert tasks[0].env == env


def test_load_native_subtable_and_inline_table(tmp_path: Path) -> None:
    (tmp_path / "tasks.toml").write_text(
        '[first]\ncmd = "true"\n[first.env]\nLEVEL = "info"\n'
        '[second]\ncmd = "true"\nenv = { LEVEL = "debug" }\n'
        '[third]\ncmd = "true"\n'
    )
    tasks, errors = load_tasks(tmp_path)
    assert errors == []
    assert [task.env for task in tasks] == [{"LEVEL": "info"}, {"LEVEL": "debug"}, {}]


@pytest.mark.parametrize(
    "env",
    [
        "not a table",
        42,
        False,
        [],
        {"VALUE": 42},
        {"VALUE": False},
        {"VALUE": ["a"]},
        {"VALUE": {"nested": "value"}},
        {"": "value"},
        {"BAD=NAME": "value"},
        {"BAD\0NAME": "value"},
        {"VALUE": "secret\0value"},
    ],
)
def test_invalid_env_is_a_config_error(tmp_path: Path, env: object) -> None:
    write_config(tmp_path, env)
    tasks, errors = load_tasks(tmp_path)
    assert tasks == []
    assert len(errors) == 1
    assert "env" in errors[0]
    assert "secret" not in errors[0]


def test_invalid_env_does_not_discard_other_tasks(tmp_path: Path) -> None:
    path = write_config(tmp_path, {"VALUE": 42})
    with path.open("a") as stream:
        stream.write('\n[valid]\ncmd = "true"\n')
    tasks, errors = load_tasks(tmp_path)
    assert [task.name for task in tasks] == ["valid"]
    assert len(errors) == 1


def test_execution_merges_environment_literally_without_logging_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TALE_TEST_INHERITED", "from-parent")
    monkeypatch.setenv("TALE_TEST_OVERRIDE", "parent-value")
    monkeypatch.setenv("TALE_TEST_EMPTY", "not-empty")
    secret = "unique-private-test-value"
    env = {
        "TALE_TEST_OVERRIDE": "child-value",
        "TALE_TEST_EMPTY": "",
        "TALE_TEST_LITERAL": "$HOME/${USER}/~; $(echo not-expanded)",
        "TALE_TEST_SECRET": secret,
        "TALE_TEST_UNICODE": "hello 世界",
    }
    script = tmp_path / "capture.py"
    script.write_text(
        "import json, os\nfrom pathlib import Path\n"
        "Path('captured.json').write_text(json.dumps({k: v for k, v in os.environ.items() "
        "if k.startswith('TALE_TEST_')}))\n"
    )
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    write_config(tmp_path, env, cmd)
    before = dict(os.environ)
    # Exercise the actual CLI while keeping real user config untouched.
    with patch("tale.run.load_tasks", return_value=load_tasks(tmp_path)):
        assert main(["--yes"]) == 0
    captured = json.loads((tmp_path / "captured.json").read_text())
    assert captured == {**env, "TALE_TEST_INHERITED": "from-parent"}
    assert dict(os.environ) == before
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    logs = list(tmp_path.glob("tale_job_*.log"))
    assert len(logs) == 1
    assert secret not in logs[0].read_text()
    assert "TALE_TEST_SECRET" not in logs[0].read_text()
    # Updating last_run must preserve the nested environment table.
    refreshed, errors = load_tasks(tmp_path)
    assert errors == []
    assert refreshed[0].env == env
    assert refreshed[0].last_run is not None


def test_environment_overrides_do_not_leak_between_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALE_TEST_SCOPE", "parent")
    source = tmp_path / "tasks.toml"
    source.write_text(
        tomlkit.dumps(
            {
                "first": {
                    "cmd": 'printf "%s" "$TALE_TEST_SCOPE"',
                    "dir": str(tmp_path),
                    "env": {"TALE_TEST_SCOPE": "child"},
                },
                "second": {
                    "cmd": 'printf "%s" "$TALE_TEST_SCOPE"',
                    "dir": str(tmp_path),
                },
            }
        )
    )
    tasks, errors = load_tasks(tmp_path)
    assert errors == []
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for task in tasks:
        assert execute(DueTask(task, (now,))) == [0]
    for name, expected in [("first", "child"), ("second", "parent")]:
        log = next(tmp_path.glob(f"tale_{name}_*.log")).read_text()
        output = log.split("---\n", 1)[1].split("\n---", 1)[0]
        assert output == expected
    assert os.environ["TALE_TEST_SCOPE"] == "parent"
