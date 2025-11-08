from sqlmodel import Session, select

from backend.spec_extraction import get_engine
from backend.spec_extraction.jobs import persist_sections
from backend.spec_extraction.models import Header, Section


def test_persist_sections_records_headers() -> None:
    """Headers should be persisted and associated with their sections."""

    sections = [
        {
            "header_text": "1 Scope",
            "start_page": 1,
            "end_page": 2,
            "start_global_idx": 0,
            "end_global_idx": 4,
        },
        {
            "header_text": "2 Requirements",
            "start_page": 3,
            "end_page": 5,
            "start_global_idx": 5,
            "end_global_idx": 9,
        },
    ]
    headers = [
        {
            "text": "1 Scope",
            "number": "1",
            "level": 1,
            "page": 1,
            "line_idx": 10,
            "global_idx": 0,
        },
        {
            "text": "2 Requirements",
            "number": "2",
            "level": 1,
            "page": 3,
            "line_idx": 2,
            "global_idx": 5,
        },
    ]

    persist_sections(
        document_id="hdr-1",
        filename="doc.pdf",
        sections=sections,
        headers=headers,
    )

    with Session(get_engine()) as session:
        stored_sections = session.exec(
            select(Section).where(Section.document_id == "hdr-1")
        ).all()
        starts = {section.start_global_idx: section.id for section in stored_sections}
        stored_headers = session.exec(
            select(Header).where(Header.document_id == "hdr-1").order_by(Header.global_idx)
        ).all()
        assert len(stored_headers) == 2
        assert stored_headers[0].title == "1 Scope"
        assert stored_headers[0].section_id == starts.get(0)
        assert stored_headers[1].section_id == starts.get(5)

    updated_headers = [
        {
            "text": "1 Scope",
            "number": "1",
            "level": 1,
            "page": 1,
            "line_idx": 15,
            "global_idx": 0,
        }
    ]

    persist_sections(
        document_id="hdr-1",
        filename="doc.pdf",
        sections=sections,
        headers=updated_headers,
    )

    with Session(get_engine()) as session:
        stored_headers = session.exec(
            select(Header).where(Header.document_id == "hdr-1")
        ).all()
        assert len(stored_headers) == 1
        assert stored_headers[0].line_idx == 15
        assert stored_headers[0].section_id is not None
