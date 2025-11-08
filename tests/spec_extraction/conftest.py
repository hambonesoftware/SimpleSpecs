"""Fixtures specific to the spec extraction test suite."""

from __future__ import annotations

import pytest

from backend.services.simpleheaders_state import SimpleHeadersState


@pytest.fixture(autouse=True)
def _reset_spec_extraction_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with a pristine specs database and cache."""

    from backend.spec_extraction import init_db, reset_engine
    import backend.spec_extraction.jobs as jobs

    reset_engine()
    init_db()
    monkeypatch.setattr(jobs, "_LLM_CLIENT", None, raising=False)
    SimpleHeadersState.clear()
    yield
    monkeypatch.setattr(jobs, "_LLM_CLIENT", None, raising=False)
    SimpleHeadersState.clear()
    reset_engine()
