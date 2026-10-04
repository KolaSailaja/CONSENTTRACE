from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import ApiKey, EvidenceRecord, IngestionEvent, InvestigationScope, SecurityAuditRecord
from app import security as security_module

client = TestClient(app)


def _event_payload(organization_id: str, *, event_id: str | None = None, payload: dict | None = None) -> dict:
    return {
        "event_id": event_id or f"security-{uuid.uuid4().hex}",
        "event_type": "CONSENT_WITHDRAWN",
        "event_time": "2026-10-02T10:31:42+05:30",
        "observed_time": "2026-10-02T10:31:43+05:30",
        "source_system": "security-test",
        "organization_id": organization_id,
        "person_ref": "security-person",
        "purpose": "MARKETING",
        "payload": payload or {},
    }


def test_org_a_cannot_ingest_for_org_b(authorized_headers):
    organization_a = f"org-a-{uuid.uuid4().hex}"
    organization_b = f"org-b-{uuid.uuid4().hex}"
    payload = _event_payload(organization_b)
    response = client.post(
        "/api/v1/ingest/events",
        json=payload,
        headers=authorized_headers(organization_a, "CONNECTOR"),
    )
    assert response.status_code == 403
    with SessionLocal() as db:
        assert db.get(IngestionEvent, payload["event_id"]) is None


def test_org_a_cannot_investigate_org_b_person(authorized_headers):
    organization_a = f"org-a-{uuid.uuid4().hex}"
    organization_b = f"org-b-{uuid.uuid4().hex}"
    response = client.post(
        "/investigations/withdrawal",
        json={
            "customer_id": f"person-{organization_b}",
            "purpose": "MARKETING",
            "organization_id": organization_b,
        },
        headers=authorized_headers(organization_a),
    )
    assert response.status_code == 403
    assert "findings" not in response.json()


def test_org_a_cannot_retrieve_org_b_evidence(authorized_headers):
    organization_a = f"org-a-{uuid.uuid4().hex}"
    organization_b = f"org-b-{uuid.uuid4().hex}"
    event_id = f"event-{uuid.uuid4().hex}"
    evidence_id = f"EVID-{uuid.uuid4().hex.upper()}"
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(IngestionEvent(
            event_id=event_id,
            organization_id=organization_b,
            event_type="CONSENT_WITHDRAWN",
            event_time=now,
            observed_time=now,
            ingested_time=now,
            source_system="tenant-b",
            person_ref="tenant-b-person",
            purpose="MARKETING",
            payload={},
            request_id="security-test",
        ))
        db.add(EvidenceRecord(
            evidence_id=evidence_id,
            organization_id=organization_b,
            source_type="security-test",
            source_event_id=event_id,
            source_record="private-evidence",
            content_hash="a" * 64,
            event_time=now,
            observed_time=now,
            ingested_at=now,
            raw_excerpt="tenant B private evidence",
        ))
        db.commit()
    response = client.get(
        f"/api/v1/evidence/{evidence_id}",
        headers=authorized_headers(organization_a),
    )
    assert response.status_code == 404
    assert "tenant B private evidence" not in response.text


def test_not_found_evidence_access_is_audited(authorized_headers):
    organization_id = f"org-evidence-audit-{uuid.uuid4().hex}"
    headers = authorized_headers(organization_id, "VIEWER")
    evidence_id = f"EVID-{uuid.uuid4().hex.upper()}"

    direct = client.get(f"/api/v1/evidence/{evidence_id}", headers=headers)
    nested = client.get(
        f"/investigations/INV-missing-{uuid.uuid4().hex}/evidence/{evidence_id}",
        headers=headers,
    )
    assert direct.status_code == 404
    assert nested.status_code == 404

    key_id = headers["Authorization"].split(".", 1)[0].removeprefix("Bearer ct_")
    with SessionLocal() as db:
        attempts = db.execute(
            select(SecurityAuditRecord).where(
                SecurityAuditRecord.organization_id == organization_id,
                SecurityAuditRecord.principal_id == key_id,
                SecurityAuditRecord.action == "EVIDENCE_ACCESS",
                SecurityAuditRecord.outcome == "not_found",
            )
        ).scalars().all()
    assert len(attempts) == 2


def test_org_a_cannot_retrieve_org_b_lineage(authorized_headers):
    organization_a = f"org-a-{uuid.uuid4().hex}"
    organization_b = f"org-b-{uuid.uuid4().hex}"
    investigation_id = f"INV-{organization_b}-person-MARKETING-20261002103142"
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(InvestigationScope(
            investigation_id=investigation_id,
            organization_id=organization_b,
            person_ref="tenant-b-person",
            purpose="MARKETING",
            window_start=now,
            window_end=now,
            watermark=now,
        ))
        db.commit()
    response = client.get(
        f"/investigations/{investigation_id}/graph",
        headers=authorized_headers(organization_a),
    )
    assert response.status_code == 404
    assert "nodes" not in response.json()


def test_revoked_api_key_cannot_access_protected_routes(authorized_headers):
    organization_id = f"org-revoke-{uuid.uuid4().hex}"
    viewer_headers, secret = authorized_headers.with_secret(organization_id, "VIEWER")
    key_id = secret.removeprefix("ct_").split(".", 1)[0]
    admin_headers = authorized_headers(organization_id, "ADMIN")
    revoked = client.post(f"/api/v1/admin/api-keys/{key_id}/revoke", headers=admin_headers)
    assert revoked.status_code == 200, revoked.text
    response = client.get("/customers", headers=viewer_headers)
    assert response.status_code == 401


def test_missing_authentication_is_rejected(authorized_headers):
    response = client.get("/customers")
    assert response.status_code == 401
    assert response.headers.get("X-Request-ID")
    assert authorized_headers("org-auth-audit", "ADMIN")
    with SessionLocal() as db:
        failure = db.execute(
            select(SecurityAuditRecord).where(
                SecurityAuditRecord.action == "AUTHENTICATION",
                SecurityAuditRecord.outcome == "failure",
                SecurityAuditRecord.resource_id == "/customers",
            ).order_by(SecurityAuditRecord.timestamp.desc())
        ).scalars().first()
    assert failure is not None


def test_wrong_role_cannot_ingest(authorized_headers):
    organization_id = f"org-viewer-{uuid.uuid4().hex}"
    response = client.post(
        "/api/v1/ingest/events",
        json=_event_payload(organization_id),
        headers=authorized_headers(organization_id, "VIEWER"),
    )
    assert response.status_code == 403


def test_health_is_public_and_does_not_disclose_connection_secrets():
    health = client.get("/health")
    ready = client.get("/ready")
    assert health.status_code == 200
    assert ready.status_code == 200
    response_text = health.text + ready.text
    assert "postgresql://" not in response_text
    assert "postgresql+psycopg2://" not in response_text
    assert settings.database_url not in response_text
    assert "bolt://" not in response_text
    assert "neo4j_uri" not in response_text
    assert "database_url" not in response_text


def test_api_key_management_returns_secret_once_and_stores_only_hash(authorized_headers):
    organization_id = f"org-key-admin-{uuid.uuid4().hex}"
    admin_headers = authorized_headers(organization_id, "ADMIN")
    created = client.post(
        "/api/v1/admin/api-keys",
        json={"name": "read-only auditor", "role": "AUDITOR"},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"].startswith(f"ct_{body['key_id']}.")

    listed = client.get("/api/v1/admin/api-keys", headers=admin_headers)
    assert listed.status_code == 200
    serialized = json.dumps(listed.json())
    assert body["secret"] not in serialized
    assert "key_hash" not in serialized
    with SessionLocal() as db:
        record = db.get(ApiKey, body["key_id"])
    assert record is not None
    assert record.key_hash.startswith("scrypt$")
    assert body["secret"] != record.key_hash


def test_hmac_signature_and_replay_protection(authorized_headers, monkeypatch):
    encryption_key = base64.urlsafe_b64encode(b"security-test-encryption-key-32!").decode()
    monkeypatch.setattr(settings, "api_key_encryption_key", encryption_key)
    organization_id = f"org-hmac-{uuid.uuid4().hex}"
    _, secret = authorized_headers.with_secret(organization_id, "CONNECTOR")
    raw_body = json.dumps(_event_payload(organization_id), separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    path = "/api/v1/ingest/events"
    signature = hmac.new(
        secret.encode(),
        b"\n".join((b"POST", path.encode(), timestamp.encode(), raw_body)),
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-ConsentTrace-Key-Id": secret.removeprefix("ct_").split(".", 1)[0],
        "X-ConsentTrace-Timestamp": timestamp,
        "X-ConsentTrace-Signature": signature,
    }
    accepted = client.post(path, content=raw_body, headers=headers)
    replay = client.post(path, content=raw_body, headers=headers)
    assert accepted.status_code == 201, accepted.text
    assert replay.status_code == 401


def test_stale_hmac_timestamp_is_rejected(authorized_headers, monkeypatch):
    encryption_key = base64.urlsafe_b64encode(b"security-test-encryption-key-32!").decode()
    monkeypatch.setattr(settings, "api_key_encryption_key", encryption_key)
    organization_id = f"org-stale-signature-{uuid.uuid4().hex}"
    _, secret = authorized_headers.with_secret(organization_id, "CONNECTOR")
    raw_body = json.dumps(_event_payload(organization_id), separators=(",", ":")).encode()
    timestamp = str(int(time.time()) - settings.hmac_replay_window_seconds - 1)
    path = "/api/v1/ingest/events"
    signature = hmac.new(
        secret.encode(),
        b"\n".join((b"POST", path.encode(), timestamp.encode(), raw_body)),
        hashlib.sha256,
    ).hexdigest()
    response = client.post(path, content=raw_body, headers={
        "Content-Type": "application/json",
        "X-ConsentTrace-Key-Id": secret.removeprefix("ct_").split(".", 1)[0],
        "X-ConsentTrace-Timestamp": timestamp,
        "X-ConsentTrace-Signature": signature,
    })
    assert response.status_code == 401


def test_invalid_hmac_signature_is_rejected(authorized_headers, monkeypatch):
    encryption_key = base64.urlsafe_b64encode(b"security-test-encryption-key-32!").decode()
    monkeypatch.setattr(settings, "api_key_encryption_key", encryption_key)
    organization_id = f"org-invalid-signature-{uuid.uuid4().hex}"
    _, secret = authorized_headers.with_secret(organization_id, "CONNECTOR")
    raw_body = json.dumps(_event_payload(organization_id), separators=(",", ":")).encode()
    response = client.post("/api/v1/ingest/events", content=raw_body, headers={
        "Content-Type": "application/json",
        "X-ConsentTrace-Key-Id": secret.removeprefix("ct_").split(".", 1)[0],
        "X-ConsentTrace-Timestamp": str(int(time.time())),
        "X-ConsentTrace-Signature": "0" * 64,
    })
    assert response.status_code == 401


def test_request_body_limits_return_413():
    too_large_event = _event_payload("org-size-test", payload={"blob": "x" * 300_000})
    ingestion = client.post(
        "/api/v1/ingest/events",
        json=too_large_event,
        headers={"Authorization": "Bearer invalid"},
    )
    assert ingestion.status_code == 413

    oversized_evidence = _event_payload("org-size-test", payload={"blob": "x" * 70_000})
    evidence = client.post(
        "/api/v1/ingest/events",
        json=oversized_evidence,
        headers={"Authorization": "Bearer invalid"},
    )
    assert evidence.status_code == 413

    generic = client.post(
        "/investigations/withdrawal",
        content=json.dumps({"customer_id": "x", "purpose": "MARKETING", "blob": "x" * 1_100_000}),
        headers={"Content-Type": "application/json"},
    )
    assert generic.status_code == 413


def test_ingestion_rate_limit_returns_429(authorized_headers, monkeypatch):
    organization_id = f"org-rate-{uuid.uuid4().hex}"
    headers = authorized_headers(organization_id, "CONNECTOR")
    monkeypatch.setattr(security_module, "rate_limiter", security_module.InProcessRateLimiter())
    monkeypatch.setattr(settings, "rate_limit_ingest_per_minute", 1)
    first = client.post("/api/v1/ingest/events", json=_event_payload(organization_id), headers=headers)
    second = client.post("/api/v1/ingest/events", json=_event_payload(organization_id), headers=headers)
    assert first.status_code == 201, first.text
    assert second.status_code == 429


def test_investigation_rate_limit_returns_429(authorized_headers, monkeypatch):
    organization_id = f"org-investigation-rate-{uuid.uuid4().hex}"
    headers = authorized_headers(organization_id, "PRIVACY_ANALYST")
    monkeypatch.setattr(security_module, "rate_limiter", security_module.InProcessRateLimiter())
    monkeypatch.setattr(settings, "rate_limit_investigation_per_minute", 1)
    body = {"customer_id": "not-present", "purpose": "MARKETING"}
    first = client.post("/investigations/withdrawal", json=body, headers=headers)
    second = client.post("/investigations/withdrawal", json=body, headers=headers)
    assert first.status_code == 404
    assert second.status_code == 429


def test_authentication_failures_are_rate_limited(monkeypatch):
    monkeypatch.setattr(security_module, "rate_limiter", security_module.InProcessRateLimiter())
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 1)
    first = client.get("/customers")
    second = client.get("/customers")
    assert first.status_code == 401
    assert second.status_code == 429


def test_audit_trail_records_ingestion_and_is_tenant_scoped(authorized_headers):
    organization_id = f"org-audit-{uuid.uuid4().hex}"
    headers = authorized_headers(organization_id, "CONNECTOR")
    created = client.post("/api/v1/ingest/events", json=_event_payload(organization_id), headers=headers)
    assert created.status_code == 201, created.text
    auditor_headers = authorized_headers(organization_id, "AUDITOR")
    audit_log = client.get("/api/v1/audit-events", headers=auditor_headers)
    assert audit_log.status_code == 200, audit_log.text
    actions = {row["action"] for row in audit_log.json()}
    assert {"AUTHENTICATION", "EVENT_INGESTION"} <= actions
    assert all(row["organization_id"] == organization_id for row in audit_log.json())
    assert all("Authorization" not in json.dumps(row) for row in audit_log.json())
