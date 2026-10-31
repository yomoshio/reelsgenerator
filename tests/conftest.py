import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_local_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Settings read `.env` from the working directory and REELSMITH_* variables; a
    developer's own values must not change what the tests see."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("REELSMITH_"):
            monkeypatch.delenv(name)
