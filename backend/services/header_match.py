"""Exact header matcher with logging, TOC guard, and offset calibration."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple

from .lines import iter_lines

DOT_LEADERS_RE = re.compile(r"\.{2,}\s*\d+\s*$")
NUMBER_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")


def _norm(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = value.replace("\u2019", "'").replace("\u2018", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(value.split())


def _equal_heading(candidate: str, target: str) -> bool:
    return _norm(candidate) == _norm(target)


def _contains_heading(candidate: str, target: str) -> bool:
    candidate_norm = _norm(candidate)
    target_norm = _norm(target)
    if not target_norm:
        return False
    if candidate_norm == target_norm:
        return True
    start = 0
    while True:
        index = candidate_norm.find(target_norm, start)
        if index == -1:
            break
        end_index = index + len(target_norm)
        while end_index < len(candidate_norm) and candidate_norm[end_index].isspace():
            end_index += 1
        if end_index == len(candidate_norm) or candidate_norm[end_index] in "-–—:;,./()[]{}":
            return True
        start = index + 1
    return False


def _number_prefix(value: str) -> str | None:
    match = NUMBER_PREFIX_RE.match(_norm(value))
    if match:
        return match.group(1)
    return None


def _build_pages(lines):
    pages: Dict[int, List[Dict]] = {}
    for line in lines:
        pages.setdefault(int(line["page"]), []).append(line)
    for page, values in pages.items():
        values.sort(key=lambda item: int(item["line_in_page"]))
    return pages


def _match_on_page_exact(title: str, page_lines: List[Dict]) -> Tuple[bool, Dict | None]:
    if "\n" not in title:
        target = _norm(title)
        target_prefix = _number_prefix(title)
        for entry in page_lines:
            text = entry.get("text", "")
            if DOT_LEADERS_RE.search(text):
                continue
            if _contains_heading(text, target):
                return True, {
                    "found_page": int(entry.get("page", 0)),
                    "line_in_page": int(entry.get("line_in_page", 0)),
                    "matched_text": text,
                }
            if target_prefix and _number_prefix(text) == target_prefix:
                return True, {
                    "found_page": int(entry.get("page", 0)),
                    "line_in_page": int(entry.get("line_in_page", 0)),
                    "matched_text": text,
                }
        return False, None

    segments = title.split("\n")
    segment_count = len(segments)
    if segment_count == 0:
        return False, None
    total_lines = len(page_lines)
    for start in range(0, total_lines - segment_count + 1):
        window_lines = [page_lines[start + offset].get("text", "") for offset in range(segment_count)]
        if not window_lines:
            continue
        if DOT_LEADERS_RE.search(window_lines[0]):
            continue
        window = "\n".join(window_lines)
        if _equal_heading(window, title):
            anchor = page_lines[start]
            return True, {
                "found_page": int(anchor.get("page", 0)),
                "line_in_page": int(anchor.get("line_in_page", 0)),
                "matched_text": window,
            }
    return False, None


def _scan_order(hint_page: int | None, pages_sorted: List[int], band: int) -> List[int]:
    seen: set[int] = set()
    ordered: List[int] = []
    if hint_page:
        if hint_page in pages_sorted:
            ordered.append(hint_page)
            seen.add(hint_page)
        for delta in range(1, band + 1):
            lower = hint_page - delta
            upper = hint_page + delta
            if lower in pages_sorted and lower not in seen:
                ordered.append(lower)
                seen.add(lower)
            if upper in pages_sorted and upper not in seen:
                ordered.append(upper)
                seen.add(upper)
    for page in pages_sorted:
        if page not in seen:
            ordered.append(page)
    return ordered


def find_header_occurrences(session, document_id: int, llm_headers: List[Dict]) -> List[Dict]:
    band = int(os.getenv("HEADERS_MATCH_PAGE_BAND", "2") or 2)
    min_len = int(os.getenv("HEADERS_MATCH_MIN_TITLE_LEN", "4") or 4)
    use_calibration = os.getenv("HEADERS_MATCH_ENABLE_OFFSET_CALIBRATION", "1").lower() in {"1", "true", "yes", "on"}
    calibration_seed_min = int(os.getenv("HEADERS_MATCH_OFFSET_SEED_MIN", "3") or 3)

    lines = list(iter_lines(session, document_id))
    pages_map = _build_pages(lines)
    pages_sorted = sorted(pages_map.keys())

    matches: List[Dict] = []
    seeds: List[int] = []
    rows_for_log: List[Dict] = []

    for header in llm_headers:
        title = header.get("title", "")
        try:
            level = int(header.get("level", 1) or 1)
        except (TypeError, ValueError):
            level = 1
        try:
            expected_page = int(header.get("page", 0) or 0)
        except (TypeError, ValueError):
            expected_page = 0

        record = {
            "llm_title": title,
            "level": level,
            "expected_page": expected_page or None,
            "found": False,
            "found_page": None,
            "line_in_page": None,
            "matched_text": None,
            "reason": None,
            "page_scan_range": None,
        }

        if len(_norm(title)) < min_len:
            record["reason"] = "title_too_short"
            rows_for_log.append(record)
            matches.append(record)
            continue

        hint = expected_page if expected_page in pages_map else None
        scan_order = _scan_order(hint, pages_sorted, band)
        record["page_scan_range"] = scan_order

        for page in scan_order:
            ok, info = _match_on_page_exact(title, pages_map.get(page, []))
            if ok and info is not None:
                record.update(
                    {
                        "found": True,
                        "found_page": info["found_page"],
                        "line_in_page": info["line_in_page"],
                        "matched_text": info["matched_text"],
                    }
                )
                if expected_page:
                    seeds.append(info["found_page"] - expected_page)
                break

        if not record["found"]:
            record["reason"] = "no_exact_match_on_scanned_pages"

        rows_for_log.append(record)
        matches.append(record)

    if use_calibration and len(seeds) >= calibration_seed_min:
        offset = int(round(median(seeds)))
        updated_rows: List[Dict] = []
        for record, header in zip(matches, llm_headers):
            if record["found"]:
                updated_rows.append(record)
                continue
            title = header.get("title", "")
            try:
                expected_page = int(header.get("page", 0) or 0)
            except (TypeError, ValueError):
                expected_page = 0

            adjusted_hint = expected_page + offset if expected_page else None
            if adjusted_hint not in pages_map:
                adjusted_hint = None
            scan_order = _scan_order(adjusted_hint, pages_sorted, band)
            record["page_scan_range"] = scan_order

            for page in scan_order:
                ok, info = _match_on_page_exact(title, pages_map.get(page, []))
                if ok and info is not None:
                    record.update(
                        {
                            "found": True,
                            "found_page": info["found_page"],
                            "line_in_page": info["line_in_page"],
                            "matched_text": info["matched_text"],
                            "reason": "matched_after_offset",
                        }
                    )
                    break
            if not record["found"]:
                record["reason"] = "no_match_after_offset"
            updated_rows.append(record)
        rows_for_log = updated_rows

    log_dir = Path(os.getenv("HEADERS_LOG_DIR", "backend/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"header_matches_{document_id}.jsonl"
    with log_path.open("w", encoding="utf-8") as handle:
        for row in rows_for_log:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    return rows_for_log


__all__ = ["find_header_occurrences", "_match_on_page_exact"]
