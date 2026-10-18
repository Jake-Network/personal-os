from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from app.modules.career.career_manager import career_manager as manager
from app.schema.career_schema import CareerRecordCreate as Create, period_bounds


def test_career_hierarchy_multi_year_precision_and_skills(session):
    employment = manager.save(session, Create(kind="employment", title="회사 재직", company="합성 회사", started_on="2023"))
    project = manager.save(session, Create(kind="project", parent_id=employment.id, title="플랫폼", started_on="2023-07", ended_on="2025-02"))
    contribution = manager.save(session, Create(kind="contribution", parent_id=project.id, title="캐시 설계", started_on="2024", skills=["Python", "Python"]))
    achievement = manager.save(session, Create(kind="achievement", parent_id=contribution.id, title="지연 개선", outcome="팀 측정 결과, 본인 기여는 캐시 설계"))
    evidence = manager.save(session, Create(kind="evidence", parent_id=achievement.id, title="측정 보고서", evidence_url="https://example.test/report"))
    assert contribution.skills == ["Python"]
    assert {r.id for r in manager.list(session, company="합성 회사")} == {employment.id, project.id, contribution.id, achievement.id, evidence.id}
    assert {r.id for r in manager.list(session, project_id=project.id)} == {project.id, contribution.id, achievement.id, evidence.id}
    assert [r.id for r in manager.list(session, skill="Python")] == [contribution.id]
    timeline = manager.timeline(session, start=date(2024, 1, 1), end=date(2025, 1, 1), domain="career")
    assert {r.source_id for r in timeline.items} == {employment.id, project.id, contribution.id}
    assert next(r for r in timeline.items if r.source_id == contribution.id).occurred_on == "2024"
    assert project.started_on == "2023-07"
    with pytest.raises(ValueError):
        manager.delete(session, project.id)


def test_extraction_is_draft_and_needs_explicit_confirmation(session):
    record = manager.save(session, Create(kind="achievement", title="추출한 성과", source="advisor"))
    assert record.status == "draft"
    assert record.share_with_advisor is False
    manager.confirm(session, record.id)
    assert record.status == "confirmed"
    record = manager.save(session, Create(kind="achievement", title="다시 추출한 성과", source="advisor"), record.id)
    assert record.status == "draft"


def test_invalid_relationship_dates_and_urls(session):
    employment = manager.save(session, Create(kind="employment", title="재직"))
    with pytest.raises(ValueError):
        manager.save(session, Create(kind="evidence", title="근거", parent_id=employment.id))
    with pytest.raises(LookupError):
        manager.save(session, Create(kind="project", title="프로젝트", parent_id=9999))
    with pytest.raises(LookupError):
        manager.save(session, Create(kind="achievement", title="출처", source_message_id=9999))
    for invalid in ["2024-13", "2023-02-29", "24", "2024-1", "2024-01-1"]:
        with pytest.raises((ValidationError, ValueError)):
            Create(kind="project", title="검증", started_on=invalid)
    with pytest.raises(ValidationError):
        Create(kind="project", title="역전", started_on="2025", ended_on="2024")
    with pytest.raises(ValidationError):
        Create(kind="evidence", title="악성", evidence_url="javascript:alert(1)")
    assert period_bounds("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))


def test_timeline_derived_from_original_changes(session):
    record = manager.save(session, Create(kind="project", title="원본", started_on="2024", ended_on="2024"))
    assert manager.timeline(session).items[0].title == "원본"
    manager.save(session, Create(kind="project", title="수정 원본", started_on="2024", ended_on="2024"), record.id)
    assert manager.timeline(session).items[0].title == "수정 원본"
    assert manager.timeline(session, start=date(2025, 1, 1)).total == 0
    manager.delete(session, record.id)
    assert manager.timeline(session).total == 0


def test_career_migration_preserves_legacy_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'career-migration.sqlite'}")
    cfg = Config("alembic.ini")
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0007_document_job_attempts")
        connection.execute(text("INSERT INTO personal_memories (kind, content, status, source, created_at) VALUES ('profile', 'synthetic legacy fact', 'confirmed', 'user', '2024-01-01')"))
        command.upgrade(cfg, "0008_career_records")
        assert "career_records" in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT content FROM personal_memories")) == "synthetic legacy fact"
        command.downgrade(cfg, "0007_document_job_attempts")
        assert "career_records" not in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT COUNT(*) FROM personal_memories")) == 1
    engine.dispose()


def test_career_api_and_timeline_contract(client):
    created = client.post("/api/career/records", json={"kind": "employment", "title": "합성 재직", "started_on": "2022", "company": "회사"})
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["share_with_advisor"] is False
    assert row["recorded_at"].endswith("Z") or "+00:00" in row["recorded_at"]
    assert client.get("/api/career/records").json()[0]["id"] == row["id"]
    timeline = client.get("/api/timeline", params={"start": "2023-01-01", "end": "2024-01-01", "domain": "career"})
    assert timeline.status_code == 200, timeline.text
    assert timeline.json()["items"][0]["occurred_on"] == "2022"
    assert client.get("/api/timeline", params={"start": "2024-01-01", "end": "2023-01-01"}).status_code == 422
    assert client.post("/api/career/records", json={"kind": "project", "title": "오류", "started_on": "2023-02-30"}).status_code == 422


def test_career_payload_and_revocation_propagates_history(session, fake_provider):
    import asyncio
    import json
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.types import AskOptions
    from app.enums.context_category import Category
    from app.modules.advisor.memory_history_manager import source_allowed

    shared = manager.save(session, Create(kind="achievement", title="공유된 합성 성과", outcome="캐시 설계", share_with_advisor=True))
    private = manager.save(session, Create(kind="achievement", title="로컬 전용 비밀 성과"))
    draft = manager.save(session, Create(kind="achievement", title="미확인 비밀 초안", source="advisor", share_with_advisor=True))
    conversation = advisor_manager.create_conversation(session, "커리어 상담")
    async def ask(text):
        return [event async for event in advisor_manager.ask(session, conversation, text, AskOptions(categories=frozenset({Category.CAREER})))]
    events = asyncio.run(ask("내 경력과 프로젝트를 정리해줘"))
    assert events[-1]["type"] == "done", events
    sent = json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
    assert shared.title in sent
    assert private.title not in sent and draft.title not in sent
    context_event = next(event for event in events if event["type"] == "context")
    assert any(ref["table"] == "career_records" and ref["id"] == shared.id for ref in context_event["record_references"])
    shared.share_with_advisor = False
    session.commit()
    assert not source_allowed(session, [{"table": "career_records", "id": shared.id}])
    events = asyncio.run(ask("같은 경력을 다시 정리해줘"))
    assert events[-1]["type"] == "done", events
    assert shared.title not in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)


def test_career_ancestor_sharing_restriction(session):
    from app.modules.advisor.memory_history_manager import source_allowed
    parent = manager.save(session, Create(kind="project", title="로컬 프로젝트"))
    child = manager.save(session, Create(kind="achievement", parent_id=parent.id, title="외부 공유 후보", share_with_advisor=True))
    assert not source_allowed(session, [{"table": "career_records", "id": child.id}])
    parent.share_with_advisor = True
    session.commit()
    assert source_allowed(session, [{"table": "career_records", "id": child.id}])


def test_deleted_document_cannot_reenable_derived_career_record(session):
    from app.modules.database.model import Document, DocumentVersion
    from app.modules.advisor.memory_history_manager import source_allowed
    document = Document(title="합성 근거", categories=["career"], sharing_enabled=True)
    session.add(document)
    session.flush()
    version = DocumentVersion(document_id=document.id, filename="evidence.txt", content_hash="0" * 64, content=b"synthetic", status="ready")
    session.add(version)
    session.flush()
    document.active_version_id = version.id
    session.commit()
    record = manager.save(session, Create(kind="achievement", title="문서 파생 성과", source="document",
        source_document_version_id=version.id, share_with_advisor=True))
    manager.confirm(session, record.id)
    assert source_allowed(session, [{"table": "career_records", "id": record.id}])
    original_references = list(record.source_references)
    session.delete(version)
    session.commit()
    session.expire_all()
    assert record.source_references == original_references
    assert not source_allowed(session, [{"table": "career_records", "id": record.id}])


def test_deleted_career_id_not_reused(session):
    row = manager.save(session, Create(kind="achievement", title="이전 성과", share_with_advisor=True))
    previous_id = row.id
    manager.delete(session, row.id)
    replacement = manager.save(session, Create(kind="achievement", title="새 성과", share_with_advisor=True))
    assert replacement.id > previous_id


def test_project_keyword_does_not_match_inside_unrelated_document_title():
    from app.modules.context.routing import context_router
    from app.enums.context_category import Category
    assert Category.CAREER in context_router.route("내 프로젝트를 정리해줘").selected
    assert Category.CAREER not in context_router.route("업로드한 자료에서 비밀프로젝트 찾아줘").selected


def test_decision_timeline_occurrence_uses_application_timezone(session, monkeypatch):
    from datetime import UTC, datetime
    from app.config import settings
    from app.modules.database.model.advisor import DecisionJournalEntry
    from dataclasses import replace
    monkeypatch.setattr("app.modules.career.career_manager.settings", replace(settings, timezone="Asia/Seoul"))
    entry = DecisionJournalEntry(title="합성 자정 결정", choice="선택", rationale="근거",
        decided_at=datetime(2024, 3, 31, 23, 30, tzinfo=UTC))
    session.add(entry)
    session.commit()
    timeline = manager.timeline(session, domain="decisions", start=date(2024, 4, 1), end=date(2024, 5, 1))
    assert len(timeline.items) == 1
    assert timeline.items[0].occurred_on == "2024-04-01"
