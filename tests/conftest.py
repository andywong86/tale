from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep CLI tests and their real advisory locks away from user configuration."""
    directory = tmp_path / "config"
    monkeypatch.setattr("tale.config.config_directory", lambda: directory)
    monkeypatch.setattr("tale.run.config_directory", lambda: directory)
