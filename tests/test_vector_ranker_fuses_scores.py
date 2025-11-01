from __future__ import annotations

import numpy as np

from backend.services.vector_index import LineWindow, score_candidates


def _window(global_idx: int, text: str) -> LineWindow:
    return LineWindow(
        text=text,
        tokens=text.lower().split(),
        page=1,
        start_line_id=global_idx,
        end_line_id=global_idx,
        start_line_idx=global_idx,
        end_line_idx=global_idx,
        y_top=None,
        font_max=None,
        is_toc=False,
        is_index=False,
        is_running=False,
    )


def test_vector_ranker_prefers_high_fused_score() -> None:
    windows = [_window(5, "Safety Requirements"), _window(10, "Safety Overview")]
    window_embeddings = np.array(
        [
            [0.8, 0.2],
            [0.1, 0.9],
        ],
        dtype=np.float32,
    )
    header_embedding = np.array([0.85, 0.15], dtype=np.float32)

    candidates = score_candidates(
        "Safety Requirements",
        1,
        windows,
        window_embeddings,
        header_embedding,
        weights=(0.5, 0.5, 0.0, 0.0),
        thresholds=(0.0, 0.0),
        prefer_last=False,
    )

    assert candidates, "expected scored candidates"
    chosen = candidates[0]
    assert chosen.window.start_line_id == 5
    assert chosen.fused > candidates[1].fused
