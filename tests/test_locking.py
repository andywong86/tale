from __future__ import annotations

import errno
import fcntl
import os
import select
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from tale import config
from tale.locking import LockError, invocation_lock
from tale.run import main

_HOLDER = """
import sys
from pathlib import Path
from tale.locking import invocation_lock
with invocation_lock(Path(sys.argv[1])):
    print('locked', flush=True)
    sys.stdin.read()
"""
_CLI = "from tale.run import main; raise SystemExit(main())"


@contextmanager
def lock_holder(directory: Path) -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", _HOLDER, str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "lock holder did not report readiness"
        assert process.stdout.readline().strip() == "locked"
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_lock_creates_directory_and_keeps_stable_file(tmp_path: Path) -> None:
    directory = tmp_path / "nested" / "config"
    path = directory / ".lock"
    with invocation_lock(directory):
        assert path.is_file()
        inode = path.stat().st_ino
        with (
            pytest.raises(LockError, match="Another Tale invocation is active"),
            invocation_lock(directory),
        ):
            pytest.fail("second acquisition must not succeed")
    assert path.is_file()
    with invocation_lock(directory):
        assert path.stat().st_ino == inode


@pytest.mark.parametrize(
    "error", [RuntimeError("failed"), KeyboardInterrupt(), SystemExit(2)]
)
def test_lock_released_on_exception(tmp_path: Path, error: BaseException) -> None:
    with pytest.raises(type(error)), invocation_lock(tmp_path):
        raise error
    with invocation_lock(tmp_path):
        pass


@pytest.mark.parametrize("crash", [False, True])
def test_os_releases_lock_after_process_exit(tmp_path: Path, crash: bool) -> None:
    with lock_holder(tmp_path) as process:
        inode = (tmp_path / ".lock").stat().st_ino
        with pytest.raises(LockError), invocation_lock(tmp_path):
            pytest.fail("another process owns the lock")
        if crash:
            process.kill()
            process.wait(timeout=10)
        else:
            process.communicate(input="", timeout=10)
            assert process.returncode == 0
        with invocation_lock(tmp_path):
            assert (tmp_path / ".lock").stat().st_ino == inode


@pytest.mark.parametrize(
    "args",
    [
        ["--yes"],
        ["--dry-run"],
        ["--cleanup", "--yes"],
        ["--cleanup", "--dry-run"],
        ["pending", "--yes"],
    ],
)
def test_cli_fails_fast_without_reading_or_changing_tasks(
    tmp_path: Path, args: list[str]
) -> None:
    home = tmp_path / "home"
    directory = home / ".config" / "tale"
    directory.mkdir(parents=True)
    source = directory / "tasks.toml"
    source.write_text(
        f'[pending]\ncmd = "touch marker"\ndir = "{tmp_path.as_posix()}"\n'
        '[scheduled]\ncmd = "true"\ncron = "* * * * *"\n'
        '[done]\ncmd = "true"\nlast_run = 2026-01-01T00:00:00Z\n'
    )
    original = source.read_bytes()
    with lock_holder(directory):
        result = subprocess.run(
            [sys.executable, "-c", _CLI, *args],
            env={**os.environ, "HOME": str(home)},
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    assert result.returncode == 1
    assert "Another Tale invocation is active." in result.stderr
    assert result.stdout == ""
    assert source.read_bytes() == original
    assert not (tmp_path / "marker").exists()
    assert list(tmp_path.glob("*.log")) == []


def test_busy_lock_is_checked_before_configuration_loading() -> None:
    with invocation_lock(config.config_directory()):
        with patch("tale.run.load_tasks") as load:
            assert main(["--yes"]) == 1
        load.assert_not_called()


@pytest.mark.parametrize("stage", ["load", "prompt", "execute", "cleanup", "schedule"])
def test_lock_held_through_entire_cli_invocation(tmp_path: Path, stage: str) -> None:
    directory = config.config_directory()
    directory.mkdir(parents=True)
    source = directory / "tasks.toml"
    source.write_text(f'[job]\ncmd = "true"\ndir = "{tmp_path.as_posix()}"\n')
    observed = False

    def check_lock() -> None:
        nonlocal observed
        with pytest.raises(LockError), invocation_lock(directory):
            pytest.fail("the CLI released its lock too early")
        observed = True

    if stage == "load":

        def fake_load() -> tuple[list[object], list[str]]:
            check_lock()
            return [], []

        with patch("tale.run.load_tasks", side_effect=fake_load):
            assert main(["--dry-run"]) == 0
    elif stage == "prompt":

        def answer(_: str) -> str:
            check_lock()
            return "n"

        with patch("builtins.input", side_effect=answer):
            assert main([]) == 0
    elif stage == "execute":

        def fake_execute(_: object) -> list[int]:
            check_lock()
            return [0]

        with patch("tale.run.execute", side_effect=fake_execute):
            assert main(["--yes"]) == 0
    elif stage == "cleanup":

        def fake_cleanup(*_: object, **__: object) -> int:
            check_lock()
            return 0

        with patch("tale.run.cleanup", side_effect=fake_cleanup):
            assert main(["--cleanup", "--yes"]) == 0
    else:

        def fake_schedule(*_: object, **__: object) -> tuple[list[object], list[str]]:
            check_lock()
            return [], []

        with patch("tale.run.find_due", side_effect=fake_schedule):
            assert main(["--dry-run"]) == 0
    assert observed
    with invocation_lock(directory):
        pass


def test_help_does_not_acquire_lock() -> None:
    with (
        patch("tale.run.invocation_lock") as lock,
        pytest.raises(SystemExit) as exit_info,
    ):
        main(["--help"])
    assert exit_info.value.code == 0
    lock.assert_not_called()


def test_cannot_create_lock_directory_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = config.config_directory()
    directory.write_text("not a directory")
    with patch("tale.run.load_tasks") as load:
        assert main(["--dry-run"]) == 1
    load.assert_not_called()
    assert "cannot open Tale lock" in capsys.readouterr().err


def test_cannot_open_lock_file_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    directory = config.config_directory()
    (directory / ".lock").mkdir(parents=True)
    assert main(["--cleanup", "--yes"]) == 1
    assert "cannot open Tale lock" in capsys.readouterr().err


def test_flock_failure_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("tale.locking.fcntl.flock", side_effect=OSError("unsupported locking")):
        with patch("tale.run.load_tasks") as load:
            assert main(["--yes"]) == 1
        load.assert_not_called()
    assert "cannot acquire Tale lock" in capsys.readouterr().err
    with invocation_lock(config.config_directory()):
        pass


@pytest.mark.parametrize("code", [errno.EACCES, errno.EAGAIN])
def test_contention_errno_is_reported_as_busy(
    code: int, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("tale.locking.fcntl.flock", side_effect=OSError(code, "busy")):
        assert main(["--dry-run"]) == 1
    assert "Another Tale invocation is active." in capsys.readouterr().err


def test_lock_descriptor_is_not_inheritable(tmp_path: Path) -> None:
    flock = fcntl.flock
    descriptors: list[int] = []

    def check_descriptor(fd: int, operation: int) -> None:
        assert not os.get_inheritable(fd)
        descriptors.append(fd)
        flock(fd, operation)

    with (
        patch("tale.locking.fcntl.flock", side_effect=check_descriptor),
        invocation_lock(tmp_path),
    ):
        assert len(descriptors) == 1


def test_cli_exception_releases_lock_without_misreporting_acquisition_failure() -> None:
    with (
        patch("tale.run.load_tasks", side_effect=RuntimeError("task error")),
        pytest.raises(RuntimeError, match="task error"),
    ):
        main(["--yes"])
    with invocation_lock(config.config_directory()):
        pass


def test_cleanup_leaves_lock_file_when_last_task_file_deleted() -> None:
    directory = config.config_directory()
    directory.mkdir(parents=True)
    source = directory / "tasks.toml"
    source.write_text('[done]\ncmd = "true"\nlast_run = 2026-01-01T00:00:00Z\n')
    assert main(["--cleanup", "--yes"]) == 0
    assert not source.exists()
    assert (directory / ".lock").is_file()
    with invocation_lock(directory):
        pass
