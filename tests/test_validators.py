"""Validator unit tests."""
from __future__ import annotations

import pytest

from backend.spec_search.validators import ValidationError, validate_schema

BUCKETS = ["mechanical", "electrical", "software", "controls"]


def test_reject_json_array_payload() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_schema("```json\n[]```", BUCKETS)
    assert exc.value.reason == "bad_label_or_shape"

    with pytest.raises(ValidationError) as exc2:
        validate_schema("json []", BUCKETS)
    assert exc2.value.reason == "bad_label_or_shape"


def test_reject_prose_response() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_schema("Just some words about requirements.", BUCKETS)
    assert exc.value.reason == "missing_fence"


def test_accept_valid_empty_payload() -> None:
    payload = """```SIMPLEBUCKETS\n{\n  \"mechanical\": {\"requirements\": []},\n  \"electrical\": {\"requirements\": []},\n  \"software\": {\"requirements\": []},\n  \"controls\": {\"requirements\": []}\n}\n```"""
    result = validate_schema(payload, BUCKETS)
    for bucket in BUCKETS:
        assert bucket in result
        assert result[bucket].requirements == []
