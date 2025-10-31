import pytest

from backend.utils.errors import AlignmentPreconditionError, OutlineParseError


def test_abort_on_no_lines(monkeypatch, tmp_path):
    monkeypatch.setenv("HEADERS_STRICT_ABORT_ON_NO_LINES", "1")
    monkeypatch.setenv("HEADERS_STRICT_FAIL_ON_EMPTY_OUTLINE", "0")

    import importlib

    import backend.config as config
    import backend.services.headers_llm_strict as strict_module

    importlib.reload(config)
    importlib.reload(strict_module)

    run_strict_headers_pipeline = strict_module.run_strict_headers_pipeline

    def fake_extract_lines(_):
        return []

    import backend.services.text_extraction as text_extraction

    monkeypatch.setattr(text_extraction, "extract_lines", fake_extract_lines)

    with pytest.raises(AlignmentPreconditionError) as exc:
        run_strict_headers_pipeline(
            file_id=1,
            file_path=str(tmp_path / "file.pdf"),
            provider="provider",
            model="model",
            trace=True,
        )

    assert exc.value.code == "no_lines"


def test_abort_on_empty_outline(monkeypatch, tmp_path):
    monkeypatch.setenv("HEADERS_STRICT_ABORT_ON_NO_LINES", "0")
    monkeypatch.setenv("HEADERS_STRICT_FAIL_ON_EMPTY_OUTLINE", "1")

    import importlib

    import backend.config as config
    import backend.services.headers_llm_strict as strict_module

    importlib.reload(config)
    importlib.reload(strict_module)

    run_strict_headers_pipeline = strict_module.run_strict_headers_pipeline

    def fake_extract_lines(_):
        return [{"text": "Example", "page": 1, "global_idx": 0}]

    def fake_outline(**_kwargs):
        return ""

    import backend.services.text_extraction as text_extraction
    import backend.services.llm as llm

    monkeypatch.setattr(text_extraction, "extract_lines", fake_extract_lines)
    monkeypatch.setattr(llm, "get_outline_for_headers", fake_outline)

    with pytest.raises(OutlineParseError) as exc:
        run_strict_headers_pipeline(
            file_id=2,
            file_path=str(tmp_path / "file.pdf"),
            provider="provider",
            model="model",
            trace=True,
        )

    assert exc.value.code == "empty_outline"
