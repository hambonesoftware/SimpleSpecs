"""Specification extraction service for classifying requirements by discipline."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ..config import DEFAULT_TERMS_DIR, Settings
from .llm import LLMCircuitOpenError, LLMProviderError, LLMService
from .pdf_native import ParseResult

LOGGER = logging.getLogger(__name__)

LINE_BREAK_RE = re.compile(r"[\r\n]+")
HEADER_NUMBER_RE = re.compile(
    r"^(?P<number>(?:\d+|[A-Z])(?:[.][\dA-Z]+)*)[.)]?\s+(?P<title>.+)$"
)
WORD_RE = re.compile(r"\w+")


@dataclass(slots=True)
class TermLexicon:
    """Term lexicon describing seed keywords for a discipline."""

    discipline: str
    terms: tuple[str, ...]
    boost_terms: tuple[str, ...] = tuple()
    term_patterns: tuple[re.Pattern[str], ...] = field(init=False)
    boost_patterns: tuple[re.Pattern[str], ...] = field(init=False)

    def __post_init__(self) -> None:
        self.term_patterns = tuple(_compile_term(term) for term in self.terms)
        self.boost_patterns = tuple(_compile_term(term) for term in self.boost_terms)

    def score(self, text: str) -> float:
        """Return a score based on keyword matches within the text."""

        score = 0.0
        for pattern in self.term_patterns:
            if pattern.search(text):
                score += 1.0
        for pattern in self.boost_patterns:
            if pattern.search(text):
                score += 1.5
        return score


@dataclass(slots=True)
class SpecLine:
    """Atomic specification line with provenance and classification metadata."""

    text: str
    page: int
    header_path: tuple[str, ...]
    disciplines: tuple[str, ...]
    scores: Mapping[str, float]
    source: str
    block_index: int
    line_index: int
    bbox: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict:
        """Return a serialisable representation of the spec line."""

        return {
            "text": self.text,
            "page": self.page,
            "header_path": list(self.header_path),
            "disciplines": list(self.disciplines),
            "scores": dict(self.scores),
            "source": self.source,
            "provenance": {
                "page": self.page,
                "block_index": self.block_index,
                "line_index": self.line_index,
                "bbox": list(self.bbox) if self.bbox is not None else None,
            },
        }


@dataclass(slots=True)
class SpecExtractionResult:
    """Result container aggregating spec lines by discipline."""

    lines: list[SpecLine]
    disciplines: tuple[str, ...]
    unknown_label: str = "unknown"

    def to_dict(self) -> dict[str, list[dict]]:
        """Return the result grouped per discipline plus an unknown bucket."""

        buckets: dict[str, list[dict]] = {
            discipline: [] for discipline in self.disciplines
        }
        buckets[self.unknown_label] = []

        for line in self.lines:
            if line.disciplines:
                for discipline in line.disciplines:
                    buckets.setdefault(discipline, []).append(line.to_dict())
            else:
                buckets[self.unknown_label].append(line.to_dict())

        # Ensure every known discipline key exists even if empty
        for discipline in self.disciplines:
            buckets.setdefault(discipline, [])
        if self.unknown_label not in buckets:
            buckets[self.unknown_label] = []
        return buckets

    def iter_by_discipline(self, discipline: str) -> Iterable[SpecLine]:
        """Yield all lines assigned to a given discipline."""

        target = discipline.lower()
        for line in self.lines:
            if target in (disc.lower() for disc in line.disciplines):
                yield line


class SpecLLMClient:
    """LLM-driven classifier for ambiguous specification lines."""

    def __init__(
        self,
        settings: Settings,
        llm_service: LLMService | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm_service or LLMService(settings)

    @property
    def is_enabled(self) -> bool:
        return self._llm.is_enabled

    def classify(
        self,
        text: str,
        header_path: tuple[str, ...],
        scores: Mapping[str, float],
        *,
        candidates: Sequence[str] | None = None,
    ) -> list[str] | None:
        """Return LLM-provided disciplines if available."""

        if not self.is_enabled:
            return None

        prompt_lines = [
            "Classify the following specification line by discipline.",
            "Return a JSON array of discipline labels inside #classes# fences.",
            "Recognised disciplines: mechanical, electrical, controls, software, project_management.",
            f"Line: {text}",
        ]
        if header_path:
            prompt_lines.append(f"Header path: {' > '.join(header_path)}")
        if candidates:
            prompt_lines.append(f"Rule candidates: {', '.join(candidates)}")
        prompt_lines.append(f"Term scores: {json.dumps(scores, ensure_ascii=False)}")
        prompt = "\n".join(prompt_lines)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a quality engineer who assigns specification disciplines. "
                    "Respond ONLY with a JSON array enclosed in #classes# fences."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            result = self._llm.generate(
                messages=messages,
                fence="#classes#",
                metadata={"task": "spec-classification"},
            )
        except (
            LLMCircuitOpenError,
            LLMProviderError,
        ) as exc:  # pragma: no cover - network path
            LOGGER.warning("Specification classification LLM failed: %s", exc)
            return None

        fenced = result.fenced or result.content
        try:
            parsed = json.loads(fenced)
        except json.JSONDecodeError:
            return None

        labels: list[str] = []
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str) and item.strip():
                    labels.append(item.strip())
                elif isinstance(item, Mapping):
                    label = item.get("label") or item.get("discipline")
                    if isinstance(label, str) and label.strip():
                        labels.append(label.strip())
        elif isinstance(parsed, Mapping):
            candidates_list = parsed.get("disciplines")
            if isinstance(candidates_list, list):
                for value in candidates_list:
                    if isinstance(value, str) and value.strip():
                        labels.append(value.strip())

        if not labels:
            return None

        seen: set[str] = set()
        ordered: list[str] = []
        for label in labels:
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(label)
        return ordered or None


def extract_specifications(
    parse_result: ParseResult,
    *,
    settings: Settings,
    llm_client: SpecLLMClient | None = None,
    terms_dir: Path | None = None,
) -> SpecExtractionResult:
    """Extract and classify specification lines from a parsed document."""

    if llm_client is None:
        llm_client = SpecLLMClient(settings)
    lexicons = _load_lexicons(terms_dir or settings.spec_terms_dir)
    tracker = _HeaderTracker()
    lines: list[SpecLine] = []

    for page in parse_result.pages:
        for block_index, block in enumerate(page.blocks):
            raw_lines = _split_block(block.text)
            for line_index, raw_line in enumerate(raw_lines):
                if tracker.consume_header(raw_line):
                    continue
                cleaned_line = _normalise_spec_line(raw_line)
                if not cleaned_line or len(cleaned_line) < 3:
                    continue
                disciplines, scores, source = _classify_line(
                    cleaned_line,
                    lexicons,
                    settings,
                    llm_client,
                    tracker.path,
                )
                spec_line = SpecLine(
                    text=cleaned_line,
                    page=page.page_number,
                    header_path=tracker.path,
                    disciplines=tuple(disciplines),
                    scores=scores,
                    source=source,
                    block_index=block_index,
                    line_index=line_index,
                    bbox=getattr(block, "bbox", None),
                )
                lines.append(spec_line)

    available_disciplines = tuple(lexicon.discipline for lexicon in lexicons)
    return SpecExtractionResult(lines=lines, disciplines=available_disciplines)


def _split_block(text: str) -> list[str]:
    """Split a block of text into candidate lines."""

    if not text:
        return []
    text = text.replace("•", "\n").replace("\u2022", "\n")
    raw_lines = LINE_BREAK_RE.split(text)
    lines = [line.strip() for line in raw_lines if line.strip()]
    return lines


def _normalise_spec_line(line: str) -> str:
    """Remove bullets, numbering, and collapse whitespace for spec lines."""

    stripped = line.strip()
    stripped = re.sub(r"^[\-–—*]+\s*", "", stripped)
    stripped = re.sub(r"^(?:\(?\d+[A-Za-z]?\)|\d+[.)]|[A-Za-z]\))\s+", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip()


def _compile_term(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.strip())
    if WORD_RE.search(term):
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def _looks_like_header(line: str, *, had_trailing_colon: bool = False) -> bool:
    if not line:
        return False
    words = line.split()
    if had_trailing_colon:
        return True
    if len(words) <= 8 and line.isupper():
        return True
    if len(words) <= 6 and all(word[:1].isupper() for word in words if word):
        return True
    match = HEADER_NUMBER_RE.match(line)
    if match:
        title = match.group("title")
        title_words = title.split()
        if title_words and all(word[:1].isupper() for word in title_words if word):
            return True
    return False


class _HeaderTracker:
    """Maintain the current header path while iterating text blocks."""

    def __init__(self) -> None:
        self._stack: list[str] = []

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self._stack)

    def consume_header(self, line: str) -> bool:
        candidate = _normalise_header(line)
        if candidate is None:
            return False
        level = _infer_header_level(candidate)
        while len(self._stack) >= level:
            self._stack.pop()
        self._stack.append(candidate)
        return True


def _normalise_header(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    had_colon = stripped.endswith(":")
    if had_colon:
        stripped = stripped[:-1]
    stripped = re.sub(r"\s+", " ", stripped)
    if not _looks_like_header(stripped, had_trailing_colon=had_colon):
        return None
    return stripped


def _infer_header_level(header: str) -> int:
    match = HEADER_NUMBER_RE.match(header)
    if not match:
        return 1
    numbering = match.group("number")
    if not numbering:
        return 1
    segments = [segment for segment in numbering.replace(" ", "").split(".") if segment]
    return max(1, len(segments))


def _classify_line(
    text: str,
    lexicons: Sequence[TermLexicon],
    settings: Settings,
    llm_client: SpecLLMClient | None,
    header_path: tuple[str, ...],
) -> tuple[list[str], dict[str, float], str]:
    """Classify a line using rule-based scores with optional LLM tie-breaker."""

    lowered = text.lower()
    scores = {lexicon.discipline: lexicon.score(lowered) for lexicon in lexicons}
    top_score = max(scores.values()) if scores else 0.0
    min_hits = max(settings.spec_rule_min_hits, 0)
    margin = max(settings.spec_multi_label_margin, 0.0)

    disciplines: list[str] = []
    source = "rule"

    if top_score >= min_hits:
        disciplines = [
            discipline
            for discipline, score in scores.items()
            if score > 0 and top_score - score <= margin
        ]

    if llm_client and llm_client.is_enabled:
        should_call_llm = False
        if not disciplines and any(score > 0 for score in scores.values()):
            should_call_llm = True
        elif len(disciplines) > 1:
            should_call_llm = True

        if should_call_llm:
            candidates = disciplines or [
                discipline for discipline, score in scores.items() if score > 0
            ]
            llm_result = llm_client.classify(
                text, header_path, scores, candidates=candidates
            )
            if llm_result:
                disciplines = list(llm_result)
                source = "llm"

    return disciplines, scores, source


@lru_cache(maxsize=1)
def _load_lexicons(path: Path) -> tuple[TermLexicon, ...]:
    """Load and cache term lexicons from JSON files."""

    if not path.exists():
        LOGGER.warning(
            "Spec terms directory %s missing; using default %s", path, DEFAULT_TERMS_DIR
        )
        path = DEFAULT_TERMS_DIR
    lexicons: list[TermLexicon] = []
    for json_path in sorted(path.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - configuration error
            LOGGER.error("Invalid JSON in %s: %s", json_path, exc)
            continue
        discipline = data.get("discipline")
        terms = tuple(item.strip() for item in data.get("terms", []) if item.strip())
        boost_terms = tuple(
            item.strip() for item in data.get("boost_terms", []) if item.strip()
        )
        if not discipline or not terms:
            LOGGER.warning(
                "Skipping lexicon %s due to missing discipline/terms", json_path
            )
            continue
        lexicons.append(
            TermLexicon(discipline=discipline, terms=terms, boost_terms=boost_terms)
        )

    if not lexicons:
        raise RuntimeError("No specification term lexicons available")

    return tuple(lexicons)


__all__ = [
    "SpecExtractionResult",
    "SpecLine",
    "SpecLLMClient",
    "TermLexicon",
    "extract_specifications",
]
