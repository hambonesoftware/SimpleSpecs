"""Tests for MinerU startup diagnostics."""

from backend.config import Settings
from backend.services import pdf_mineru


def test_check_mineru_availability_disabled() -> None:
    settings = Settings(MINERU_ENABLED=False)

    available, reason = pdf_mineru.check_mineru_availability(settings=settings)

    assert not available
    assert reason == "MinerU is disabled in settings."


def test_check_mineru_availability_success(monkeypatch) -> None:
    class FakeModule:
        @staticmethod
        def parse(path: str):  # pragma: no cover - simplified stand-in
            return []

    def fake_loader():
        return FakeModule(), "mineru", None

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


def test_check_mineru_availability_missing_parse(monkeypatch) -> None:
    def fake_loader():
        return None, "mineru", (
            "MinerU client library is installed but is missing the 'parse' API. "
            "Please install the official MinerU package or choose the native engine."
        )

    monkeypatch.setattr(pdf_mineru, "_load_mineru_module", fake_loader)
    settings = Settings(MINERU_ENABLED=True)

    available, reason = pdf_mineru.check_mineru_availability(settings=settings)

    assert not available
    assert reason is not None
    assert "missing the 'parse' API" in reason
