from sqlmodel import SQLModel, Session, create_engine, select

from backend.models import Document, DocumentArtifactType, DocumentPage, DocumentTable
from backend.services.artifact_store import (
    PARSER_VERSION,
    get_cached_artifact,
    get_cached_parse_payload,
    persist_parse_result,
    store_artifact,
)
from backend.services.pdf_native import ParsedBlock, ParsedPage, ParsedTable, ParseResult


def _make_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_persist_parse_result_stores_pages_and_tables() -> None:
    session = _make_session()
    with session:
        document = Document(filename="doc.pdf", checksum="abc")
        session.add(document)
        session.commit()
        session.refresh(document)

        parse_result = ParseResult(
            pages=[
                ParsedPage(
                    page_number=0,
                    width=100.0,
                    height=200.0,
                    blocks=[
                        ParsedBlock(
                            text="Heading",
                            bbox=(0.0, 0.0, 10.0, 10.0),
                            font="Arial",
                            font_size=12.0,
                        )
                    ],
                    tables=[
                        ParsedTable(
                            page_number=0,
                            bbox=(1.0, 2.0, 3.0, 4.0),
                            flavor="stream",
                            accuracy=0.87,
                        )
                    ],
                )
            ],
            has_ocr=True,
            used_mineru=False,
        )

        persist_parse_result(session=session, document=document, parse_result=parse_result)

        stored_pages = session.exec(select(DocumentPage)).all()
        stored_tables = session.exec(select(DocumentTable)).all()
        refreshed = session.get(Document, document.id)
        cached_payload = get_cached_parse_payload(session=session, document=document)

        assert len(stored_pages) == 1
        assert stored_pages[0].text_raw.strip() == "Heading"
        assert stored_pages[0].is_toc is False
        assert len(stored_tables) == 1
        assert refreshed is not None
        assert refreshed.page_count == 1
        assert refreshed.has_ocr is True
        assert refreshed.parser_version == PARSER_VERSION
        assert cached_payload is not None
        assert cached_payload["has_ocr"] is True
        assert cached_payload["pages"][0]["blocks"][0]["text"] == "Heading"


def test_store_artifact_reuses_existing_entry() -> None:
    session = _make_session()
    with session:
        document = Document(filename="doc.pdf", checksum="def")
        session.add(document)
        session.commit()
        session.refresh(document)

        inputs = {"doc_hash": "123", "parser_version": PARSER_VERSION}

        first = store_artifact(
            session=session,
            document_id=document.id,
            artifact_type=DocumentArtifactType.HEADER_TREE,
            key="llm_full",
            inputs=inputs,
            body={"headers": []},
        )

        again = store_artifact(
            session=session,
            document_id=document.id,
            artifact_type=DocumentArtifactType.HEADER_TREE,
            key="llm_full",
            inputs=inputs,
            body={"headers": [1]},
        )

        fetched = get_cached_artifact(
            session=session,
            document_id=document.id,
            artifact_type=DocumentArtifactType.HEADER_TREE,
            key="llm_full",
            inputs=inputs,
        )

        assert first.id == again.id
        assert fetched is not None
        assert fetched.id == first.id
        assert fetched.body.get("headers") == []

