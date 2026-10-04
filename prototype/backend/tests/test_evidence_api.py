from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_evidence_can_be_retrieved_from_persisted_record(authorized_headers):
    payload = {
        "event_id": "evt-evidence-001",
        "event_type": "CONSENT_WITHDRAWN",
        "event_time": "2026-10-02T10:50:00+05:30",
        "observed_time": "2026-10-02T10:50:02+05:30",
        "source_system": "consent-service",
        "organization_id": "org-evidence-test",
        "person_ref": "person-evidence-001",
        "purpose": "MARKETING",
        "payload": {"notice_version": "v9.0", "reason": "withdrawn"},
    }

    response = client.post("/api/v1/ingest/events", json=payload, headers=authorized_headers(payload["organization_id"], "CONNECTOR"))
    assert response.status_code == 201, response.text
    evidence_id = response.json()["evidence_id"]

    evidence_response = client.get(f"/api/v1/evidence/{evidence_id}", headers=authorized_headers(payload["organization_id"]))
    assert evidence_response.status_code == 200, evidence_response.text
    body = evidence_response.json()
    assert body["evidence_id"] == evidence_id
    assert body["source_event_id"] == payload["event_id"]
    assert body["source_system"] == payload["source_system"]
    assert body["organization_id"] == payload["organization_id"]
    assert body["integrity_verified"] is True
    assert "payload" not in body
    assert "request_id" not in body


def test_unknown_evidence_returns_404(authorized_headers):
    response = client.get("/api/v1/evidence/EVID-DOES-NOT-EXIST", headers=authorized_headers("org-acmepay-demo"))
    assert response.status_code == 404, response.text


def test_malformed_evidence_id_is_handled_safely(authorized_headers):
    response = client.get("/api/v1/evidence/not-a-valid-id", headers=authorized_headers("org-acmepay-demo"))
    assert response.status_code == 404, response.text


def test_cross_org_evidence_access_is_blocked(authorized_headers):
    payload = {
        "event_id": "evt-evidence-org-001",
        "event_type": "PREFERENCE_UPDATED",
        "event_time": "2026-10-02T10:55:00+05:30",
        "observed_time": "2026-10-02T10:55:01+05:30",
        "source_system": "crm",
        "organization_id": "org-evidence-org",
        "person_ref": "person-evidence-org",
        "purpose": "MARKETING",
        "payload": {"preference": "opted_out"},
    }
    created = client.post("/api/v1/ingest/events", json=payload, headers=authorized_headers(payload["organization_id"], "CONNECTOR"))
    assert created.status_code == 201, created.text
    evidence_id = created.json()["evidence_id"]

    response = client.get(
        f"/api/v1/evidence/{evidence_id}?organization_id=other-org",
        headers=authorized_headers(payload["organization_id"]),
    )
    assert response.status_code == 403, response.text


def test_evidence_exposes_hash_but_not_secret_payload(authorized_headers):
    payload = {
        "event_id": "evt-evidence-hash-001",
        "event_type": "SUPPRESSION_COMPLETED",
        "event_time": "2026-10-02T11:00:00+05:30",
        "observed_time": "2026-10-02T11:00:02+05:30",
        "source_system": "marketing-audience",
        "organization_id": "org-evidence-hash",
        "person_ref": "person-evidence-hash",
        "purpose": "MARKETING",
        "payload": {"asset": "marketing_audience", "secret": "not-for-public-view"},
    }
    created = client.post("/api/v1/ingest/events", json=payload, headers=authorized_headers(payload["organization_id"], "CONNECTOR"))
    assert created.status_code == 201, created.text
    evidence_id = created.json()["evidence_id"]

    response = client.get(f"/api/v1/evidence/{evidence_id}", headers=authorized_headers(payload["organization_id"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_hash"]
    assert body["hash_algorithm"] == "SHA-256"
    assert body["integrity_verified"] is True
    assert "secret" not in str(body)
