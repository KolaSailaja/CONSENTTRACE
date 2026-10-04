from __future__ import annotations

import uuid
import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.investigation import engine as investigation_engine
from app.investigation.engine import load_dataset
from app.main import app
from app.models import EvidenceRecord, IngestionEvent, InvestigationScope
from app.neo4j_client import neo4j_client

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    str(os.getenv("REAL_STACK_MODE", "0")).strip().lower() not in {"1", "true", "yes", "on"},
    reason="REAL_STACK_MODE=1 is required to run the real PostgreSQL + Neo4j integration test.",
)
def test_real_stack_integration_requires_live_dependencies(authorized_headers):
    client = TestClient(app)
    health = client.get("/health")
    if health.status_code != 200:
        pytest.fail(f"REAL_STACK_UNAVAILABLE: /health returned {health.status_code} :: {health.text}")
    health_payload = health.json()
    if health_payload.get("database", {}).get("type") != "postgresql":
        pytest.fail(f"REAL_STACK_UNAVAILABLE: expected PostgreSQL, got {health_payload.get('database', {}).get('type')}")
    if health_payload.get("neo4j", {}).get("reachable") is not True:
        pytest.fail("REAL_STACK_UNAVAILABLE: Neo4j is not reachable")

    readiness = client.get("/ready")
    if readiness.status_code != 200:
        pytest.fail(f"REAL_STACK_UNAVAILABLE: /ready returned {readiness.status_code} :: {readiness.json()}")

    run_id = uuid.uuid4().hex
    organization_id = f"org-real-stack-{run_id}"
    payload = {
        "event_id": f"evt-real-stack-{run_id}",
        "event_type": "SUPPRESSION_COMPLETED",
        "event_time": "2026-10-02T10:50:00+05:30",
        "observed_time": "2026-10-02T10:50:02+05:30",
        "source_system": "marketing-audience",
        "organization_id": organization_id,
        "person_ref": "C1024",
        "purpose": "MARKETING",
        "payload": {"asset": "marketing_audience"},
    }

    headers = authorized_headers(organization_id, "CONNECTOR")
    response = client.post("/api/v1/ingest/events", json=payload, headers=headers)
    if response.status_code != 201:
        pytest.fail(f"REAL_STACK_UNAVAILABLE: POST /api/v1/ingest/events failed :: {response.text}")

    body = response.json()
    assert body["status"] == "accepted"
    assert body["idempotent"] is False
    assert body["organization_id"] == organization_id
    assert body["projection_status"] == "GRAPH_PROJECTED"
    duplicate_response = client.post("/api/v1/ingest/events", json=payload, headers=headers)
    assert duplicate_response.status_code == 200, duplicate_response.text
    duplicate_body = duplicate_response.json()
    assert duplicate_body["status"] == "duplicate"
    assert duplicate_body["idempotent"] is True
    assert duplicate_body["event_id"] == payload["event_id"]
    assert duplicate_body["evidence_id"] == body["evidence_id"]

    evidence_id = body["evidence_id"]
    evidence_response = client.get(
        f"/api/v1/evidence/{evidence_id}",
        headers=authorized_headers(organization_id),
    )
    if evidence_response.status_code != 200:
        pytest.fail(f"REAL_STACK_UNAVAILABLE: evidence lookup failed :: {evidence_response.text}")

    assert evidence_response.json()["source_event_id"] == payload["event_id"]
    with SessionLocal() as db:
        persisted_event = db.execute(
            select(IngestionEvent).where(
                IngestionEvent.organization_id == organization_id,
                IngestionEvent.event_id == payload["event_id"],
            )
        ).scalar_one()
        persisted_evidence = db.execute(
            select(EvidenceRecord).where(
                EvidenceRecord.organization_id == organization_id,
                EvidenceRecord.source_event_id == payload["event_id"],
            )
        ).scalar_one()
    assert persisted_event.projection_status == "GRAPH_PROJECTED"
    assert persisted_evidence.evidence_id == evidence_id


@pytest.mark.skipif(
    str(os.getenv("REAL_STACK_MODE", "0")).strip().lower() not in {"1", "true", "yes", "on"},
    reason="REAL_STACK_MODE=1 is required to run PostgreSQL + Neo4j functional verification.",
)
def test_c1024_investigation_uses_persisted_postgres_and_neo4j(monkeypatch, authorized_headers):
    from app import main as main_module

    client = TestClient(app)
    health = client.get("/health").json()
    assert health["database"]["type"] == "postgresql"
    assert health["database"]["reachable"] is True
    assert health["neo4j"]["reachable"] is True

    organization_id = f"org-c1024-functional-{uuid.uuid4().hex}"
    fixture = load_dataset()
    canonical_evidence_ids = {
        "EV-0000", "EV-1001", "EV-1002", "EV-1003", "EV-2001", "EV-2002",
        "EV-2003", "EV-3001", "EV-3002", "EV-4001", "EV-4002", "EV-4003",
        "EV-4004", "EV-9901", "EV-9902", "EV-9903",
    }
    source_facts: dict[str, list[dict[str, object]]] = {}
    withdrawal = next(row for row in fixture["consent_events"] if row["event_id"] == "CONS-C1024-002")
    initial_consent = next(row for row in fixture["consent_events"] if row["event_id"] == "CONS-C1024-001")
    source_facts["EV-0000"] = [{"table": "consent_events", "row": withdrawal}]
    source_facts["EV-9901"] = [
        {"table": "consent_events", "row": initial_consent},
        {"table": "users", "row": next(row for row in fixture["users"] if row["customer_id"] == "C1024")},
        {"table": "identity_mappings", "row": next(row for row in fixture["identity_mappings"] if row["mapping_id"] == "IM-001")},
    ]
    for evidence_id, mapping_id in (("EV-9902", "IM-002"), ("EV-9903", "IM-003")):
        source_facts[evidence_id] = [
            {"table": "identity_mappings", "row": next(row for row in fixture["identity_mappings"] if row["mapping_id"] == mapping_id)}
        ]
    source_facts["EV-2001"] = [
        {"table": "processing_logs", "row": next(row for row in fixture["processing_logs"] if row["log_id"] == "LOG-ETL-017")}
    ]
    source_facts["EV-2002"] = [
        {"table": "processing_logs", "row": next(row for row in fixture["processing_logs"] if row["log_id"] == "LOG-ETL-017-STALE")}
    ]
    source_facts["EV-3001"] = [
        {"table": "audience_membership", "row": next(row for row in fixture["audience_membership"] if row["membership_id"] == "MEM-C1024-POST")}
    ]
    source_facts["EV-3002"] = [
        {"table": "audience_membership", "row": next(row for row in fixture["audience_membership"] if row["membership_id"] == "MEM-C1024-REM")}
    ]
    source_facts["EV-4001"] = [
        {"table": "export_logs", "row": next(row for row in fixture["export_logs"] if row["export_id"] == "EXP-C1024-004")}
    ]
    source_facts["EV-4003"] = [
        {"table": "export_logs", "row": next(row for row in fixture["export_logs"] if row["export_id"] == "EXP-C1024-004-STOP")}
    ]
    source_facts["EV-4004"] = [
        {"table": "processor_acknowledgements", "row": next(row for row in fixture["processor_acknowledgements"] if row["ack_id"] == "ACK-STOP")}
    ]

    lineage_edges = [
        {
            "from_id": row["from_id"],
            "from_name": next((item["name"] for item in fixture["systems"] if item["system_id"] == row["from_id"]), next((item["name"] for item in fixture["datasets"] if item["dataset_id"] == row["from_id"]), row["from_id"])),
            "from_type": row["from_type"],
            "relationship": row["relationship"],
            "to_id": row["to_id"],
            "to_name": next((item["name"] for item in fixture["systems"] if item["system_id"] == row["to_id"]), next((item["name"] for item in fixture["datasets"] if item["dataset_id"] == row["to_id"]), row["to_id"])),
            "to_type": row["to_type"],
        }
        for row in fixture["lineage"]
    ]

    with SessionLocal() as db:
        assert db.execute(
            select(IngestionEvent).where(IngestionEvent.organization_id == organization_id)
        ).scalars().all() == []
        assert db.execute(
            select(InvestigationScope).where(InvestigationScope.organization_id == organization_id)
        ).scalars().all() == []
    assert neo4j_client.get_lineage(organization_id, "C1024", "MARKETING") == []

    for evidence in fixture["evidence"]:
        canonical_id = evidence["evidence_id"]
        if canonical_id not in canonical_evidence_ids:
            continue
        source_record = evidence["source_record"]
        if canonical_id == "EV-0000":
            event_type = "CONSENT_WITHDRAWN"
        elif canonical_id in {"EV-1001", "EV-1002"}:
            event_type = "PREFERENCE_UPDATED"
        elif canonical_id == "EV-1003":
            event_type = "DATASET_WRITE"
        elif canonical_id == "EV-2001":
            event_type = "PROCESSING_COMPLETED"
        elif canonical_id in {"EV-3001", "EV-3002"}:
            event_type = "AUDIENCE_MEMBER_ADDED" if canonical_id == "EV-3001" else "AUDIENCE_MEMBER_REMOVED"
        elif canonical_id in {"EV-4001", "EV-4003"}:
            event_type = "EXPORT_SENT" if canonical_id == "EV-4001" else "EXPORT_CREATED"
        elif canonical_id == "EV-4004":
            event_type = "PROCESSOR_ACKNOWLEDGED"
        elif canonical_id in {"EV-9901", "EV-9902", "EV-9903"}:
            event_type = "IDENTITY_MAPPED"
        elif canonical_id == "EV-2003":
            event_type = "DATASET_WRITE"
        else:
            event_type = "EVIDENCE_OBSERVED"

        facts = source_facts.get(canonical_id, [])
        event_payload: dict[str, object] = {"investigation_facts": facts}
        if canonical_id == "EV-9901":
            event_payload["asset"] = {"id": "SYS-03", "name": "Customer Database", "type": "System"}
        if canonical_id == "EV-0000":
            event_payload["asset"] = {"id": "SYS-02", "name": "Consent Service", "type": "System"}
        if canonical_id == "EV-2001":
            event_payload["asset"] = {"id": "SYS-06", "name": "Warehouse ETL", "type": "System"}
        if canonical_id == "EV-3001":
            event_payload["asset"] = {"id": "DS-06", "name": "marketing_audience", "type": "Dataset"}
        if canonical_id == "EV-4001":
            event_payload["asset"] = {"id": "SYS-09", "name": "Processor X Export", "type": "System"}
        if canonical_id == "EV-9903":
            event_payload["investigation_facts"] = facts
        request_payload = {
            "event_id": f"{organization_id}-{canonical_id}",
            "event_type": event_type,
            "event_time": evidence["timestamp"],
            "observed_time": evidence["observed_time"],
            "source_system": evidence["source_system"],
            "organization_id": organization_id,
            "person_ref": "C1024",
            "purpose": "MARKETING",
            "payload": event_payload,
            "evidence_metadata": {
                "canonical_id": canonical_id,
                "source_type": evidence["source_type"],
                "source_record": source_record,
                "source_url": evidence["source_url"],
                "evidence_status": evidence["evidence_status"],
                "raw_excerpt": evidence["raw_excerpt"],
                "integrity_hash": evidence["integrity_hash"],
            },
        }
        response = client.post(
            "/api/v1/ingest/events",
            json=request_payload,
            headers=authorized_headers(organization_id, "CONNECTOR"),
        )
        assert response.status_code == 201, response.text

    lineage_response = client.post(
        "/api/v1/ingest/events",
        json={
            "event_id": f"{organization_id}-lineage-catalog",
            "event_type": "LINEAGE_DEFINED",
            "event_time": "2026-08-12T09:05:00+05:30",
            "observed_time": "2026-08-12T09:05:00+05:30",
            "source_system": "AcmePay Lineage Catalog",
            "organization_id": organization_id,
            "person_ref": "C1024",
            "purpose": "MARKETING",
            "payload": {
                "lineage_edges": lineage_edges,
                "investigation_facts": [
                    *({"table": "lineage", "row": row} for row in fixture["lineage"]),
                    *({"table": "systems", "row": row} for row in fixture["systems"]),
                    *({"table": "datasets", "row": row} for row in fixture["datasets"]),
                ],
            },
            "evidence_metadata": {
                "source_type": "static_lineage",
                "source_record": "AcmePay lineage catalog",
                "evidence_status": "DIRECT",
                "raw_excerpt": "Static system and dataset lineage definitions.",
            },
        },
        headers=authorized_headers(organization_id, "CONNECTOR"),
    )
    assert lineage_response.status_code == 201, lineage_response.text

    monkeypatch.setattr(
        main_module,
        "load_dataset",
        lambda: pytest.fail("Investigation endpoint must not load fixture data at runtime"),
    )
    monkeypatch.setattr(
        investigation_engine,
        "load_dataset",
        lambda: pytest.fail("Investigation endpoint must not load fixture data at runtime"),
    )
    first = client.post(
        "/investigations/withdrawal",
        json={"customer_id": "C1024", "purpose": "MARKETING", "organization_id": organization_id},
        headers=authorized_headers(organization_id),
    )
    second = client.post(
        "/investigations/withdrawal",
        json={"customer_id": "C1024", "purpose": "MARKETING", "organization_id": organization_id},
        headers=authorized_headers(organization_id),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    result = first.json()
    findings = {finding["asset"]: finding for finding in result["findings"]}
    expected_states = {
        "Customer Database / CRM": "VERIFIED_STOPPED",
        "Warehouse": "VERIFIED_STOPPED",
        "ETL Job #17": "STILL_ACTIVE",
        "Marketing Audience": "STILL_ACTIVE",
        "Export #4": "STILL_ACTIVE",
        "Processor X": "UNKNOWN",
    }
    assert result["withdrawal_timestamp"] == "2026-10-02T10:31:42+05:30"
    assert result["first_break"] == "ETL Job #17"
    assert {asset: findings[asset]["finding_state"] for asset in expected_states} == expected_states
    assert first.json() == second.json()

    persisted_evidence = {}
    with SessionLocal() as db:
        persisted_evidence = {
            record.evidence_id: record
            for record in db.execute(
                select(EvidenceRecord).where(EvidenceRecord.organization_id == organization_id)
            ).scalars().all()
        }
        persisted_events = db.execute(
            select(IngestionEvent).where(IngestionEvent.organization_id == organization_id)
        ).scalars().all()
        assert db.execute(
            select(InvestigationScope).where(
                InvestigationScope.organization_id == organization_id,
                InvestigationScope.person_ref == "C1024",
                InvestigationScope.purpose == "MARKETING",
            )
        ).scalars().first() is not None
    persisted_acknowledgements = [
        fact["row"]
        for event in persisted_events
        for fact in event.payload.get("investigation_facts", [])
        if fact.get("table") == "processor_acknowledgements"
    ]
    assert persisted_acknowledgements == [{
        "ack_id": "ACK-STOP",
        "processor_id": "PROC-01",
        "customer_id": "C1024",
        "purpose": "MARKETING",
        "action": "SUPPRESSION",
        "timestamp": "2026-10-02T11:12:00+05:30",
        "status": "RECEIVED",
        "export_id": "EXP-C1024-004-STOP",
    }]
    assert not any(
        acknowledgement.get("action") == "ACKNOWLEDGED"
        and acknowledgement.get("export_id") == "EXP-C1024-004"
        for acknowledgement in persisted_acknowledgements
    )
    for finding in findings.values():
        assert finding["event_time"]
        assert finding["evidence"]
        assert all(evidence["timestamp"] for evidence in finding["evidence"])
        for evidence in finding["evidence"]:
            record = persisted_evidence[evidence["evidence_id"]]
            assert datetime.fromisoformat(evidence["timestamp"].replace("Z", "+00:00")) == record.event_time
            assert evidence["source_record"] == record.source_record
    assert {event.projection_status for event in persisted_events} == {"GRAPH_PROJECTED"}
    assert "ABSENT" == next(
        evidence["evidence_status"] for evidence in findings["Processor X"]["evidence"]
        if evidence["source_record"] == "processor_ack_missing"
    )
    assert len(neo4j_client.get_lineage(organization_id, "C1024", "MARKETING")) == len(lineage_edges)
    etl_evidence_id = next(
        evidence["evidence_id"] for evidence in findings["ETL Job #17"]["evidence"]
        if evidence["source_record"] == "USE_STALE_CONSENT_SNAPSHOT"
    )
    evidence_detail = client.get(
        f"/investigations/{result['investigation_id']}/evidence/{etl_evidence_id}",
        headers=authorized_headers(organization_id),
    )
    assert evidence_detail.status_code == 200, evidence_detail.text
    assert datetime.fromisoformat(evidence_detail.json()["timestamp"].replace("Z", "+00:00")) == datetime.fromisoformat(
        "2026-10-02T10:45:03+05:30"
    )
