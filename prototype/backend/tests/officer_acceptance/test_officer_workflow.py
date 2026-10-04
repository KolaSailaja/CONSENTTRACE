from __future__ import annotations

import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal, engine
from app.main import app
from app.models import EvidenceRecord, IngestionEvent, InvestigationScope
from app.neo4j_client import neo4j_client
from app.sandbox import SANDBOX_ORGANIZATION_ID, SANDBOX_PERSON_ID, SANDBOX_PURPOSE

REAL_STACK_READY = (
    engine.dialect.name == "postgresql"
    and str(os.getenv("SANDBOX_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not REAL_STACK_READY,
        reason="Officer acceptance tests require PostgreSQL and SANDBOX_ENABLED=true.",
    ),
]


@pytest.fixture
def sandbox_client(authorized_headers):
    client = TestClient(app, headers=authorized_headers(SANDBOX_ORGANIZATION_ID, "ADMIN"))
    health = client.get("/health")
    if health.status_code != 200 or health.json().get("neo4j", {}).get("reachable") is not True:
        pytest.skip("Officer acceptance tests require reachable PostgreSQL and Neo4j services.")

    reset = client.post("/api/v1/sandbox/reset", json={"confirm": True})
    assert reset.status_code == 200, reset.text
    yield client
    reset = client.post("/api/v1/sandbox/reset", json={"confirm": True})
    assert reset.status_code == 200, reset.text


def _investigate(client: TestClient) -> dict:
    response = client.post(
        "/investigations/withdrawal",
        json={
            "customer_id": SANDBOX_PERSON_ID,
            "purpose": SANDBOX_PURPOSE,
            "organization_id": SANDBOX_ORGANIZATION_ID,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _finding_states(result: dict) -> dict[str, str]:
    return {finding["asset"]: finding["finding_state"] for finding in result["findings"]}


def test_officer_investigates_persisted_stale_etl_case(sandbox_client: TestClient):
    run = sandbox_client.post("/api/v1/sandbox/scenarios/stale-etl-snapshot/run")
    assert run.status_code == 200, run.text
    run_body = run.json()
    assert run_body["status"] == "completed"
    assert {event["source_system"] for event in run_body["events"]} >= {
        "DemoCorp Consent Service",
        "DemoCorp CRM",
        "DemoCorp Warehouse",
        "DemoCorp ETL",
        "DemoCorp Marketing Audience",
        "DemoCorp Export Service",
    }
    assert sum(event["status"] == "duplicate" for event in run_body["events"]) == 1

    event_id = next(event["event_id"] for event in run_body["events"] if event["status"] == "duplicate")
    with SessionLocal() as db:
        event_count = db.execute(
            select(func.count()).select_from(IngestionEvent).where(
                IngestionEvent.organization_id == SANDBOX_ORGANIZATION_ID,
                IngestionEvent.event_id == event_id,
            )
        ).scalar_one()
        evidence_count = db.execute(
            select(func.count()).select_from(EvidenceRecord).where(
                EvidenceRecord.organization_id == SANDBOX_ORGANIZATION_ID,
                EvidenceRecord.source_event_id == event_id,
            )
        ).scalar_one()
        projected_count = db.execute(
            select(func.count()).select_from(IngestionEvent).where(
                IngestionEvent.organization_id == SANDBOX_ORGANIZATION_ID,
                IngestionEvent.projection_status == "GRAPH_PROJECTED",
            )
        ).scalar_one()
    assert event_count == 1
    assert evidence_count == 1
    assert projected_count == len(run_body["events"]) - 1

    monitor = sandbox_client.get("/api/v1/sandbox/events")
    assert monitor.status_code == 200
    assert monitor.json()["counts"]["duplicate"] == 1
    assert monitor.json()["counts"]["accepted"] == len(run_body["events"]) - 1

    with neo4j_client._driver_instance().session(database="neo4j") as session:
        graph_event_count = session.run(
            "MATCH (event:Event {organization_id: $organization_id}) RETURN count(event) AS count",
            organization_id=SANDBOX_ORGANIZATION_ID,
        ).single()["count"]
    assert graph_event_count == len(run_body["events"]) - 1
    assert len(neo4j_client.get_lineage(
        SANDBOX_ORGANIZATION_ID,
        SANDBOX_PERSON_ID,
        SANDBOX_PURPOSE,
    )) == 5

    first = _investigate(sandbox_client)
    states = _finding_states(first)
    assert first["customer_id"] == SANDBOX_PERSON_ID
    assert first["customer_name"] == "Test Customer"
    assert first["purpose"] == SANDBOX_PURPOSE
    assert first["withdrawal_timestamp"] == "2026-10-02T10:31:42+05:30"
    assert first["first_break"] == "ETL Job #17"
    assert states["Customer Database / CRM"] == "VERIFIED_STOPPED"
    assert states["Warehouse"] == "VERIFIED_STOPPED"
    assert states["ETL Job #17"] == "STILL_ACTIVE"
    assert states["Marketing Audience"] == "STILL_ACTIVE"
    assert states["Export #4"] == "STILL_ACTIVE"
    assert states["Processor X"] == "UNKNOWN"

    etl = next(finding for finding in first["findings"] if finding["asset"] == "ETL Job #17")
    stale_evidence = next(item for item in etl["evidence"] if item["source_record"] == "USE_STALE_CONSENT_SNAPSHOT")
    detail = sandbox_client.get(
        f"/investigations/{first['investigation_id']}/evidence/{stale_evidence['evidence_id']}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["evidence_status"] == "STALE"
    assert detail.json()["source_system"] == "DemoCorp ETL"
    assert detail.json()["source_record"] == "USE_STALE_CONSENT_SNAPSHOT"
    assert datetime.fromisoformat(detail.json()["timestamp"].replace("Z", "+00:00")) == datetime.fromisoformat(
        "2026-10-02T10:45:03+05:30"
    )

    simulated = sandbox_client.post(
        "/investigations/remediation",
        json={"investigation_id": first["investigation_id"], "scenario": "demo-remediation"},
    )
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["overall_investigation_state"] == "REMEDIATION_SIMULATION"
    rerun = _investigate(sandbox_client)
    assert rerun == first


def test_success_and_conflicting_processor_scenarios_are_evaluated_from_events(sandbox_client: TestClient):
    successful = sandbox_client.post("/api/v1/sandbox/scenarios/successful-withdrawal/run")
    assert successful.status_code == 200, successful.text
    successful_result = _investigate(sandbox_client)
    successful_states = _finding_states(successful_result)
    assert successful_states["Customer Database / CRM"] == "VERIFIED_STOPPED"
    assert successful_states["Warehouse"] == "VERIFIED_STOPPED"
    assert successful_states["Marketing Audience"] == "VERIFIED_STOPPED"

    reset = sandbox_client.post("/api/v1/sandbox/reset", json={"confirm": True})
    assert reset.status_code == 200, reset.text
    conflict = sandbox_client.post("/api/v1/sandbox/scenarios/conflicting-processor-evidence/run")
    assert conflict.status_code == 200, conflict.text
    conflict_result = _investigate(sandbox_client)
    conflict_states = _finding_states(conflict_result)
    assert conflict_states["Processor X"] == "CONFLICTED"


def test_out_of_order_and_late_events_use_event_time_and_recompute_scope(
    sandbox_client: TestClient,
    authorized_headers,
):
    run = sandbox_client.post("/api/v1/sandbox/scenarios/out-of-order-events/run")
    assert run.status_code == 200, run.text
    event_rows = run.json()["events"]
    stale_index = next(index for index, event in enumerate(event_rows) if event["event_type"] == "DATASET_READ")
    withdrawal_index = next(index for index, event in enumerate(event_rows) if event["event_type"] == "CONSENT_WITHDRAWN")
    assert stale_index < withdrawal_index

    result = _investigate(sandbox_client)
    assert result["first_break"] == "ETL Job #17"
    assert _finding_states(result)["ETL Job #17"] == "STILL_ACTIVE"

    late_event = {
        "event_id": "evt-democorp-late-audience-event",
        "event_type": "AUDIENCE_MEMBER_REMOVED",
        "event_time": "2026-10-02T11:30:00+05:30",
        "observed_time": "2026-10-02T12:05:00+05:30",
        "source_system": "DemoCorp Marketing Audience",
        "organization_id": SANDBOX_ORGANIZATION_ID,
        "person_ref": SANDBOX_PERSON_ID,
        "purpose": SANDBOX_PURPOSE,
        "payload": {
            "audience_id": "marketing_audience",
            "investigation_facts": [{
                "table": "audience_membership",
                "row": {
                    "membership_id": "MEM-LATE-REM",
                    "audience_id": "marketing_audience",
                    "customer_id": SANDBOX_PERSON_ID,
                    "purpose": SANDBOX_PURPOSE,
                    "observed_at": "2026-10-02T11:30:00+05:30",
                    "status": "REMOVED",
                },
            }],
        },
        "evidence_metadata": {
            "source_type": "audience_membership",
            "source_record": "LATE_AUDIENCE_SUPPRESSION",
            "raw_excerpt": "A late-arriving sandbox suppression record was observed at its original event time.",
            "evidence_status": "DIRECT",
        },
    }
    ingested = sandbox_client.post(
        "/api/v1/ingest/events",
        json=late_event,
        headers=authorized_headers(SANDBOX_ORGANIZATION_ID, "CONNECTOR"),
    )
    assert ingested.status_code == 201, ingested.text
    after_late_event = _investigate(sandbox_client)
    assert _finding_states(after_late_event)["Marketing Audience"] == "CONFLICTED"
    with SessionLocal() as db:
        persisted = db.get(IngestionEvent, late_event["event_id"])
        assert persisted is not None
        assert datetime.fromisoformat(late_event["event_time"]) == persisted.event_time
        assert datetime.fromisoformat(late_event["observed_time"]) == persisted.observed_time
        scope = db.get(InvestigationScope, result["investigation_id"])
        assert scope is not None
        assert scope.status == "ACTIVE"
