from backend.services.extractors._normalize import (
    score_confusable_one_ratio,
    score_spaced_dots_ratio,
)


def test_noise_scoring_thresholds() -> None:
    text = "1 . I Scope 2 . 1 . 3 Title 3 . 4 Aux"
    assert score_spaced_dots_ratio(text) >= 0.01
    assert score_confusable_one_ratio(text) >= 0.01
