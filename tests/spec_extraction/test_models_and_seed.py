from __future__ import annotations

from sqlmodel import Session, delete, select

from backend.spec_extraction import get_engine, init_db
from backend.spec_extraction.models import Agent, Document, Section


def test_agent_seed_and_models(monkeypatch) -> None:
    init_db()
    with Session(get_engine()) as session:
        session.exec(delete(Agent))
        session.commit()

    init_db()
    with Session(get_engine()) as session:
        agents = session.exec(select(Agent)).all()
        codes = {agent.code for agent in agents}
        assert codes == {"Mechanical"}

        document = Document(id="doc-1", filename="sample.pdf")
        session.add(document)
        session.commit()

        section = Section(
            document_id=document.id,
            title="1 Scope",
            page_start=1,
            page_end=2,
            start_global_idx=0,
            end_global_idx=5,
        )
        session.add(section)
        session.commit()

        stored = session.exec(select(Section).where(Section.document_id == document.id)).one()
        assert stored.title == "1 Scope"
        assert stored.status == "pending"
