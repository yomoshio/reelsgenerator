import pytest

from reelsmith.settings import Settings


def test_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REELSMITH_CODER", "qwen3-coder:30b")
    monkeypatch.setenv("REELSMITH_WORKERS", "3")
    settings = Settings()
    assert settings.coder == "qwen3-coder:30b"
    assert settings.cores() == 3
    assert settings.editor == ""
