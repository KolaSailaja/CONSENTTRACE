from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import SessionLocal, init_db
from app.investigation.engine import get_path_graph, load_dataset, simulate_remediation
from app.investigation.persistence import (
    load_persisted_dataset,
    load_persisted_evidence_detail,
    run_persisted_investigation,
)
from app.models import ApiKey, EvidenceRecord, IngestionEvent, InvestigationScope, SecurityAuditRecord, SourceHealth
from app.neo4j_client import neo4j_client
from app.schemas import EvidenceDetail, InvestigationRequest, InvestigationResult, RemediationRequest
from app.security import (
    ALL_ROLES,
    HUMAN_ROLES,
    Principal,
    RequestSizeLimitMiddleware,
    audit,
    bootstrap_configured_keys,
    create_key_record,
    enforce_rate_limit,
    require_permission,
    require_roles,
)
from app.sandbox import (
    SANDBOX_EVENT_DELAY_SECONDS,
    SANDBOX_ORGANIZATION_ID,
    SANDBOX_PERSON_ID,
    SANDBOX_PERSON_NAME,
    SANDBOX_PURPOSE,
    SANDBOX_SCENARIOS,
    SANDBOX_SYSTEMS,
    run_scenario,
)

EVENT_TYPES = Literal[
    "CONSENT_GRANTED",
    "CONSENT_WITHDRAWN",
    "PREFERENCE_UPDATED",
    "PROCESSING_STARTED",
    "PROCESSING_COMPLETED",
    "DATASET_READ",
    "DATASET_WRITE",
    "AUDIENCE_MEMBER_ADDED",
    "AUDIENCE_MEMBER_REMOVED",
    "EXPORT_CREATED",
    "EXPORT_SENT",
    "PROCESSOR_ACKNOWLEDGED",
    "SUPPRESSION_COMPLETED",
    "IDENTITY_MAPPED",
    "EXCEPTION_CREATED",
    "LINEAGE_DEFINED",
    "EVIDENCE_OBSERVED",
]

EVENT_REQUIREMENTS = {
    "CONSENT_GRANTED": ["consent_status"],
    "CONSENT_WITHDRAWN": ["termination_reason"],
    "PREFERENCE_UPDATED": ["preference"],
    "PROCESSING_STARTED": ["dataset_id"],
    "PROCESSING_COMPLETED": ["dataset_id"],
    "DATASET_READ": ["dataset_id"],
    "DATASET_WRITE": ["dataset_id"],
    "AUDIENCE_MEMBER_ADDED": ["audience_id"],
    "AUDIENCE_MEMBER_REMOVED": ["audience_id"],
    "EXPORT_CREATED": ["export_id"],
    "EXPORT_SENT": ["export_id"],
    "PROCESSOR_ACKNOWLEDGED": ["processor_id"],
    "SUPPRESSION_COMPLETED": ["audience_id"],
    "IDENTITY_MAPPED": ["source_identifier"],
    "EXCEPTION_CREATED": ["exception_id"],
}

app = FastAPI(
    title="CONSENTTRACE API",
    version="0.1.0",
    docs_url=None if settings.app_mode == "PRODUCTION" else "/docs",
    redoc_url=None if settings.app_mode == "PRODUCTION" else "/redoc",
    openapi_url=None if settings.app_mode == "PRODUCTION" else "/openapi.json",
)
app.state.db_init_error = None

try:
    init_db()
    bootstrap_configured_keys()
    app.state.db_init_error = None
except Exception as exc:  # pragma: no cover - runtime dependency path
    app.state.db_init_error = str(exc)
    if settings.app_mode == "PRODUCTION":
        raise RuntimeError("Production security/database initialization failed.") from exc

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-ConsentTrace-Key-Id", "X-ConsentTrace-Timestamp", "X-ConsentTrace-Signature"],
)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_json_body_bytes=settings.max_json_body_bytes,
    max_ingestion_event_bytes=settings.max_ingestion_event_bytes,
    max_evidence_payload_bytes=settings.max_evidence_payload_bytes,
)


@app.middleware("http")
async def request_correlation(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_id):
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_EVENT",
                "message": exc.errors()[0].get("msg", "Malformed request payload"),
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": str(detail),
                "request_id": request_id,
            }
        },
    )


def parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def make_error(code: str, message: str, request_id: str, status_code: int = 400):
    raise HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
    )


INVESTIGATION_STORE: dict[str, InvestigationResult] = {}
EVENT_STORE: dict[str, dict[str, Any]] = {}
EVIDENCE_STORE: dict[str, dict[str, Any]] = {}
SOURCE_HEALTH: dict[str, dict[str, Any]] = {}
SANDBOX_EVENT_MONITOR: list[dict[str, Any]] = []
SANDBOX_RUN_LOCK = asyncio.Lock()


def sandbox_is_enabled() -> bool:
    return (
        settings.sandbox_enabled
        and settings.app_mode == "SANDBOX"
        and settings.app_env.strip().lower() in {"development", "test"}
    )


def require_sandbox_enabled() -> None:
    if not sandbox_is_enabled():
        raise HTTPException(status_code=404, detail="Company sandbox is not enabled in this environment.")


def require_sandbox_organization(principal: Principal) -> None:
    require_sandbox_enabled()
    if principal.organization_id != SANDBOX_ORGANIZATION_ID:
        raise HTTPException(status_code=403, detail="Sandbox administration requires a DemoCorp sandbox administrator key.")


def record_sandbox_event(
    *,
    organization_id: str,
    event_id: str | None,
    event_type: str | None,
    source_system: str | None,
    event_time: str | None,
    status: str,
    http_status: int,
    ingested_at: str | None = None,
    projection_status: str | None = None,
    evidence_id: str | None = None,
) -> None:
    if organization_id != SANDBOX_ORGANIZATION_ID:
        return
    SANDBOX_EVENT_MONITOR.append({
        "event_id": event_id or "unavailable",
        "event_type": event_type or "unavailable",
        "source_system": source_system or "unavailable",
        "event_time": event_time,
        "ingested_at": ingested_at or datetime.now(timezone.utc).isoformat(),
        "status": status,
        "http_status": http_status,
        "projection_status": projection_status,
        "evidence_id": evidence_id,
    })
    del SANDBOX_EVENT_MONITOR[:-500]


def recompute_affected_investigations(
    organization_id: str,
    person_ref: str,
    purpose: str | None,
    event_time: datetime,
) -> list[InvestigationResult]:
    with SessionLocal() as db:
        rows = db.execute(
            select(InvestigationScope).where(
                InvestigationScope.organization_id == organization_id,
                InvestigationScope.person_ref == person_ref,
                InvestigationScope.purpose == (purpose or ""),
                InvestigationScope.window_start <= event_time,
                InvestigationScope.window_end >= event_time,
            )
        ).scalars().all()

    results: list[InvestigationResult] = []
    for scope in rows:
        try:
            result = run_persisted_investigation(scope.person_ref, scope.purpose, scope.organization_id)
        except ValueError:
            continue
        INVESTIGATION_STORE[result.investigation_id] = result
        results.append(result)
    return results


def persist_source_health(db, source_name: str, organization_id: str, event_id: str, event_time: datetime, ingested_time: datetime):
    record = db.execute(
        select(SourceHealth).where(
            SourceHealth.organization_id == organization_id,
            SourceHealth.source_name == source_name,
        )
    ).scalars().first()
    if record is None:
        record = SourceHealth(
            organization_id=organization_id,
            source_name=source_name,
            source_type="webhook",
            connection_status="connected",
        )
        db.add(record)

    record.event_count = (record.event_count or 0) + 1
    record.last_successful_ingestion = ingested_time
    record.last_event = event_id
    record.updated_at = datetime.now(timezone.utc)
    if event_time is not None:
        record.last_event = event_id
        record.updated_at = datetime.now(timezone.utc)
    db.flush()
    return record


def persist_event_and_evidence(event: IngestEventRequest, request_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    normalized_event_time = parse_iso_datetime(event.event_time)
    observed_time = parse_iso_datetime(event.observed_time) if event.observed_time else normalized_event_time
    ingested_time = datetime.now(timezone.utc)

    with SessionLocal() as db:
        existing = db.execute(
            select(IngestionEvent).where(
                IngestionEvent.organization_id == event.organization_id,
                IngestionEvent.event_id == event.event_id,
            )
        ).scalars().first()
        if existing is not None:
            evidence = db.execute(
                select(EvidenceRecord).where(EvidenceRecord.source_event_id == event.event_id)
            ).scalars().first()
            return {
                "event_id": existing.event_id,
                "organization_id": existing.organization_id,
                "status": "duplicate",
                "evidence_id": evidence.evidence_id if evidence else None,
                "idempotent": True,
                "request_id": request_id,
            }, {
                "evidence_id": evidence.evidence_id if evidence else None,
                "content_hash": evidence.content_hash if evidence else None,
            }, "DUPLICATE"

        canonical_payload = canonical_json(event.model_dump())
        evidence_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        evidence_id = f"EVID-{evidence_hash[:16].upper()}"
        evidence_excerpt = (event.evidence_metadata or {}).get("raw_excerpt", canonical_payload)
        content_hash = hashlib.sha256(evidence_excerpt.encode("utf-8")).hexdigest()

        event_record = IngestionEvent(
            event_id=event.event_id,
            organization_id=event.organization_id,
            event_type=event.event_type,
            event_time=normalized_event_time,
            observed_time=observed_time,
            ingested_time=ingested_time,
            source_system=event.source_system,
            person_ref=event.person_ref,
            purpose=event.purpose,
            payload={
                **event.payload,
                "__evidence_metadata": event.evidence_metadata or {},
            },
            request_id=request_id,
            projection_status="RECEIVED",
            recomputation_status="PENDING",
        )
        evidence_record = EvidenceRecord(
            evidence_id=evidence_id,
            organization_id=event.organization_id,
            source_type=(event.evidence_metadata or {}).get("source_type", "external_event"),
            source_event_id=event.event_id,
            source_record=(event.evidence_metadata or {}).get("source_record", event.source_system),
            content_hash=content_hash,
            hash_algorithm="SHA-256",
            event_time=normalized_event_time,
            observed_time=observed_time,
            ingested_at=ingested_time,
            evidence_status=(event.evidence_metadata or {}).get("evidence_status", "DIRECT"),
            reliability_tier="MEDIUM",
            normalization_version="v1",
            raw_excerpt=evidence_excerpt,
            source_system=event.source_system,
            request_id=request_id,
        )
        db.add(event_record)
        db.flush()
        db.add(evidence_record)
        persist_source_health(db, event.source_system, event.organization_id, event.event_id, normalized_event_time, ingested_time)
        db.commit()

    EVENT_STORE[event.event_id] = {
        "event_id": event.event_id,
        "organization_id": event.organization_id,
        "event_type": event.event_type,
        "source_system": event.source_system,
        "evidence_id": evidence_id,
    }

    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "status": "accepted",
        "idempotent": False,
        "evidence_id": evidence_id,
        "organization_id": event.organization_id,
        "event_time": normalized_event_time.isoformat() if normalized_event_time else None,
        "observed_time": observed_time.isoformat() if observed_time else None,
        "ingested_time": ingested_time.isoformat(),
        "request_id": request_id,
    }, {
        "evidence_id": evidence_id,
        "content_hash": content_hash,
        "source_event_id": event.event_id,
        "organization_id": event.organization_id,
        "source_system": event.source_system,
        "event_time": normalized_event_time,
        "observed_time": observed_time,
    }, "OK"


def ensure_investigation_scope(organization_id: str, person_ref: str, purpose: str, event_time: datetime):
    with SessionLocal() as db:
        scope = db.execute(
            select(InvestigationScope).where(
                InvestigationScope.organization_id == organization_id,
                InvestigationScope.person_ref == person_ref,
                InvestigationScope.purpose == purpose,
            )
        ).scalars().first()
        if scope is not None:
            return scope

        scope = InvestigationScope(
            investigation_id=f"INV-{organization_id}-{person_ref}-{purpose}-{event_time.strftime('%Y%m%d%H%M%S')}",
            organization_id=organization_id,
            person_ref=person_ref,
            purpose=purpose,
            withdrawal_event="external-event",
            window_start=event_time - timedelta(days=1),
            window_end=event_time + timedelta(days=7),
            watermark=event_time + timedelta(hours=1),
            policy_version="v1",
            created_at=datetime.now(timezone.utc),
            status="ACTIVE",
        )
        db.add(scope)
        db.commit()
        return scope


class IngestEventRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    event_type: str
    event_time: str
    observed_time: str | None = None
    source_system: str
    organization_id: str | None = None
    person_ref: str
    purpose: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_metadata: dict[str, Any] | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str):
        allowed = {
            "CONSENT_GRANTED",
            "CONSENT_WITHDRAWN",
            "PREFERENCE_UPDATED",
            "PROCESSING_STARTED",
            "PROCESSING_COMPLETED",
            "DATASET_READ",
            "DATASET_WRITE",
            "AUDIENCE_MEMBER_ADDED",
            "AUDIENCE_MEMBER_REMOVED",
            "EXPORT_CREATED",
            "EXPORT_SENT",
            "PROCESSOR_ACKNOWLEDGED",
            "SUPPRESSION_COMPLETED",
            "IDENTITY_MAPPED",
            "EXCEPTION_CREATED",
            "LINEAGE_DEFINED",
            "EVIDENCE_OBSERVED",
        }
        if value not in allowed:
            raise ValueError(f"Unsupported event_type '{value}'")
        return value

    @field_validator("event_time", "observed_time")
    @classmethod
    def validate_datetime_fields(cls, value: str | None):
        if value is None or not str(value).strip():
            raise ValueError("event_time is required")
        parse_iso_datetime(str(value))
        return value

    @model_validator(mode="after")
    def validate_event_against_type(self):
        if not self.person_ref or not self.source_system:
            raise ValueError("person_ref and source_system are required")
        return self


def get_or_create_investigation(investigation_id: str | None = None, customer_id: str = "C1024", purpose: str = "MARKETING") -> InvestigationResult:
    if investigation_id and investigation_id in INVESTIGATION_STORE:
        return INVESTIGATION_STORE[investigation_id]
    organization_id = "org-acmepay-demo"
    if investigation_id:
        with SessionLocal() as db:
            scope = db.get(InvestigationScope, investigation_id)
            if scope is None:
                raise HTTPException(status_code=404, detail="Investigation not found")
            customer_id = scope.person_ref
            purpose = scope.purpose
            organization_id = scope.organization_id
    result = run_persisted_investigation(customer_id, purpose, organization_id)
    INVESTIGATION_STORE[result.investigation_id] = result
    return result


def refresh_source_health(source_name: str, event_id: str, event_time: datetime, event_record: dict[str, Any]):
    source_state = SOURCE_HEALTH.setdefault(
        source_name,
        {
            "source_name": source_name,
            "source_type": "webhook",
            "last_successful_ingestion": None,
            "last_event": None,
            "event_count": 0,
            "failed_events": 0,
            "duplicate_events": 0,
            "validation_failures": 0,
            "current_cursor": None,
            "connection_status": "connected",
        },
    )
    source_state["event_count"] += 1
    ingested_at = event_record["ingested_time"]
    current_ingestion = source_state.get("last_successful_ingestion")
    if current_ingestion is None or ingested_at >= parse_iso_datetime(current_ingestion):
        source_state["last_successful_ingestion"] = ingested_at.isoformat()

    if event_time is not None:
        current_last = source_state.get("last_event_time")
        if current_last is None or event_time >= parse_iso_datetime(current_last):
            source_state["last_event"] = event_id
            source_state["last_event_time"] = event_time.isoformat()


def database_status() -> dict[str, Any]:
    db_url = settings.database_url or "sqlite:///./consenttrace.db"
    database_type = "sqlite" if db_url.startswith("sqlite") else "postgresql"
    if database_type == "sqlite":
        reachable = True
        detail = "sqlite-unit-test-mode"
    else:
        try:
            with SessionLocal() as session:
                session.execute(select(1))
            reachable = True
            detail = "reachable"
        except Exception:  # pragma: no cover - runtime dependency path
            reachable = False
            detail = "unreachable"
    return {
        "type": database_type,
        "reachable": reachable,
        "status": "healthy" if reachable else "unhealthy",
        "detail": detail,
    }


@app.get("/health")
def health():
    db = database_status()
    neo = neo4j_client.health_check()
    if db["reachable"] and neo["reachable"]:
        status = "healthy"
    elif db["reachable"] or neo["reachable"]:
        status = "degraded"
    else:
        status = "unhealthy"
    return {
        "status": status,
        "service": "consenttrace-backend",
        "database": db,
        "neo4j": neo,
    }


@app.get("/ready")
def ready():
    db = database_status()
    neo = neo4j_client.health_check()
    real_stack_mode = str(os.getenv("REAL_STACK_MODE", "0")).strip().lower() not in {"", "0", "false", "off", "no"}
    sqlite_mode = bool(settings.database_url and settings.database_url.startswith("sqlite")) or not settings.database_url
    if sqlite_mode and not real_stack_mode:
        return {"status": "ready", "ready": True, "mode": "sqlite-unit-test", "database": db, "neo4j": neo}
    if not db["reachable"] or not neo["reachable"]:
        return JSONResponse(status_code=503, content={"status": "not_ready", "ready": False, "database": db, "neo4j": neo})
    return {
        "status": "ready",
        "ready": True,
        "mode": settings.app_mode.lower(),
        "database": db,
        "neo4j": neo,
    }


@app.get("/api/v1/ingest/health")
def ingest_health(principal: Principal = Depends(require_permission("ingest_status"))):
    with SessionLocal() as db:
        rows = db.execute(
            select(SourceHealth).where(SourceHealth.organization_id == principal.organization_id)
        ).scalars().all()
        events_seen = db.execute(
            select(func.count()).select_from(IngestionEvent).where(
                IngestionEvent.organization_id == principal.organization_id,
            )
        ).scalar_one()
    source_health = {}
    for row in rows:
        source_health[row.source_name] = {
            "source_name": row.source_name,
            "source_type": row.source_type,
            "last_successful_ingestion": row.last_successful_ingestion.isoformat() if row.last_successful_ingestion else None,
            "last_event": row.last_event,
            "event_count": row.event_count,
            "failed_events": row.failed_events,
            "duplicate_events": row.duplicate_events,
            "validation_failures": row.validation_failures,
            "current_cursor": row.current_cursor,
            "connection_status": row.connection_status,
        }
    return {
        "status": "ok",
        "events_seen": events_seen,
        "source_health": source_health,
        "database": {
            "type": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql",
        },
        "neo4j": neo4j_client.health_check(),
    }


@app.get("/api/v1/sandbox")
def sandbox_status(_principal: Principal = Depends(require_roles("ADMIN"))):
    if not sandbox_is_enabled():
        return {"enabled": False, "environment": "SANDBOX"}
    require_sandbox_organization(_principal)
    return {
        "enabled": True,
        "environment": "SANDBOX",
        "organization_id": SANDBOX_ORGANIZATION_ID,
        "organization_name": "DemoCorp",
        "person": {"person_ref": SANDBOX_PERSON_ID, "name": SANDBOX_PERSON_NAME},
        "purpose": SANDBOX_PURPOSE,
        "systems": list(SANDBOX_SYSTEMS),
        "scenarios": [
            {"scenario_id": scenario_id, **scenario}
            for scenario_id, scenario in SANDBOX_SCENARIOS.items()
        ],
        "event_delay_seconds": SANDBOX_EVENT_DELAY_SECONDS,
        "reset_scope": "DemoCorp sandbox organization only",
    }


@app.get("/api/v1/sandbox/events")
def sandbox_events(_principal: Principal = Depends(require_roles("ADMIN"))):
    require_sandbox_organization(_principal)
    with SessionLocal() as db:
        persisted = db.execute(
            select(IngestionEvent)
            .where(IngestionEvent.organization_id == SANDBOX_ORGANIZATION_ID)
            .order_by(IngestionEvent.ingested_time, IngestionEvent.event_id)
        ).scalars().all()

    monitored = [
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "source_system": event.source_system,
            "event_time": event.event_time.isoformat() if event.event_time else None,
            "ingested_at": event.ingested_time.isoformat() if event.ingested_time else None,
            "status": "failed" if event.projection_status == "GRAPH_PROJECTION_FAILED" else "accepted",
            "http_status": 201,
            "projection_status": event.projection_status,
        }
        for event in persisted
    ]
    persisted_ids = {event["event_id"] for event in monitored}
    monitored.extend(
        event for event in SANDBOX_EVENT_MONITOR
        if event["event_id"] not in persisted_ids or event["status"] != "accepted"
    )
    monitored.sort(key=lambda event: event.get("ingested_at") or "")
    return {"events": monitored, "counts": {
        status: sum(event["status"] == status for event in monitored)
        for status in ("accepted", "duplicate", "rejected", "failed")
    }}


class SandboxResetRequest(BaseModel):
    confirm: bool


@app.post("/api/v1/sandbox/reset")
def reset_sandbox(request: SandboxResetRequest, http_request: Request, principal: Principal = Depends(require_roles("ADMIN"))):
    require_sandbox_organization(principal)
    if request.confirm is not True:
        raise HTTPException(status_code=400, detail="Explicit sandbox reset confirmation is required.")

    neo4j_client.clear_organization(SANDBOX_ORGANIZATION_ID)
    with SessionLocal() as db:
        evidence_count = db.execute(
            select(EvidenceRecord).where(EvidenceRecord.organization_id == SANDBOX_ORGANIZATION_ID)
        ).scalars().all()
        event_count = db.execute(
            select(IngestionEvent).where(IngestionEvent.organization_id == SANDBOX_ORGANIZATION_ID)
        ).scalars().all()
        scope_count = db.execute(
            select(InvestigationScope).where(InvestigationScope.organization_id == SANDBOX_ORGANIZATION_ID)
        ).scalars().all()
        db.execute(delete(EvidenceRecord).where(EvidenceRecord.organization_id == SANDBOX_ORGANIZATION_ID))
        db.execute(delete(IngestionEvent).where(IngestionEvent.organization_id == SANDBOX_ORGANIZATION_ID))
        db.execute(delete(InvestigationScope).where(InvestigationScope.organization_id == SANDBOX_ORGANIZATION_ID))
        db.execute(delete(SourceHealth).where(SourceHealth.organization_id == SANDBOX_ORGANIZATION_ID))
        db.commit()

    for key in list(INVESTIGATION_STORE):
        if key.startswith(f"INV-{SANDBOX_ORGANIZATION_ID}-"):
            INVESTIGATION_STORE.pop(key, None)
    for store in (EVENT_STORE, EVIDENCE_STORE):
        for key, value in list(store.items()):
            if value.get("organization_id") == SANDBOX_ORGANIZATION_ID:
                store.pop(key, None)
    for source_system in SANDBOX_SYSTEMS:
        SOURCE_HEALTH.pop(source_system, None)
    SANDBOX_EVENT_MONITOR.clear()
    audit(
        request=http_request,
        action="SANDBOX_RESET",
        resource_type="organization",
        resource_id=SANDBOX_ORGANIZATION_ID,
        outcome="success",
        principal=principal,
        metadata={
            "deleted_events": len(event_count),
            "deleted_evidence_records": len(evidence_count),
            "deleted_investigation_scopes": len(scope_count),
        },
    )
    return {
        "status": "reset",
        "organization_id": SANDBOX_ORGANIZATION_ID,
        "deleted_events": len(event_count),
        "deleted_evidence_records": len(evidence_count),
        "deleted_investigation_scopes": len(scope_count),
        "scope": "DemoCorp sandbox organization only",
    }


@app.post("/api/v1/sandbox/scenarios/{scenario_id}/run")
async def start_sandbox_scenario(scenario_id: str, http_request: Request, principal: Principal = Depends(require_roles("ADMIN"))):
    require_sandbox_organization(principal)
    if scenario_id not in SANDBOX_SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown sandbox scenario '{scenario_id}'.")
    async with SANDBOX_RUN_LOCK:
        with SessionLocal() as db:
            existing_events = db.execute(
                select(IngestionEvent.event_id).where(
                    IngestionEvent.organization_id == SANDBOX_ORGANIZATION_ID
                ).limit(1)
            ).first()
        if existing_events:
            raise HTTPException(
                status_code=409,
                detail="DemoCorp already has sandbox events. Reset the DemoCorp sandbox before starting another scenario.",
            )
        result = await run_scenario(scenario_id, app)
    audit(
        request=http_request,
        action="SANDBOX_SCENARIO",
        resource_type="scenario",
        resource_id=scenario_id,
        outcome=result["status"],
        principal=principal,
        metadata={"run_id": result["run_id"], "event_count": len(result["events"])},
    )
    if result["status"] != "completed":
        return JSONResponse(status_code=502, content=result)
    return result


@app.get("/api/v1/evidence/{evidence_id}")
def get_evidence_record(
    evidence_id: str,
    request: Request,
    organization_id: str | None = None,
    principal: Principal = Depends(require_permission("read")),
):
    if organization_id is not None and organization_id != principal.organization_id:
        audit(
            request=request,
            action="EVIDENCE_ACCESS",
            resource_type="evidence",
            resource_id=evidence_id,
            outcome="rejected",
            principal=principal,
            metadata={"reason": "organization_mismatch"},
        )
        raise HTTPException(status_code=403, detail="Requested organization does not match the authenticated tenant.")
    if not evidence_id or not evidence_id.startswith("EVID-"):
        audit(
            request=request,
            action="EVIDENCE_ACCESS",
            resource_type="evidence",
            resource_id=evidence_id,
            outcome="not_found",
            principal=principal,
        )
        raise HTTPException(status_code=404, detail={"error": {"code": "EVIDENCE_NOT_FOUND", "message": "Evidence not found."}})

    with SessionLocal() as db:
        record = db.execute(
            select(EvidenceRecord).where(
                EvidenceRecord.evidence_id == evidence_id,
                EvidenceRecord.organization_id == principal.organization_id,
            )
        ).scalars().first()
        if record is None:
            audit(
                request=request,
                action="EVIDENCE_ACCESS",
                resource_type="evidence",
                resource_id=evidence_id,
                outcome="not_found",
                principal=principal,
            )
            raise HTTPException(status_code=404, detail={"error": {"code": "EVIDENCE_NOT_FOUND", "message": "Evidence not found."}})

        source_event = db.execute(
            select(IngestionEvent).where(
                IngestionEvent.event_id == record.source_event_id,
                IngestionEvent.organization_id == principal.organization_id,
            )
        ).scalars().first()
        raw_excerpt = record.raw_excerpt or ""
        integrity_verified = bool(raw_excerpt) and hashlib.sha256(raw_excerpt.encode("utf-8")).hexdigest() == record.content_hash

        response = {
            "evidence_id": record.evidence_id,
            "organization_id": record.organization_id,
            "source_type": record.source_type,
            "source_event_id": record.source_event_id,
            "event_type": source_event.event_type if source_event else None,
            "source_system": record.source_system or (source_event.source_system if source_event else None),
            "event_time": record.event_time.isoformat() if record.event_time else None,
            "observed_time": record.observed_time.isoformat() if record.observed_time else None,
            "ingested_at": record.ingested_at.isoformat() if record.ingested_at else None,
            "content_hash": record.content_hash,
            "hash_algorithm": record.hash_algorithm,
            "evidence_status": record.evidence_status,
            "reliability_tier": record.reliability_tier,
            "source_record": record.source_record,
            "integrity_verified": integrity_verified,
            "artifact_version": record.normalization_version,
        }
    audit(
        request=request,
        action="EVIDENCE_ACCESS",
        resource_type="evidence",
        resource_id=evidence_id,
        outcome="success",
        principal=principal,
    )
    return response


@app.post("/api/v1/ingest/events")
def ingest_event(
    payload: IngestEventRequest,
    request: Request,
    principal: Principal = Depends(require_roles("CONNECTOR")),
):
    enforce_rate_limit(request, principal, "ingestion", settings.rate_limit_ingest_per_minute)
    if payload.organization_id is not None and payload.organization_id != principal.organization_id:
        audit(
            request=request,
            action="EVENT_INGESTION",
            resource_type="event",
            resource_id=payload.event_id,
            outcome="rejected",
            principal=principal,
            metadata={"reason": "organization_mismatch"},
        )
        raise HTTPException(status_code=403, detail="organization_id does not match the authenticated tenant.")
    payload = payload.model_copy(update={"organization_id": principal.organization_id})
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    normalized_event_time = parse_iso_datetime(payload.event_time)
    if normalized_event_time is None:
        make_error("INVALID_EVENT", "event_time is required", request_id, 400)

    try:
        event_payload, evidence_payload, status = persist_event_and_evidence(payload, request_id)
    except Exception:  # pragma: no cover - DB failure path
        record_sandbox_event(
            organization_id=payload.organization_id,
            event_id=payload.event_id,
            event_type=payload.event_type,
            source_system=payload.source_system,
            event_time=payload.event_time,
            status="failed",
            http_status=503,
        )
        make_error("DATABASE_FAILURE", "The event could not be persisted due to a database error.", request_id, status_code=503)

    if status == "DUPLICATE":
        with SessionLocal() as db:
            row = db.execute(
                select(SourceHealth).where(
                    SourceHealth.organization_id == payload.organization_id,
                    SourceHealth.source_name == payload.source_system,
                )
            ).scalars().first()
            if row is not None:
                row.duplicate_events = (row.duplicate_events or 0) + 1
                row.updated_at = datetime.now(timezone.utc)
                db.commit()
        EVENT_STORE[payload.event_id] = {
            "event_id": payload.event_id,
            "organization_id": payload.organization_id,
            "event_type": payload.event_type,
            "source_system": payload.source_system,
            "evidence_id": event_payload["evidence_id"],
        }
        duplicate_response = JSONResponse(
            status_code=200,
            content={
                "event_id": payload.event_id,
                "status": "duplicate",
                "idempotent": True,
                "evidence_id": event_payload["evidence_id"],
                "organization_id": payload.organization_id,
                "request_id": request_id,
            },
        )
        record_sandbox_event(
            organization_id=payload.organization_id,
            event_id=payload.event_id,
            event_type=payload.event_type,
            source_system=payload.source_system,
            event_time=payload.event_time,
            status="duplicate",
            http_status=200,
            evidence_id=event_payload["evidence_id"],
        )
        audit(
            request=request,
            action="EVENT_INGESTION",
            resource_type="event",
            resource_id=payload.event_id,
            outcome="duplicate",
            principal=principal,
            metadata={"event_type": payload.event_type},
        )
        return duplicate_response

    graph_status = "GRAPH_PROJECTION_FAILED"
    with SessionLocal() as db:
        event_row = db.execute(
            select(IngestionEvent).where(
                IngestionEvent.organization_id == payload.organization_id,
                IngestionEvent.event_id == payload.event_id,
            )
        ).scalars().first()
        if event_row is None:
            make_error("DATABASE_FAILURE", "Ingestion record not found after persist", request_id, 503)
        graph_status = neo4j_client.project_event(
            {
                "event_id": event_row.event_id,
                "event_type": event_row.event_type,
                "event_time": event_row.event_time,
                "source_system": event_row.source_system,
                "organization_id": event_row.organization_id,
                "person_ref": event_row.person_ref,
                "purpose": event_row.purpose,
            },
            {
                "evidence_id": evidence_payload["evidence_id"],
                "content_hash": evidence_payload["content_hash"],
                "hash_algorithm": "SHA-256",
                "observed_time": event_row.observed_time,
            },
            event_row.payload,
        )
        event_row.projection_status = graph_status
        if graph_status == "GRAPH_PROJECTION_FAILED":
            event_row.projection_notes = "Neo4j unavailable at ingestion time"
        else:
            event_row.projection_notes = "Graph projected deterministically from ingestion event"
        db.commit()

    if payload.event_type == "CONSENT_WITHDRAWN":
        ensure_investigation_scope(payload.organization_id, payload.person_ref, payload.purpose or "UNKNOWN", normalized_event_time)
    if graph_status == "GRAPH_PROJECTED":
        recompute_affected_investigations(payload.organization_id, payload.person_ref, payload.purpose, normalized_event_time)
    accepted_response = JSONResponse(
        status_code=201,
        content={
            "event_id": payload.event_id,
            "event_type": payload.event_type,
            "status": "accepted",
            "idempotent": False,
            "evidence_id": event_payload["evidence_id"],
            "organization_id": payload.organization_id,
            "event_time": event_payload["event_time"],
            "observed_time": event_payload["event_time"],
            "ingested_time": event_payload["ingested_time"],
            "request_id": request_id,
            "projection_status": graph_status,
        },
    )
    record_sandbox_event(
        organization_id=payload.organization_id,
        event_id=payload.event_id,
        event_type=payload.event_type,
        source_system=payload.source_system,
        event_time=payload.event_time,
        status="failed" if graph_status == "GRAPH_PROJECTION_FAILED" else "accepted",
        http_status=201,
        ingested_at=event_payload["ingested_time"],
        projection_status=graph_status,
        evidence_id=event_payload["evidence_id"],
    )
    audit(
        request=request,
        action="EVENT_INGESTION",
        resource_type="event",
        resource_id=payload.event_id,
        outcome="accepted" if graph_status == "GRAPH_PROJECTED" else "projection_failed",
        principal=principal,
        metadata={"event_type": payload.event_type, "projection_status": graph_status},
    )
    return accepted_response


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str):
        normalized = value.strip().upper()
        if normalized not in ALL_ROLES:
            raise ValueError("Unsupported API key role.")
        return normalized


@app.post("/api/v1/admin/api-keys", status_code=201)
def create_api_key(
    key_request: ApiKeyCreateRequest,
    request: Request,
    principal: Principal = Depends(require_roles("ADMIN")),
):
    if key_request.role == "ADMIN" and principal.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Only an administrator can create administrator keys.")
    record, secret = create_key_record(
        organization_id=principal.organization_id,
        name=key_request.name,
        role=key_request.role,
    )
    with SessionLocal() as db:
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="An API key with this name already exists for the organization.")
        key_id = record.key_id
        role = record.role
        name = record.name
    audit(
        request=request,
        action="API_KEY_CREATE",
        resource_type="api_key",
        resource_id=key_id,
        outcome="success",
        principal=principal,
        metadata={"role": role, "name": name},
    )
    return {"key_id": key_id, "secret": secret, "role": role, "name": name}


@app.get("/api/v1/admin/api-keys")
def list_api_keys(
    request: Request,
    principal: Principal = Depends(require_roles("ADMIN")),
):
    with SessionLocal() as db:
        records = db.execute(
            select(ApiKey)
            .where(ApiKey.organization_id == principal.organization_id)
            .order_by(ApiKey.created_at, ApiKey.key_id)
        ).scalars().all()
    audit(
        request=request,
        action="API_KEY_LIST",
        resource_type="api_key",
        resource_id=None,
        outcome="success",
        principal=principal,
    )
    return [{
        "key_id": record.key_id,
        "organization_id": record.organization_id,
        "name": record.name,
        "role": record.role,
        "active": record.active,
        "created_at": record.created_at,
        "revoked_at": record.revoked_at,
        "last_used_at": record.last_used_at,
    } for record in records]


@app.post("/api/v1/admin/api-keys/{key_id}/revoke")
def revoke_api_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("ADMIN")),
):
    with SessionLocal() as db:
        record = db.execute(
            select(ApiKey).where(
                ApiKey.key_id == key_id,
                ApiKey.organization_id == principal.organization_id,
            )
        ).scalars().first()
        if record is None:
            raise HTTPException(status_code=404, detail="API key not found.")
        if record.active:
            record.active = False
            record.revoked_at = datetime.now(timezone.utc)
            db.commit()
    audit(
        request=request,
        action="API_KEY_REVOKE",
        resource_type="api_key",
        resource_id=key_id,
        outcome="success",
        principal=principal,
    )
    return {"key_id": key_id, "active": False, "revoked": True}


@app.get("/api/v1/audit-events")
def list_audit_events(
    request: Request,
    limit: int = 100,
    principal: Principal = Depends(require_permission("audit")),
):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500.")
    with SessionLocal() as db:
        rows = db.execute(
            select(SecurityAuditRecord)
            .where(SecurityAuditRecord.organization_id == principal.organization_id)
            .order_by(SecurityAuditRecord.timestamp.desc())
            .limit(limit)
        ).scalars().all()
    audit(
        request=request,
        action="AUDIT_LOG_ACCESS",
        resource_type="audit_log",
        resource_id=None,
        outcome="success",
        principal=principal,
        metadata={"limit": limit},
    )
    return [{
        "audit_id": row.audit_id,
        "organization_id": row.organization_id,
        "principal_id": row.principal_id,
        "role": row.role,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "request_id": row.request_id,
        "timestamp": row.timestamp,
        "outcome": row.outcome,
        "source_ip": row.source_ip,
        "metadata": row.metadata_json,
    } for row in rows]


def customers_for_organization(organization_id: str) -> list[dict[str, Any]]:
    if organization_id == "org-acmepay-demo":
        user_rows = load_dataset()["users"]
        return [
            {
                "customer_id": row["customer_id"],
                "name": row.get("name", row["customer_id"]),
                "synthetic_demo": True,
            }
            for row in sorted(user_rows, key=lambda item: item["customer_id"])
        ]
    with SessionLocal() as db:
        events = db.execute(
            select(IngestionEvent).where(IngestionEvent.organization_id == organization_id)
        ).scalars().all()
    customers: dict[str, dict[str, Any]] = {}
    for event in events:
        for fact in event.payload.get("investigation_facts", []):
            if fact.get("table") == "users" and isinstance(fact.get("row"), dict):
                user = fact["row"]
                customer_id = user.get("customer_id")
                if customer_id:
                    customers[customer_id] = {
                        "customer_id": customer_id,
                        "name": user.get("name", customer_id),
                        "synthetic_demo": organization_id == SANDBOX_ORGANIZATION_ID,
                    }
    return sorted(customers.values(), key=lambda item: item["customer_id"])


@app.get("/customers")
def get_customers(principal: Principal = Depends(require_permission("read"))):
    return customers_for_organization(principal.organization_id)


@app.get("/customers/{customer_id}")
def get_customer(customer_id: str, principal: Principal = Depends(require_permission("read"))):
    customer = next((row for row in customers_for_organization(principal.organization_id) if row["customer_id"] == customer_id), None)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {
        **customer,
        "synthetic_demo": True,
    }


@app.get("/purposes")
def get_purposes(principal: Principal = Depends(require_permission("read"))):
    if principal.organization_id == "org-acmepay-demo":
        purpose_set = sorted({row["purpose"] for row in load_dataset()["consent_events"]})
    else:
        with SessionLocal() as db:
            purpose_set = sorted({
                row[0] for row in db.execute(
                    select(IngestionEvent.purpose).where(
                        IngestionEvent.organization_id == principal.organization_id,
                        IngestionEvent.purpose.is_not(None),
                    )
                ).all()
            })
    if not purpose_set:
        return ["MARKETING", "ANALYTICS"]
    purpose_set = [purpose for purpose in ["ANALYTICS", "MARKETING", *purpose_set] if purpose not in {"", None}]
    unique = []
    for purpose in purpose_set:
        if purpose not in unique:
            unique.append(purpose)
    return unique


@app.get("/investigations")
def list_investigations(
    organization_id: str | None = None,
    principal: Principal = Depends(require_permission("read")),
):
    if organization_id is not None and organization_id != principal.organization_id:
        raise HTTPException(status_code=403, detail="Requested organization does not match the authenticated tenant.")
    organization_id = principal.organization_id
    with SessionLocal() as db:
        scopes = db.execute(
            select(InvestigationScope).where(InvestigationScope.organization_id == organization_id)
        ).scalars().all()
    results = []
    for scope in scopes:
        result = INVESTIGATION_STORE.get(scope.investigation_id)
        results.append({
            "investigation_id": scope.investigation_id,
            "customer_id": scope.person_ref,
            "customer_name": result.customer_name if result else scope.person_ref,
            "purpose": scope.purpose,
            "state": result.overall_investigation_state if result else scope.status,
            "first_break": result.first_break if result else None,
        })
    return results


@app.post("/investigations/withdrawal", response_model=InvestigationResult)
def create_investigation(
    investigation_request: InvestigationRequest,
    request: Request,
    principal: Principal = Depends(require_permission("investigate")),
):
    enforce_rate_limit(request, principal, "investigation", settings.rate_limit_investigation_per_minute)
    if investigation_request.organization_id is not None and investigation_request.organization_id != principal.organization_id:
        audit(
            request=request,
            action="INVESTIGATION_CREATE",
            resource_type="investigation",
            resource_id=investigation_request.customer_id,
            outcome="rejected",
            principal=principal,
            metadata={"reason": "organization_mismatch"},
        )
        raise HTTPException(status_code=403, detail="organization_id does not match the authenticated tenant.")
    try:
        result = run_persisted_investigation(
            investigation_request.customer_id,
            investigation_request.purpose,
            principal.organization_id,
        )
    except ValueError as exc:
        audit(
            request=request,
            action="INVESTIGATION_CREATE",
            resource_type="investigation",
            resource_id=investigation_request.customer_id,
            outcome="not_found",
            principal=principal,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    INVESTIGATION_STORE[result.investigation_id] = result
    audit(
        request=request,
        action="INVESTIGATION_CREATE",
        resource_type="investigation",
        resource_id=result.investigation_id,
        outcome="success",
        principal=principal,
    )
    return result


def get_tenant_scope(investigation_id: str, organization_id: str) -> InvestigationScope:
    with SessionLocal() as db:
        scope = db.execute(
            select(InvestigationScope).where(
                InvestigationScope.investigation_id == investigation_id,
                InvestigationScope.organization_id == organization_id,
            )
        ).scalars().first()
    if scope is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return scope


@app.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: str, principal: Principal = Depends(require_permission("read"))):
    get_tenant_scope(investigation_id, principal.organization_id)
    result = INVESTIGATION_STORE.get(investigation_id)
    if result is None:
        result = get_or_create_investigation(investigation_id)
    return result.model_dump()


@app.get("/investigations/{investigation_id}/finding/{asset_name}")
def finding_detail(
    investigation_id: str,
    asset_name: str,
    principal: Principal = Depends(require_permission("read")),
):
    get_tenant_scope(investigation_id, principal.organization_id)
    result = INVESTIGATION_STORE.get(investigation_id)
    if result is None:
        result = get_or_create_investigation(investigation_id)
    item = next((finding for finding in result.findings if finding.asset == asset_name), None)
    if not item:
        raise HTTPException(status_code=404, detail="Finding not found")
    return item.model_dump()


@app.get("/investigations/{investigation_id}/evidence/{evidence_id}", response_model=EvidenceDetail)
def evidence_detail(
    investigation_id: str,
    evidence_id: str,
    request: Request,
    principal: Principal = Depends(require_permission("read")),
):
    try:
        scope = get_tenant_scope(investigation_id, principal.organization_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            audit(
                request=request,
                action="EVIDENCE_ACCESS",
                resource_type="evidence",
                resource_id=evidence_id,
                outcome="not_found",
                principal=principal,
            )
        raise
    try:
        evidence = load_persisted_evidence_detail(scope.organization_id, evidence_id)
    except KeyError as exc:
        audit(
            request=request,
            action="EVIDENCE_ACCESS",
            resource_type="evidence",
            resource_id=evidence_id,
            outcome="not_found",
            principal=principal,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit(
        request=request,
        action="EVIDENCE_ACCESS",
        resource_type="evidence",
        resource_id=evidence_id,
        outcome="success",
        principal=principal,
    )
    return EvidenceDetail(**evidence)


@app.get("/investigations/{investigation_id}/graph")
def graph_path(
    investigation_id: str,
    request: Request,
    principal: Principal = Depends(require_permission("read")),
):
    scope = get_tenant_scope(investigation_id, principal.organization_id)
    result = INVESTIGATION_STORE.get(investigation_id)
    if result is None:
        result = get_or_create_investigation(investigation_id)
    dataset = load_persisted_dataset(scope.organization_id, result.customer_id, result.purpose)
    audit(
        request=request,
        action="LINEAGE_ACCESS",
        resource_type="investigation",
        resource_id=investigation_id,
        outcome="success",
        principal=principal,
    )
    return get_path_graph(result.customer_id, result.purpose, dataset).model_dump()


@app.post("/investigations/remediation", response_model=InvestigationResult)
def remediation(
    remediation_request: RemediationRequest,
    request: Request,
    principal: Principal = Depends(require_permission("investigate")),
):
    scope = get_tenant_scope(remediation_request.investigation_id, principal.organization_id)
    base = INVESTIGATION_STORE.get(remediation_request.investigation_id) or get_or_create_investigation(remediation_request.investigation_id)
    dataset = load_persisted_dataset(scope.organization_id, base.customer_id, base.purpose)
    remediated = simulate_remediation(base, dataset)
    INVESTIGATION_STORE[remediated.investigation_id] = remediated
    audit(
        request=request,
        action="REMEDIATION_SIMULATION",
        resource_type="investigation",
        resource_id=remediation_request.investigation_id,
        outcome="success",
        principal=principal,
    )
    return remediated


@app.post("/investigations/reinvestigate")
def re_investigate(
    investigation_id: str,
    request: Request,
    principal: Principal = Depends(require_permission("investigate")),
):
    scope = get_tenant_scope(investigation_id, principal.organization_id)
    base = INVESTIGATION_STORE.get(investigation_id) or get_or_create_investigation(investigation_id)
    dataset = load_persisted_dataset(scope.organization_id, base.customer_id, base.purpose)
    remediated = simulate_remediation(base, dataset)
    INVESTIGATION_STORE[remediated.investigation_id] = remediated
    audit(
        request=request,
        action="INVESTIGATION_RECOMPUTE",
        resource_type="investigation",
        resource_id=investigation_id,
        outcome="success",
        principal=principal,
    )
    return {"previous": base.model_dump(), "remediated": remediated.model_dump()}
