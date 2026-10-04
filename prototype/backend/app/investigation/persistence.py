from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import SessionLocal
from app.investigation.engine import get_latest_withdrawal, normalize_purpose, run_investigation
from app.models import EvidenceRecord, IngestionEvent, InvestigationScope as PersistedInvestigationScope
from app.neo4j_client import neo4j_client

FACT_TABLES = (
    "users",
    "consent_events",
    "systems",
    "datasets",
    "lineage",
    "processing_logs",
    "audience_membership",
    "export_logs",
    "processor_acknowledgements",
    "exceptions",
    "identity_mappings",
)


def load_persisted_dataset(organization_id: str, person_ref: str, purpose: str) -> dict[str, list[dict[str, Any]]]:
    effective_purpose = normalize_purpose(purpose)
    with SessionLocal() as db:
        events = db.execute(
            select(IngestionEvent)
            .where(
                IngestionEvent.organization_id == organization_id,
                IngestionEvent.person_ref == person_ref,
                IngestionEvent.purpose == effective_purpose,
            )
            .order_by(IngestionEvent.event_time, IngestionEvent.event_id)
        ).scalars().all()
        if not events:
            raise ValueError(f"No persisted events found for {organization_id}/{person_ref}/{effective_purpose}.")

        event_ids = [event.event_id for event in events]
        evidence_records = db.execute(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.organization_id == organization_id,
                EvidenceRecord.source_event_id.in_(event_ids),
            )
            .order_by(EvidenceRecord.event_time, EvidenceRecord.evidence_id)
        ).scalars().all()

        dataset: dict[str, list[dict[str, Any]]] = {table: [] for table in FACT_TABLES}
        dataset["evidence"] = []
        event_by_id = {event.event_id: event for event in events}
        for event in events:
            for fact in event.payload.get("investigation_facts", []):
                table = fact.get("table")
                row = fact.get("row")
                if table in dataset and isinstance(row, dict):
                    dataset[table].append(row)

        for record in evidence_records:
            event = event_by_id[record.source_event_id]
            metadata = event.payload.get("__evidence_metadata", {})
            dataset["evidence"].append({
                "evidence_id": record.evidence_id,
                "canonical_id": metadata.get("canonical_id"),
                "source_type": record.source_type,
                "source_record": record.source_record,
                "source_url": metadata.get("source_url"),
                "timestamp": record.event_time.isoformat() if record.event_time else None,
                "observed_time": record.observed_time.isoformat() if record.observed_time else None,
                "ingested_at": record.ingested_at.isoformat() if record.ingested_at else None,
                "raw_excerpt": record.raw_excerpt,
                "integrity_hash": metadata.get("integrity_hash", record.content_hash),
                "evidence_status": record.evidence_status,
                "source_system": record.source_system or event.source_system,
            })

    dataset["lineage"] = neo4j_client.get_lineage(organization_id, person_ref, effective_purpose)
    return dataset


def run_persisted_investigation(
    customer_id: str,
    purpose: str,
    organization_id: str,
):
    dataset = load_persisted_dataset(organization_id, customer_id, purpose)
    withdrawal, withdrawal_timestamp = get_latest_withdrawal(dataset, customer_id, purpose)
    result = run_investigation(customer_id, purpose, dataset, organization_id=organization_id)

    with SessionLocal() as db:
        persisted_scope = db.get(PersistedInvestigationScope, result.investigation_id)
        if persisted_scope is None:
            persisted_scope = PersistedInvestigationScope(
                investigation_id=result.investigation_id,
                organization_id=organization_id,
                person_ref=customer_id,
                purpose=normalize_purpose(purpose),
                withdrawal_event=withdrawal.get("event_id"),
                window_start=withdrawal_timestamp - timedelta(days=1),
                window_end=withdrawal_timestamp + timedelta(days=3),
                watermark=result.watermark,
                policy_version="v1-demo",
                created_at=datetime.now(withdrawal_timestamp.tzinfo),
                status="ACTIVE",
            )
            db.add(persisted_scope)
        else:
            persisted_scope.organization_id = organization_id
            persisted_scope.person_ref = customer_id
            persisted_scope.purpose = normalize_purpose(purpose)
            persisted_scope.withdrawal_event = withdrawal.get("event_id")
            persisted_scope.window_start = withdrawal_timestamp - timedelta(days=1)
            persisted_scope.window_end = withdrawal_timestamp + timedelta(days=3)
            persisted_scope.watermark = result.watermark
            persisted_scope.status = "ACTIVE"
        db.commit()
    return result


def load_persisted_evidence_detail(organization_id: str, evidence_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        record = db.execute(
            select(EvidenceRecord).where(
                EvidenceRecord.organization_id == organization_id,
                EvidenceRecord.evidence_id == evidence_id,
            )
        ).scalars().first()
        if record is None:
            raise KeyError(f"Evidence {evidence_id} not found in organization {organization_id}.")
        event = db.execute(
            select(IngestionEvent).where(
                IngestionEvent.organization_id == organization_id,
                IngestionEvent.event_id == record.source_event_id,
            )
        ).scalars().first()
        if event is None:
            raise KeyError(f"Source event for evidence {evidence_id} was not found.")
        metadata = event.payload.get("__evidence_metadata", {})
        return {
            "evidence_id": record.evidence_id,
            "source_type": record.source_type,
            "source_record": record.source_record,
            "source_url": metadata.get("source_url"),
            "timestamp": record.event_time,
            "observed_time": record.observed_time,
            "ingested_at": record.ingested_at,
            "evidence_status": record.evidence_status,
            "raw_excerpt": record.raw_excerpt,
            "integrity_hash": metadata.get("integrity_hash", record.content_hash),
            "source_system": record.source_system or event.source_system,
        }
