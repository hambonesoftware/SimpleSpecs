"""Adapter for invoking MinerU in library or server mode."""
from __future__ import annotations

import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

JsonObj = Dict[str, Any]
NormObj = Dict[str, Any]


def _load_mineru_client():
    """Lazy import of the MinerU CLI client."""

    from mineru.cli.client import do_parse as _do_parse
    from mineru.cli.common import read_fn as _read_fn

    return _do_parse, _read_fn


def load_mineru_client() -> Tuple[Any, Any]:
    """Public wrapper returning the MinerU CLI helpers.

    This raises ``ImportError`` if MinerU is unavailable which simplifies
    availability checks in other modules.
    """

    return _load_mineru_client()


@dataclass
class MinerUConfig:
    mode: str = os.getenv("MINERU_MODE", "library")
    server_url: str = os.getenv("MINERU_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
    backend: str = os.getenv("MINERU_BACKEND", "pipeline")
    parse_method: str = os.getenv("MINERU_PARSE_METHOD", "auto")
    enable_table: bool = os.getenv("MINERU_ENABLE_TABLE", "true").lower() == "true"
    enable_formula: bool = os.getenv("MINERU_ENABLE_FORMULA", "true").lower() == "true"
    timeout_sec: int = int(os.getenv("MINERU_TIMEOUT_SEC", "180"))
    out_root: Path = Path(os.getenv("MINERU_OUT_ROOT", ".cache/mineru"))


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _search_content_list(out_dir: Path) -> Optional[Path]:
    for p in out_dir.rglob("*content_list.json"):
        return p
    for p in out_dir.rglob("*_content_list.json"):
        return p
    return None


def _search_markdown(out_dir: Path) -> Optional[Path]:
    for p in out_dir.rglob("*.md"):
        return p
    return None


def _search_tables(out_dir: Path) -> List[Path]:
    return list(out_dir.rglob("*.csv")) + list(out_dir.rglob("*.xlsx"))


def _norm_from_content_list(content_list: JsonObj) -> List[NormObj]:
    out: List[NormObj] = []

    def as_kind(value: str) -> str:
        value = (value or "").lower()
        if "title" in value or "header" in value or "heading" in value:
            return "heading"
        if "table" in value:
            return "table"
        if "figure" in value or "image" in value:
            return "figure"
        if "formula" in value or "equation" in value:
            return "formula"
        if "footnote" in value:
            return "footnote"
        if "list" in value:
            return "list"
        if "code" in value:
            return "code"
        return "paragraph"

    items = (
        content_list
        if isinstance(content_list, list)
        else content_list.get("items")
        or content_list.get("elements")
        or []
    )

    for index, block in enumerate(items):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type") or block.get("block_type") or ""
        text = block.get("text") or block.get("content")
        page = block.get("page_index") or block.get("page") or block.get("page_no")
        bbox = block.get("bbox") or block.get("box")

        out.append(
            {
                "id": block.get("id") or f"mineru-{index}",
                "page": int(page) if isinstance(page, (int, float)) else None,
                "kind": as_kind(str(block_type)),
                "text": text,
                "bbox": bbox if isinstance(bbox, list) else None,
                "meta": {
                    key: value
                    for key, value in block.items()
                    if key
                    not in {
                        "id",
                        "type",
                        "block_type",
                        "text",
                        "content",
                        "page_index",
                        "page",
                        "page_no",
                        "bbox",
                        "box",
                    }
                },
                "source": "mineru",
            }
        )
    return out


def _fallback_from_markdown(md_path: Path) -> List[NormObj]:
    blocks: List[NormObj] = []
    if not md_path or not md_path.exists():
        return blocks
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    for index, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        kind = "heading" if line.startswith("#") else "paragraph"
        blocks.append(
            {
                "id": f"mineru-md-{index}",
                "page": None,
                "kind": kind,
                "text": line.lstrip("# ").strip(),
                "bbox": None,
                "meta": {"md_file": str(md_path)},
                "source": "mineru",
            }
        )
    return blocks


def _augment_with_tables(objs: List[NormObj], table_files: List[Path]) -> None:
    for path in table_files:
        objs.append(
            {
                "id": f"mineru-table-{path.stem}",
                "page": None,
                "kind": "table",
                "text": None,
                "bbox": None,
                "meta": {"table_file": str(path)},
                "source": "mineru",
            }
        )


def _call_mineru_library(
    pdf_bytes: bytes, pdf_name: str, out_dir: Path, cfg: MinerUConfig
) -> None:
    do_parse, _read_fn = _load_mineru_client()
    do_parse(
        output_dir=str(out_dir),
        pdf_file_names=[Path(pdf_name).stem],
        pdf_bytes_list=[pdf_bytes],
        p_lang_list=["en"],
        backend=cfg.backend,
        parse_method=cfg.parse_method,
        p_formula_enable=cfg.enable_formula,
        p_table_enable=cfg.enable_table,
        server_url=None,
    )


def _call_mineru_server(
    pdf_bytes: bytes, pdf_name: str, out_dir: Path, cfg: MinerUConfig
) -> None:
    try:
        import requests
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("requests is required for MinerU server mode") from exc

    files = [("files", (pdf_name, io.BytesIO(pdf_bytes), "application/pdf"))]
    data = {
        "backend": cfg.backend,
        "parse_method": cfg.parse_method,
        "formula_enable": str(cfg.enable_formula).lower(),
        "table_enable": str(cfg.enable_table).lower(),
    }
    url = f"{cfg.server_url}/file_parse"
    response = requests.post(url, files=files, data=data, timeout=cfg.timeout_sec)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    _ensure_dir(out_dir)
    if "application/zip" in content_type or "octet-stream" in content_type:
        (out_dir / "mineru_server_artifacts.zip").write_bytes(response.content)
    else:
        (out_dir / "mineru_server_response.json").write_text(
            response.text, encoding="utf-8"
        )


def parse_with_mineru(
    upload_id: str,
    pdf_bytes: bytes,
    pdf_filename: str,
    cfg: Optional[MinerUConfig] = None,
) -> Tuple[List[NormObj], Path]:
    cfg = cfg or MinerUConfig()
    out_dir = _ensure_dir(cfg.out_root / upload_id)

    start_time = time.time()
    if cfg.mode == "server":
        _call_mineru_server(pdf_bytes, pdf_filename, out_dir, cfg)
    else:
        _call_mineru_library(pdf_bytes, pdf_filename, out_dir, cfg)
    duration = time.time() - start_time

    normalized: List[NormObj] = []
    content_list_path = _search_content_list(out_dir)
    if content_list_path and content_list_path.exists():
        try:
            content = json.loads(
                content_list_path.read_text(encoding="utf-8", errors="ignore")
            )
            normalized = _norm_from_content_list(content)
        except Exception:
            normalized = []

    if not normalized:
        markdown = _search_markdown(out_dir)
        normalized = _fallback_from_markdown(markdown) if markdown else []

    _augment_with_tables(normalized, _search_tables(out_dir))

    for block in normalized:
        block.setdefault("meta", {})
        block["meta"].update(
            {
                "upload_id": upload_id,
                "mineru_duration_sec": round(duration, 3),
                "mineru_mode": cfg.mode,
            }
        )
    return normalized, out_dir


__all__ = [
    "MinerUConfig",
    "NormObj",
    "parse_with_mineru",
    "load_mineru_client",
]
