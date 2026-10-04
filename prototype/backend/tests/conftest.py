from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from app.db import SessionLocal
from app.models import ApiKey, HmacReplayRecord, SecurityAuditRecord
from app.security import create_key_record


class ApiKeyFactory:
    def __init__(self) -> None:
        self.key_ids: list[str] = []
        self.headers_by_identity: dict[tuple[str, str], tuple[dict[str, str], str]] = {}

    def __call__(self, organization_id: str, role: str = "ADMIN") -> dict[str, str]:
        identity = (organization_id, role)
        if identity not in self.headers_by_identity:
            record, secret = create_key_record(
                organization_id=organization_id,
                name=f"pytest-{uuid.uuid4().hex}",
                role=role,
            )
            key_id = record.key_id
            with SessionLocal() as db:
                db.add(record)
                db.commit()
            self.key_ids.append(key_id)
            self.headers_by_identity[identity] = (
                {"Authorization": f"Bearer {secret}"},
                secret,
            )
        return self.headers_by_identity[identity][0]

    def with_secret(self, organization_id: str, role: str = "ADMIN") -> tuple[dict[str, str], str]:
        headers = self(organization_id, role)
        return headers, self.headers_by_identity[(organization_id, role)][1]


@pytest.fixture
def authorized_headers():
    keys = ApiKeyFactory()
    yield keys
    if keys.key_ids:
        with SessionLocal() as db:
            db.execute(delete(HmacReplayRecord).where(HmacReplayRecord.key_id.in_(keys.key_ids)))
            db.execute(delete(SecurityAuditRecord).where(SecurityAuditRecord.principal_id.in_(keys.key_ids)))
            db.execute(delete(ApiKey).where(ApiKey.key_id.in_(keys.key_ids)))
            db.commit()
