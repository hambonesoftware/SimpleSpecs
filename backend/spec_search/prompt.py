"""Prompt templates for the spec-search extractor."""
from __future__ import annotations

from typing import Iterable

BUCKET_DEFINITIONS = {
    "mechanical": "installation, materials, calibration/markings, physical interfaces, enclosures, mechanical fit",
    "electrical": "power, wiring, ratings, safety classes, EMI/EMC",
    "software": "firmware, updates, diagnostics, data formats, storage, logs",
    "controls": "control algorithms, tuning, setpoints, interlocks, safety logic, HMI behavior",
}

SYSTEM_PROMPT = (
    "You are extracting compliance requirements from technical specifications. "
    "Output only a single fenced code block labeled SIMPLEBUCKETS containing valid JSON "
    "matching the required schema. No prose before or after. If you cannot comply, output "
    "exactly the single token ABORT."
)

USER_PROMPT_TEMPLATE = """
You will receive raw technical specification text. Extract normative requirements and group
them into the requested buckets.

Buckets and their focus areas:
{bucket_table}

Map requirement levels as follows:
- Words like "shall", "must", "required" -> level MUST
- Words like "should", "recommended" -> level SHOULD
- Words like "may", "can", "optional" -> level MAY

Ignore tables of contents, running headers or footers, and any marketing language.

Return exactly one fenced code block labeled SIMPLEBUCKETS that matches the schema:
{{
  "<bucket>": {{ "requirements": [ {{ "text": "...", "level": "MUST|SHOULD|MAY", "page_hint": 12 }} ] }}
}}

Specification text:
\"\"\"{text}\"\"\"
"""


def build_user_prompt(text: str, buckets: Iterable[str]) -> str:
    """Render the user prompt for the provided snippet and bucket list."""

    lines = []
    for bucket in buckets:
        description = BUCKET_DEFINITIONS.get(bucket, "(no definition provided)")
        lines.append(f"- {bucket.title()}: {description}")
    bucket_table = "\n".join(lines)
    return USER_PROMPT_TEMPLATE.format(text=text, bucket_table=bucket_table)
