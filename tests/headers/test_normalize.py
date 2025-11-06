from __future__ import annotations

from backend.headers.models import HeaderItem
from backend.headers.normalize import normalize_headers


def make_item(number: str | None, title: str, **meta) -> HeaderItem:
    item = HeaderItem(number=number, title=title, level=1, page=1, order=0)
    item.meta.update(meta)
    return item


def test_confusables_and_duplicates_are_normalised() -> None:
    headers = [
        make_item("I", "SCOPE"),
        make_item("1", "Scope"),
        make_item("1.1", "Purpose"),
        make_item("1.1", "Purpose"),
    ]
    cleaned = normalize_headers(headers)
    numbers = [item.number for item in cleaned]
    assert numbers == ["1", "1.1"]


def test_running_headers_removed_when_flagged() -> None:
    headers = [
        make_item("1", "Scope"),
        make_item("2", "Running Header", running=True),
    ]
    cleaned = normalize_headers(headers, suppress_running=True)
    titles = [item.title for item in cleaned]
    assert titles == ["Scope"]
