from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from tale import dev


def test_build_runs_all_steps_in_order() -> None:
    with patch("tale.dev.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0)

        dev.build()

    assert [call.args[0][0] for call in run.call_args_list] == [
        "pytest",
        "mypy",
        "ruff",
        "ruff",
    ]
    assert run.call_args_list[2].args[0] == ("ruff", "format")
    assert run.call_args_list[3].args[0] == ("ruff", "check", "--fix")


def test_build_stops_on_failure() -> None:
    with patch("tale.dev.subprocess.run") as run:
        run.side_effect = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 2),
        ]

        with pytest.raises(SystemExit) as error:
            dev.build()

    assert error.value.code == 2
    assert run.call_count == 2
