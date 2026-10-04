from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not settings.database_url or not settings.database_url.startswith("postgresql"),
    reason="PostgreSQL integration tests require a Postgres DATABASE_URL.",
)
def test_postgresql_integration_requires_real_database(authorized_headers):
    if os.getenv("SKIP_POSTGRES_INTEGRATION") == "1":
        pytest.skip("PostgreSQL integration test is disabled in this environment.")

    client = TestClient(app)
    payload = {
        "event_id": "evt-pg-int-001",
        "event_type": "SUPPRESSION_COMPLETED",
        "event_time": "2026-10-02T12:00:00+05:30",
        "observed_time": "2026-10-02T12:00:02+05:30",
        "source_system": "marketing-audience",
        "organization_id": "org-pg-int",
        "person_ref": "C1024",
        "purpose": "MARKETING",
        "payload": {"asset": "marketing_audience"},
    }

    response = client.post(
        "/api/v1/ingest/events",
        json=payload,
        headers=authorized_headers(payload["organization_id"], "CONNECTOR"),
    )
    assert response.status_code == 201, response.text
    evidence_id = response.json()["evidence_id"]
    evidence_response = client.get(
        f"/api/v1/evidence/{evidence_id}",
        headers=authorized_headers(payload["organization_id"]),
    )
    assert evidence_response.status_code == 200, evidence_response.text
    assert evidence_response.json()["source_event_id"] == payload["event_id"]
