"""Tests for MinerU startup diagnostics."""

from backend.config import Settings
from backend.services import pdf_mineru


def test_check_mineru_availability_disabled() -> None:
    settings = Settings(MINERU_ENABLED=False)

    available, reason = pdf_mineru.check_mineru_availability(settings=settings)

    assert not available
    assert reason == "MinerU is disabled in settings."


def test_check_mineru_availability_success(monkeypatch) -> None:
    def fake_loader():
        return object(), "mineru", None

    monkeypatch.setattr(pdf_mineru, "_load_mineru_module", fake_loader)
    settings = Settings(MINERU_ENABLED=True)

    available, reason = pdf_mineru.check_mineru_availability(settings=settings)

    assert available
    assert reason is None


def test_check_mineru_availability_failure(monkeypatch) -> None:
    def fake_loader():
        return None, None, "boom"

    monkeypatch.setattr(pdf_mineru, "_load_mineru_module", fake_loader)
    settings = Settings(MINERU_ENABLED=True)

    available, reason = pdf_mineru.check_mineru_availability(settings=settings)

    assert not available
    assert reason == "MinerU client library could not be imported: boom"
