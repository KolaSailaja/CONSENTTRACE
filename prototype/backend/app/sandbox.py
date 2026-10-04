from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI

from app.config import settings

SANDBOX_ORGANIZATION_ID = "org-democorp-sandbox"
SANDBOX_PERSON_ID = "P-1001"
SANDBOX_PERSON_NAME = "Test Customer"
SANDBOX_PURPOSE = "MARKETING"
SANDBOX_EVENT_DELAY_SECONDS = 0.1
SANDBOX_SYSTEMS = (
    "DemoCorp Consent Service",
    "DemoCorp CRM",
    "DemoCorp Warehouse",
    "DemoCorp ETL",
    "DemoCorp Marketing Audience",
    "DemoCorp Export Service",
    "DemoCorp Processor",
)

SANDBOX_SCENARIOS = {
    "successful-withdrawal": {
        "name": "Successful Withdrawal",
        "description": "Consent and downstream suppression records arrive through the company event API.",
        "mode": "normal",
    },
    "stale-etl-snapshot": {
        "name": "Stale ETL Snapshot",
        "description": "A post-withdrawal ETL run consumes a stale consent snapshot before audience and export.",
        "mode": "stale",
    },
    "conflicting-processor-evidence": {
        "name": "Conflicting Processor Evidence",
        "description": "Processor suppression acknowledgement is followed by a later export in the same scope.",
        "mode": "conflict",
    },
    "missing-processor-evidence": {
        "name": "Missing Processor Evidence",
        "description": "An export is observed without a matching processor acknowledgement.",
        "mode": "missing",
    },
    "out-of-order-events": {
        "name": "Out-of-order Events",
        "description": "The ETL event is received before the earlier withdrawal event; evaluation follows event time.",
        "mode": "out-of-order",
    },
}


@dataclass(frozen=True)
class SandboxEvent:
    source_system: str
    event_type: str
    event_time: str
    payload: dict[str, Any]
    evidence_metadata: dict[str, Any]
    event_key: str


def _fact(table: str, row: dict[str, Any]) -> dict[str, Any]:
    return {"table": table, "row": row}


def _event(
    run_id: str,
    sequence: int,
    *,
    source_system: str,
    event_type: str,
    event_time: str,
    source_record: str,
    source_type: str,
    excerpt: str,
    evidence_status: str = "DIRECT",
    canonical_id: str | None = None,
    facts: list[dict[str, Any]] | None = None,
    extra_payload: dict[str, Any] | None = None,
    observed_time: str | None = None,
) -> SandboxEvent:
    event_key = f"{sequence:02d}-{source_record.lower().replace('_', '-')}"
    payload = {
        **(extra_payload or {}),
        "investigation_facts": facts or [],
    }
    metadata = {
        "source_type": source_type,
        "source_record": source_record,
        "raw_excerpt": excerpt,
        "evidence_status": evidence_status,
    }
    if canonical_id:
        metadata["canonical_id"] = canonical_id
    return SandboxEvent(
        source_system=source_system,
        event_type=event_type,
        event_time=event_time,
        payload={
            "event_id": f"evt-democorp-{run_id}-{event_key}",
            "event_type": event_type,
            "event_time": event_time,
            "observed_time": observed_time or event_time,
            "source_system": source_system,
            "organization_id": SANDBOX_ORGANIZATION_ID,
            "person_ref": SANDBOX_PERSON_ID,
            "purpose": SANDBOX_PURPOSE,
            "payload": payload,
            "evidence_metadata": metadata,
        },
        evidence_metadata=metadata,
        event_key=event_key,
    )


def _fact_events(run_id: str) -> list[SandboxEvent]:
    identity_time = "2026-10-02T10:00:00+05:30"
    return [
        _event(
            run_id,
            1,
            source_system="DemoCorp CRM",
            event_type="IDENTITY_MAPPED",
            event_time=identity_time,
            source_record="DEMO_IDENTITY_MAPPING",
            source_type="identity_mapping",
            canonical_id="EV-9901",
            excerpt="Synthetic DemoCorp test identity P-1001 resolved to the sandbox customer.",
            facts=[
                _fact("users", {"customer_id": SANDBOX_PERSON_ID, "name": SANDBOX_PERSON_NAME}),
                _fact("identity_mappings", {
                    "mapping_id": f"MAP-{run_id}",
                    "canonical_customer_id": SANDBOX_PERSON_ID,
                    "mapping_status": "MATCHED",
                    "source_identifier": SANDBOX_PERSON_ID,
                }),
            ],
            extra_payload={"source_identifier": SANDBOX_PERSON_ID},
        ),
        _event(
            run_id,
            2,
            source_system="DemoCorp CRM",
            event_type="LINEAGE_DEFINED",
            event_time=identity_time,
            source_record="DEMOCORP_TEST_LINEAGE",
            source_type="static_lineage",
            excerpt="DemoCorp sandbox system lineage declaration; this is not runtime processing evidence.",
            extra_payload={
                "asset": {"id": "DC-CRM", "name": "DemoCorp CRM", "type": "System"},
                "lineage_edges": [
                    {"from_id": "DC-CRM", "from_name": "DemoCorp CRM", "from_type": "System", "relationship": "feeds", "to_id": "DC-WH", "to_name": "DemoCorp Warehouse", "to_type": "Dataset"},
                    {"from_id": "DC-WH", "from_name": "DemoCorp Warehouse", "from_type": "Dataset", "relationship": "feeds", "to_id": "DC-ETL", "to_name": "DemoCorp ETL", "to_type": "PipelineJob"},
                    {"from_id": "DC-ETL", "from_name": "DemoCorp ETL", "from_type": "PipelineJob", "relationship": "builds", "to_id": "DC-AUDIENCE", "to_name": "DemoCorp Marketing Audience", "to_type": "Audience"},
                    {"from_id": "DC-AUDIENCE", "from_name": "DemoCorp Marketing Audience", "from_type": "Audience", "relationship": "exports", "to_id": "DC-EXPORT", "to_name": "DemoCorp Export Service", "to_type": "Export"},
                    {"from_id": "DC-EXPORT", "from_name": "DemoCorp Export Service", "from_type": "Export", "relationship": "sends_to", "to_id": "DC-PROCESSOR", "to_name": "DemoCorp Processor", "to_type": "Processor"},
                ],
            },
        ),
        _event(
            run_id,
            3,
            source_system="DemoCorp Consent Service",
            event_type="CONSENT_GRANTED",
            event_time=identity_time,
            source_record="CONSENT_GRANTED",
            source_type="consent_event",
            excerpt="Synthetic test customer granted MARKETING consent before the withdrawal scenario.",
            facts=[_fact("consent_events", {
                "event_id": f"evt-democorp-{run_id}-03-consent-granted",
                "customer_id": SANDBOX_PERSON_ID,
                "purpose": SANDBOX_PURPOSE,
                "status": "CONSENTED",
                "timestamp": identity_time,
                "source_system": "DemoCorp Consent Service",
            })],
            extra_payload={"consent_status": "CONSENTED"},
        ),
    ]


def _withdrawal_event(run_id: str, sequence: int = 3) -> SandboxEvent:
    event_time = "2026-10-02T10:31:42+05:30"
    event_id = f"evt-democorp-{run_id}-{sequence:02d}-consent-withdrawn"
    return _event(
        run_id,
        sequence,
        source_system="DemoCorp Consent Service",
        event_type="CONSENT_WITHDRAWN",
        event_time=event_time,
        source_record=event_id,
        source_type="consent_event",
        canonical_id="EV-0000",
        excerpt="Synthetic test customer withdrew MARKETING consent.",
        facts=[_fact("consent_events", {
            "event_id": event_id,
            "customer_id": SANDBOX_PERSON_ID,
            "purpose": SANDBOX_PURPOSE,
            "status": "WITHDRAWN",
            "timestamp": event_time,
            "source_system": "DemoCorp Consent Service",
        })],
        extra_payload={"termination_reason": "CUSTOMER_REQUEST"},
    )


def _common_after_withdrawal_events(run_id: str, start: int = 4) -> list[SandboxEvent]:
    crm_time = "2026-10-02T10:31:46+05:30"
    warehouse_time = "2026-10-02T10:34:12+05:30"
    return [
        _event(
            run_id,
            start,
            source_system="DemoCorp CRM",
            event_type="PREFERENCE_UPDATED",
            event_time=crm_time,
            source_record="CRM_PREFERENCE_UPDATED",
            source_type="crm_audit",
            canonical_id="EV-1002",
            excerpt="DemoCorp CRM set MARKETING preference to false after withdrawal.",
            extra_payload={"preference": "opted_out"},
        ),
        _event(
            run_id,
            start + 1,
            source_system="DemoCorp Warehouse",
            event_type="PROCESSING_COMPLETED",
            event_time=warehouse_time,
            source_record="WAREHOUSE_REFRESH",
            source_type="warehouse_refresh_log",
            canonical_id="EV-1003",
            excerpt="DemoCorp Warehouse refreshed its consent dimension and excluded P-1001.",
            facts=[_fact("processing_logs", {
                "log_id": f"WH-{run_id}",
                "run_id": f"WH-RUN-{run_id}",
                "job_id": "WAREHOUSE_REFRESH",
                "timestamp": warehouse_time,
                "operation": "CONSENT_DIMENSION_REFRESH",
                "customer_id": SANDBOX_PERSON_ID,
                "purpose": SANDBOX_PURPOSE,
                "status": "SUCCESS",
            })],
            extra_payload={"dataset_id": "DC-WH"},
        ),
    ]


def _stale_etl_event(run_id: str, sequence: int = 6) -> SandboxEvent:
    event_time = "2026-10-02T10:45:03+05:30"
    return _event(
        run_id,
        sequence,
        source_system="DemoCorp ETL",
        event_type="DATASET_READ",
        event_time=event_time,
        source_record="USE_STALE_CONSENT_SNAPSHOT",
        source_type="job_warning",
        canonical_id="EV-2002",
        excerpt="DemoCorp ETL used a stale consent snapshot for P-1001 after withdrawal.",
        evidence_status="STALE",
        facts=[_fact("processing_logs", {
            "log_id": f"ETL-{run_id}",
            "run_id": f"ETL-RUN-{run_id}",
            "job_id": "ETL_17",
            "timestamp": event_time,
            "operation": "USE_STALE_CONSENT_SNAPSHOT",
            "customer_id": SANDBOX_PERSON_ID,
            "purpose": SANDBOX_PURPOSE,
            "status": "WARNING",
        })],
        extra_payload={"dataset_id": "DC-WH"},
    )


def _audience_event(run_id: str, sequence: int = 7, *, removed: bool = False) -> SandboxEvent:
    event_time = "2026-10-02T10:45:12+05:30" if not removed else "2026-10-02T11:05:00+05:30"
    return _event(
        run_id,
        sequence,
        source_system="DemoCorp Marketing Audience",
        event_type="AUDIENCE_MEMBER_REMOVED" if removed else "AUDIENCE_MEMBER_ADDED",
        event_time=event_time,
        source_record="AUDIENCE_MEMBER_REMOVED" if removed else "AUDIENCE_MEMBER_ADDED",
        source_type="audience_suppression" if removed else "audience_membership",
        canonical_id="EV-3001" if not removed else None,
        excerpt=(
            "DemoCorp Marketing Audience removed P-1001 after withdrawal through a recorded suppression."
            if removed else "DemoCorp Marketing Audience added P-1001 after withdrawal."
        ),
        facts=[_fact("audience_membership", {
            "membership_id": f"MEM-{run_id}-{'REM' if removed else 'ADD'}",
            "audience_id": "marketing_audience",
            "customer_id": SANDBOX_PERSON_ID,
            "purpose": SANDBOX_PURPOSE,
            "observed_at": event_time,
            "source_run_id": f"AUDIENCE-{run_id}",
            "status": "REMOVED" if removed else "ADDED",
        })],
        extra_payload={"audience_id": "marketing_audience"},
    )


def _export_event(run_id: str, sequence: int = 8, *, event_time: str = "2026-10-02T10:47:03+05:30") -> SandboxEvent:
    export_id = f"EXP-DEMOCORP-{run_id}"
    return _event(
        run_id,
        sequence,
        source_system="DemoCorp Export Service",
        event_type="EXPORT_SENT",
        event_time=event_time,
        source_record="EXPORT_SENT",
        source_type="export_log",
        canonical_id="EV-4001",
        excerpt=f"DemoCorp Export Service sent P-1001 to DemoCorp Processor in export {export_id}.",
        facts=[_fact("export_logs", {
            "export_id": export_id,
            "customer_id": SANDBOX_PERSON_ID,
            "purpose": SANDBOX_PURPOSE,
            "dataset_id": "DC-AUDIENCE",
            "processor_id": "PROC-DEMOCORP",
            "timestamp": event_time,
            "operation": "EXPORT",
            "status": "SENT",
        })],
        extra_payload={"export_id": export_id},
    )


def _missing_ack_event(run_id: str, sequence: int = 9) -> SandboxEvent:
    event_time = "2026-10-02T10:48:00+05:30"
    return _event(
        run_id,
        sequence,
        source_system="DemoCorp Export Service",
        event_type="EVIDENCE_OBSERVED",
        event_time=event_time,
        source_record="PROCESSOR_ACK_MISSING",
        source_type="bounded_acknowledgement_observation",
        canonical_id="EV-4002",
        evidence_status="ABSENT",
        excerpt="No processor acknowledgement was observed for this export at the recorded cutoff.",
    )


def _suppression_ack_event(run_id: str, sequence: int = 9) -> SandboxEvent:
    event_time = "2026-10-02T10:50:00+05:30"
    export_id = f"EXP-DEMOCORP-{run_id}"
    return _event(
        run_id,
        sequence,
        source_system="DemoCorp Processor",
        event_type="SUPPRESSION_COMPLETED",
        event_time=event_time,
        source_record="SUPPRESSION_COMPLETED",
        source_type="processor_acknowledgement",
        excerpt="DemoCorp Processor confirmed suppression for the scoped export.",
        facts=[_fact("processor_acknowledgements", {
            "ack_id": f"ACK-{run_id}",
            "processor_id": "PROC-DEMOCORP",
            "customer_id": SANDBOX_PERSON_ID,
            "purpose": SANDBOX_PURPOSE,
            "action": "ACKNOWLEDGED",
            "timestamp": event_time,
            "status": "RECEIVED",
            "export_id": export_id,
        })],
        extra_payload={"audience_id": "marketing_audience", "processor_id": "PROC-DEMOCORP"},
    )


def _successful_ack_event(run_id: str, sequence: int = 8) -> SandboxEvent:
    event_time = "2026-10-02T11:12:00+05:30"
    return _event(
        run_id,
        sequence,
        source_system="DemoCorp Processor",
        event_type="PROCESSOR_ACKNOWLEDGED",
        event_time=event_time,
        source_record="PROCESSOR_ACKNOWLEDGED",
        source_type="processor_acknowledgement",
        canonical_id="EV-4004",
        excerpt="DemoCorp Processor acknowledged the sandbox suppression request.",
        facts=[_fact("processor_acknowledgements", {
            "ack_id": f"ACK-{run_id}",
            "processor_id": "PROC-DEMOCORP",
            "customer_id": SANDBOX_PERSON_ID,
            "purpose": SANDBOX_PURPOSE,
            "action": "ACKNOWLEDGED",
            "timestamp": event_time,
            "status": "RECEIVED",
            "export_id": f"EXP-DEMOCORP-{run_id}",
        })],
        extra_payload={"processor_id": "PROC-DEMOCORP"},
    )


def build_scenario_events(scenario_id: str, run_id: str | None = None) -> tuple[str, list[SandboxEvent]]:
    scenario = SANDBOX_SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError(f"Unknown sandbox scenario '{scenario_id}'.")
    run_id = run_id or uuid.uuid4().hex
    mode = scenario["mode"]
    events = _fact_events(run_id)

    if mode == "normal":
        events.extend([
            _withdrawal_event(run_id, 4),
            *(_common_after_withdrawal_events(run_id, 5)),
            _audience_event(run_id, 7, removed=True),
            _successful_ack_event(run_id, 8),
        ])
    elif mode in {"stale", "out-of-order"}:
        stale = _stale_etl_event(run_id)
        audience = _audience_event(run_id)
        export = _export_event(run_id)
        missing = _missing_ack_event(run_id)
        if mode == "out-of-order":
            events.extend([stale, _withdrawal_event(run_id, 4), *_common_after_withdrawal_events(run_id, 5), audience, export, missing])
        else:
            events.extend([_withdrawal_event(run_id, 4), *_common_after_withdrawal_events(run_id, 5), stale, audience, export, missing])
    elif mode == "conflict":
        events.extend([
            _withdrawal_event(run_id, 4),
            *_common_after_withdrawal_events(run_id, 5),
            _suppression_ack_event(run_id),
            _export_event(run_id, event_time="2026-10-02T10:55:00+05:30"),
        ])
    else:
        events.extend([_withdrawal_event(run_id, 4), *_common_after_withdrawal_events(run_id, 5), _export_event(run_id, 7), _missing_ack_event(run_id, 8)])

    return run_id, events


class DemoCorpSystemAdapter:
    def __init__(self, source_system: str, app: FastAPI) -> None:
        if source_system not in SANDBOX_SYSTEMS:
            raise ValueError(f"Unregistered sandbox system '{source_system}'.")
        self.source_system = source_system
        self.app = app

    async def emit(self, event: SandboxEvent) -> httpx.Response:
        if event.source_system != self.source_system:
            raise ValueError("Sandbox adapters may only emit events for their registered source system.")
        if not settings.sandbox_connector_api_key:
            raise RuntimeError("SANDBOX_CONNECTOR_API_KEY is required for authenticated sandbox ingestion.")
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://consenttrace-sandbox") as client:
            return await client.post(
                "/api/v1/ingest/events",
                json=event.payload,
                headers={"Authorization": f"Bearer {settings.sandbox_connector_api_key}"},
            )


async def run_scenario(scenario_id: str, app: FastAPI) -> dict[str, Any]:
    run_id, events = build_scenario_events(scenario_id)
    results: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        adapter = DemoCorpSystemAdapter(event.source_system, app)
        response = await adapter.emit(event)
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text[:500]}

        if response.status_code == 201:
            status = "accepted"
        elif response.status_code == 200 and body.get("idempotent") is True:
            status = "duplicate"
        elif 400 <= response.status_code < 500:
            status = "rejected"
        else:
            status = "failed"

        item = {
            "event_id": event.payload["event_id"],
            "event_type": event.event_type,
            "source_system": event.source_system,
            "event_time": event.event_time,
            "ingested_at": body.get("ingested_time") or body.get("ingested_at"),
            "status": status,
            "http_status": response.status_code,
            "projection_status": body.get("projection_status"),
            "evidence_id": body.get("evidence_id"),
            "message": body.get("error", {}).get("message") or body.get("detail"),
        }
        results.append(item)

        if status in {"rejected", "failed"}:
            return {
                "run_id": run_id,
                "scenario_id": scenario_id,
                "scenario_name": SANDBOX_SCENARIOS[scenario_id]["name"],
                "status": "failed",
                "events": results,
            }
        if body.get("projection_status") == "GRAPH_PROJECTION_FAILED":
            item["status"] = "failed"
            item["message"] = "Event persisted, but Neo4j projection failed."
            return {
                "run_id": run_id,
                "scenario_id": scenario_id,
                "scenario_name": SANDBOX_SCENARIOS[scenario_id]["name"],
                "status": "failed",
                "events": results,
            }
        if index < len(events) - 1:
            await asyncio.sleep(SANDBOX_EVENT_DELAY_SECONDS)

    if scenario_id == "stale-etl-snapshot":
        export_event = next(event for event in events if event.event_type == "EXPORT_SENT")
        adapter = DemoCorpSystemAdapter(export_event.source_system, app)
        duplicate_response = await adapter.emit(export_event)
        duplicate_body = duplicate_response.json()
        results.append({
            "event_id": export_event.payload["event_id"],
            "event_type": export_event.event_type,
            "source_system": export_event.source_system,
            "event_time": export_event.event_time,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "status": "duplicate" if duplicate_body.get("idempotent") is True else "failed",
            "http_status": duplicate_response.status_code,
            "projection_status": None,
            "evidence_id": duplicate_body.get("evidence_id"),
            "message": "Same event retried to verify idempotency.",
        })

    if any(item["status"] in {"rejected", "failed"} for item in results):
        return {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "scenario_name": SANDBOX_SCENARIOS[scenario_id]["name"],
            "status": "failed",
            "events": results,
        }
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_name": SANDBOX_SCENARIOS[scenario_id]["name"],
        "status": "completed",
        "events": results,
    }
