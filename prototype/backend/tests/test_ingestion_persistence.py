from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import IngestEventRequest, persist_event_and_evidence
from app.models import EvidenceRecord, IngestionEvent


def test_ingestion_persists_parent_before_linked_evidence_and_is_idempotent():
    event_id = f"evt-fk-regression-{uuid.uuid4().hex}"
    organization_id = f"org-fk-regression-{uuid.uuid4().hex}"
    payload = {
        "event_id": event_id,
        "event_type": "PREFERENCE_UPDATED",
        "event_time": "2026-10-03T10:00:00+00:00",
        "observed_time": "2026-10-03T10:00:01+00:00",
        "source_system": "fk-regression-test",
        "organization_id": organization_id,
        "person_ref": f"person-{uuid.uuid4().hex}",
        "purpose": "MARKETING",
        "payload": {"preference": "opted_out"},
    }

    event = IngestEventRequest.model_validate(payload)
    created, _, status = persist_event_and_evidence(event, str(uuid.uuid4()))
    assert status == "OK"
    evidence_id = created["evidence_id"]

    with SessionLocal() as db:
        event_rows = db.execute(
            select(func.count()).select_from(IngestionEvent).where(
                IngestionEvent.event_id == event_id,
                IngestionEvent.organization_id == organization_id,
            )
        ).scalar_one()
        evidence_rows = db.execute(
            select(EvidenceRecord).where(
                EvidenceRecord.source_event_id == event_id,
                EvidenceRecord.organization_id == organization_id,
            )
        ).scalars().all()

    assert event_rows == 1
    assert len(evidence_rows) == 1
    assert evidence_rows[0].evidence_id == evidence_id
    assert evidence_rows[0].source_event_id == event_id

    duplicate, _, duplicate_status = persist_event_and_evidence(event, str(uuid.uuid4()))
    assert duplicate_status == "DUPLICATE"
    assert duplicate["idempotent"] is True
    assert duplicate["evidence_id"] == evidence_id

    with SessionLocal() as db:
        event_rows_after_retry = db.execute(
            select(func.count()).select_from(IngestionEvent).where(
                IngestionEvent.event_id == event_id,
                IngestionEvent.organization_id == organization_id,
            )
        ).scalar_one()
        evidence_rows_after_retry = db.execute(
            select(func.count()).select_from(EvidenceRecord).where(
                EvidenceRecord.source_event_id == event_id,
                EvidenceRecord.organization_id == organization_id,
            )
        ).scalar_one()

    assert event_rows_after_retry == 1
    assert evidence_rows_after_retry == 1
