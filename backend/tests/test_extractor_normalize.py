from backend.services.extractors._normalize import normalize_numeric_artifacts


def test_numeric_normalization_collapse_and_confusable() -> None:
    value = "1 \u00A0. I Scope\n2  . 1  . 3  Title"
    result = normalize_numeric_artifacts(value)
    assert "1.1 Scope" in result
    assert "2 . 1 . 3" not in result
    assert "2.1.3" in result
