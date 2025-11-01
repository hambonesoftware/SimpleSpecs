from backend.services.vector_index import is_probably_toc


def test_detects_dot_leader_toc_entry() -> None:
    assert is_probably_toc("1. Scope.............12")


def test_detects_table_of_contents_phrase() -> None:
    assert is_probably_toc("Table of Contents")


def test_ignores_regular_heading() -> None:
    assert not is_probably_toc("1. Scope")
