import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Every test gets its own workspace so caches and projects never leak between tests."""
    monkeypatch.setattr(settings, "workspace_dir", str(tmp_path / "ws"))
    # Legacy tests script model replies in call order, so they need strictly sequential execution.
    # Concurrency has its own tests (tests/test_concurrency.py), which set it explicitly.
    monkeypatch.setattr(settings, "llm_concurrency", 1)
