from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_headers


class DummySettings(SimpleNamespace):
    ARTIFACTS_DIR: str


def _build_repo_layout(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    (repo_root / "tests" / "golden" / "before").mkdir(parents=True)
    (repo_root / "tests" / "fixtures" / "layout").mkdir(parents=True)
    (repo_root / "artifacts").mkdir(parents=True)
    (repo_root / "docs").mkdir(parents=True)
    return repo_root


def test_find_pdf_for_upload_prefers_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _build_repo_layout(tmp_path)
    upload_id = "abc123"
    pdf_path = repo_root / "artifacts" / upload_id / "source" / "doc.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"sample")

    monkeypatch.setattr(run_headers, "ROOT", repo_root)
    settings = DummySettings(ARTIFACTS_DIR=str(repo_root / "artifacts"))

    located = run_headers._find_pdf_for_upload(upload_id, settings=settings, index_path=None)

    assert located == pdf_path


def test_find_pdf_for_upload_uses_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _build_repo_layout(tmp_path)
    upload_id = "upload-index"
    pdf_path = repo_root / "docs" / "doc.pdf"
    pdf_path.write_bytes(b"index")
    index_path = repo_root / "tests" / "golden" / "before" / "index.json"
    index_data = [
        {
            "name": "doc",
            "pdf": str(pdf_path.relative_to(repo_root)),
            "upload_id": upload_id,
        }
    ]
    index_path.write_text(json.dumps(index_data), encoding="utf-8")

    monkeypatch.setattr(run_headers, "ROOT", repo_root)
    settings = DummySettings(ARTIFACTS_DIR=str(repo_root / "artifacts"))

    located = run_headers._find_pdf_for_upload(upload_id, settings=settings, index_path=index_path)

    assert located == pdf_path


def test_check_baselines_filters_upload_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _build_repo_layout(tmp_path)
    baseline_dir = repo_root / "tests" / "golden" / "before"
    layout_dir = repo_root / "tests" / "fixtures" / "layout"
    docs_dir = repo_root / "docs"

    entries: list[dict[str, str]] = []
    run_results: dict[str, tuple[str, list[dict], list[dict], list[dict], str]] = {}

    for suffix in ("one", "two"):
        pdf = docs_dir / f"{suffix}.pdf"
        pdf.write_bytes(suffix.encode("utf-8"))

        parsed = baseline_dir / f"{suffix}.objects.json"
        headers = baseline_dir / f"{suffix}.headers.json"
        raw = baseline_dir / f"{suffix}.headers.raw.txt"
        layout = layout_dir / f"{suffix}.lines.jsonl"

        objects = [{"kind": "paragraph", "text": suffix}]
        header_items = [{"section_name": suffix, "section_number": suffix}]
        lines = [{"text": suffix, "page_index": 0, "line_index": 0}]
        raw_text = "#headers#\n{}\n#headers#".format(suffix)

        parsed.write_text(json.dumps(objects), encoding="utf-8")
        headers.write_text(json.dumps(header_items), encoding="utf-8")
        raw.write_text(raw_text, encoding="utf-8")
        with layout.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(lines[0]))

        upload_id = f"upload-{suffix}"
        entries.append(
            {
                "name": suffix,
                "pdf": str(pdf.relative_to(repo_root)),
                "upload_id": upload_id,
                "parsed": str(parsed.relative_to(repo_root)),
                "headers": str(headers.relative_to(repo_root)),
                "raw": str(raw.relative_to(repo_root)),
                "layout": str(layout.relative_to(repo_root)),
            }
        )
        run_results[pdf.name] = (upload_id, objects, header_items, lines, raw_text)

    index_path = baseline_dir / "index.json"
    index_path.write_text(json.dumps(entries), encoding="utf-8")

    calls: list[str] = []

    def fake_run(pdf_path: Path, *, engine: str = "native"):
        calls.append(pdf_path.name)
        return run_results[pdf_path.name]

    monkeypatch.setattr(run_headers, "ROOT", repo_root)
    monkeypatch.setattr(run_headers, "_run_pipeline_for_pdf", fake_run)

    result = run_headers.check_baselines(
        index_path=index_path,
        engine="native",
        upload_id="upload-one",
    )

    assert result == 0
    assert calls == ["one.pdf"]
