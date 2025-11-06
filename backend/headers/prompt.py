"""Prompt builders for the hardened header extractor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Prompt:
    """Container describing the system/user prompt pair for the LLM."""

    system: str
    user: str
    label: str


_SYSTEM_PROMPT = """
You are SimpleSpecs, a contract structure extractor.

- Analyse the provided engineering specification pages.
- Identify the hierarchical table of contents style headings.
- Output only a single fenced code block labelled SIMPLEHEADERS that contains strict JSON.
- The JSON must be an array of objects with the keys: number (string|null), title (string), level (int), page (int|null).
- Every heading must be ordered as it appears in the document.
- If you cannot comply exactly, output the single token ABORT.
""".strip()


def _page_banner(chunk_index: int | None, chunk_total: int | None) -> str:
    if chunk_index is None or chunk_total is None:
        return "Document excerpt:"
    return f"Document excerpt (chunk {chunk_index}/{chunk_total}):"


def build_prompt(
    pages: Sequence[str],
    *,
    tighten: bool = False,
    chunk_index: int | None = None,
    chunk_total: int | None = None,
) -> Prompt:
    """Return the prompt pair for the supplied *pages*.

    ``tighten=True`` emphasises concision and re-iterates the schema to reduce
    hallucinated keys on retry attempts.
    """

    joined_pages = _join_pages(pages)
    label = "primary"
    if tighten and chunk_index is None:
        label = "tightened"
    elif chunk_index is not None:
        label = "chunk"

    guidance = [
        "The fence must be ```SIMPLEHEADERS and the closing fence must be ```.",
        "Do not include commentary before or after the fence.",
        "Return page numbers when present in the source, otherwise use null.",
        "Normalise numbering separators such as '1 - 2' into dotted form when obvious.",
    ]
    if tighten:
        guidance.extend(
            [
                "If any heading is ambiguous, still include it with your best numeric guess.",
                "Drop trailing punctuation from titles (., -, :, \\).",
            ]
        )

    prefix = _page_banner(chunk_index, chunk_total)
    user_lines = [prefix, joined_pages, "\n".join(guidance)]

    user_prompt = "\n\n".join(part for part in user_lines if part)

    return Prompt(system=_SYSTEM_PROMPT, user=user_prompt, label=label)


def _join_pages(pages: Iterable[str]) -> str:
    parts = []
    for index, page in enumerate(pages, start=1):
        page_text = str(page).strip()
        if not page_text:
            continue
        parts.append(f"[page {index}]\n{page_text}")
    return "\n\n".join(parts)


__all__ = ["Prompt", "build_prompt"]
