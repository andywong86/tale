"""Development task entry points for `uv run -- <task>` commands."""

from __future__ import annotations

import subprocess


def _run(*args: str) -> None:
    raise SystemExit(subprocess.run(args, check=False).returncode)


def test() -> None:
    _run("pytest", "--cov=tale", "--cov-report=term-missing")


def typecheck() -> None:
    _run("mypy", ".")


def lint() -> None:
    _run("ruff", "check", "--fix")


def format() -> None:
    _run("ruff", "format")


def build() -> None:
    test()
    typecheck()
    format()
    lint()
