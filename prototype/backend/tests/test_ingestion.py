from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_valid_event_ingestion(authorized_headers):
    payload = {
        "event_id": "evt-valid-001",
        "event_type": "CONSENT_WITHDRAWN",
        "event_time": "2026-10-02T10:31:42+05:30",
        "observed_time": "2026-10-02T10:31:43+05:30",
        "source_system": "consent-service",
        "organization_id": "org-123",
        "person_ref": "person-abc",
        "purpose": "MARKETING",
        "payload": {"notice_version": "v3.2"},
    }
    response = client.post("/api/v1/ingest/events", json=payload, headers=authorized_headers(payload["organization_id"], "CONNECTOR"))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["event_id"] == "evt-valid-001"
    assert body["status"] == "accepted"
    assert body["evidence_id"].startswith("EVID-")
    assert body["organization_id"] == "org-123"


def test_invalid_event_is_rejected(authorized_headers):
    payload = {
        "event_id": "evt-invalid-001",
        "event_type": "NOT_A_REAL_EVENT",
        "observed_time": "2026-10-02T10:31:43+05:30",
        "source_system": "consent-service",
        "organization_id": "org-123",
        "person_ref": "person-abc",
        "purpose": "MARKETING",
        "payload": {},
    }
    response = client.post("/api/v1/ingest/events", json=payload, headers=authorized_headers(payload["organization_id"], "CONNECTOR"))
    assert response.status_code in {400, 422}, response.text
    body = response.json()
    assert "error" in body


def test_duplicate_event_is_idempotent(authorized_headers):
    payload = {
        "event_id": "evt-duplicate-001",
        "event_type": "PREFERENCE_UPDATED",
        "event_time": "2026-10-02T10:35:00+05:30",
        "observed_time": "2026-10-02T10:35:01+05:30",
        "source_system": "crm",
        "organization_id": "org-123",
        "person_ref": "person-abc",
        "purpose": "MARKETING",
        "payload": {"preference": "opted_out"},
    }
    headers = authorized_headers(payload["organization_id"], "CONNECTOR")
    first = client.post("/api/v1/ingest/events", json=payload, headers=headers)
    second = client.post("/api/v1/ingest/events", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json()["idempotent"] is True
    assert second.json()["event_id"] == payload["event_id"]


def test_late_event_preserves_event_time_ordering(authorized_headers):
    late_payload = {
        "event_id": "evt-late-001",
        "event_type": "CONSENT_WITHDRAWN",
        "event_time": "2026-10-02T10:40:00+05:30",
        "observed_time": "2026-10-02T10:41:00+05:30",
        "source_system": "consent-service",
        "organization_id": "org-123",
        "person_ref": "person-abc",
        "purpose": "MARKETING",
        "payload": {"version": "v1"},
    }
    latest_payload = {
        "event_id": "evt-late-002",
        "event_type": "SUPPRESSION_COMPLETED",
        "event_time": "2026-10-02T10:45:00+05:30",
        "observed_time": "2026-10-02T10:45:01+05:30",
        "source_system": "marketing-audience",
        "organization_id": "org-123",
        "person_ref": "person-abc",
        "purpose": "MARKETING",
        "payload": {"suppressed": True},
    }
    headers = authorized_headers(late_payload["organization_id"], "CONNECTOR")
    client.post("/api/v1/ingest/events", json=latest_payload, headers=headers)
    client.post("/api/v1/ingest/events", json=late_payload, headers=headers)
    response = client.get("/api/v1/ingest/health", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["events_seen"] >= 2
    assert body["source_health"]["consent-service"]["last_event"] == "evt-late-001"
