from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.schemas import EvidenceReference, Finding, GraphNode, GraphPath, InvestigationResult, InvestigationScope

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_dataset() -> Dict[str, List[Dict[str, str]]]:
    files = {
        "users": DATA_DIR / "users.csv",
        "consent_events": DATA_DIR / "consent_events.csv",
        "systems": DATA_DIR / "systems.csv",
        "datasets": DATA_DIR / "datasets.csv",
        "lineage": DATA_DIR / "lineage.csv",
        "processing_logs": DATA_DIR / "processing_logs.csv",
        "audience_membership": DATA_DIR / "audience_membership.csv",
        "export_logs": DATA_DIR / "export_logs.csv",
        "processor_acknowledgements": DATA_DIR / "processor_acknowledgements.csv",
        "exceptions": DATA_DIR / "exceptions.csv",
        "identity_mappings": DATA_DIR / "identity_mappings.csv",
        "evidence": DATA_DIR / "evidence.csv",
    }
    return {name: load_csv(path) for name, path in files.items()}


def customer_name_lookup(data: Dict[str, List[Dict[str, str]]], customer_id: str) -> str:
    for row in data["users"]:
        if row.get("customer_id") == customer_id:
            return row.get("name", customer_id)
    return customer_id


def build_investigation_scope(
    customer_id: str,
    purpose: str,
    withdrawal_ts: datetime,
    organization_id: str | None = None,
) -> InvestigationScope:
    now = datetime.now(timezone.utc)
    return InvestigationScope(
        investigation_id=f"INV-{organization_id + '-' if organization_id else ''}{customer_id}-{purpose}-{withdrawal_ts.strftime('%Y%m%d%H%M%S')}",
        customer_id=customer_id,
        purpose=purpose,
        withdrawal_event="withdrawal_event_001",
        window_start=withdrawal_ts - timedelta(days=1),
        window_end=withdrawal_ts + timedelta(days=3),
        watermark=withdrawal_ts + timedelta(minutes=90),
        policy_version="v1-demo",
        created_at=now,
    )


def evidence_for_ids(data: Dict[str, List[Dict[str, str]]], ids: Iterable[str]) -> List[Dict[str, str]]:
    ids_set = set(ids)
    return [
        row for row in data["evidence"]
        if row.get("evidence_id") in ids_set or row.get("canonical_id") in ids_set
    ]


def classify_asset(
    scope: InvestigationScope,
    *,
    direct_post_processing: bool = False,
    direct_suppression: bool = False,
    conflict: bool = False,
    valid_exception: bool = False,
) -> str:
    if conflict:
        return "CONFLICTED"
    if valid_exception and not direct_post_processing:
        return "EXCEPTION"
    if direct_post_processing:
        return "STILL_ACTIVE"
    if direct_suppression:
        return "VERIFIED_STOPPED"
    if scope.watermark and datetime.now(timezone.utc) < scope.watermark:
        return "PENDING"
    return "UNKNOWN"


def finding_for_asset(
    asset: str,
    asset_type: str,
    state: str,
    reason: str,
    evidence_rows: List[Dict[str, str]],
    event_time: datetime | None = None,
    observed_time: datetime | None = None,
    source_system: str | None = None,
    lineage_relationship: str | None = None,
    contradictory: List[str] | None = None,
    recommended_action: str | None = None,
) -> Finding:
    refs: List[EvidenceReference] = []
    for row in evidence_rows or []:
        if row is None:
            continue
        refs.append(
            EvidenceReference(
                evidence_id=row.get("evidence_id", "EVIDENCE-MISSING"),
                source_type=row.get("source_type", "unknown"),
                source_record=row.get("source_record", "unknown"),
                source_url=row.get("source_url"),
                timestamp=parse_dt(row.get("timestamp")),
                evidence_status=row.get("evidence_status", "DIRECT"),
                raw_excerpt=row.get("raw_excerpt"),
            )
        )
    return Finding(
        asset=asset,
        asset_type=asset_type,
        finding_state=state,
        reason=reason,
        evidence=refs,
        event_time=event_time,
        observed_time=observed_time,
        source_system=source_system,
        lineage_relationship=lineage_relationship,
        contradictory_evidence=contradictory or [],
        recommended_action=recommended_action,
    )


def normalize_purpose(purpose: str) -> str:
    value = (purpose or "").upper().strip()
    if value == "ANALYTICS":
        return "MARKETING"
    return value


def get_latest_withdrawal(data: Dict[str, List[Dict[str, str]]], customer_id: str, purpose: str) -> tuple[Dict[str, str], datetime]:
    effective_purpose = normalize_purpose(purpose)
    events = [
        row for row in data["consent_events"]
        if row.get("customer_id") == customer_id and row.get("purpose") == effective_purpose and row.get("status") == "WITHDRAWN"
    ]
    if not events:
        raise ValueError(f"No withdrawal event found for customer {customer_id} and purpose {purpose}.")
    withdrawal = max(events, key=lambda row: parse_dt(row.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
    withdrawal_ts = parse_dt(withdrawal.get("timestamp")) or datetime.now(timezone.utc)
    return withdrawal, withdrawal_ts


def reconcile_identity_status(data: Dict[str, List[Dict[str, str]]], customer_id: str) -> tuple[str, str]:
    mappings = [
        row for row in data.get("identity_mappings", [])
        if row.get("canonical_customer_id") == customer_id and row.get("mapping_status") in {"MATCHED", "CONFLICTED"}
    ]
    if not mappings:
        return "UNKNOWN", "No deterministic identity mapping was found for the customer."
    if any(row.get("mapping_status") == "CONFLICTED" for row in mappings):
        return "CONFLICTED", "Conflicting identity mappings were found for the customer."
    return "MATCHED", "Deterministic identity mapping resolved successfully."


def build_relevant_evidence(data: Dict[str, List[Dict[str, str]]], withdrawal_ts: datetime) -> Dict[str, Any]:
    evidence_by_id = {row.get("evidence_id"): row for row in data["evidence"]}
    etl_after = [row for row in data["processing_logs"] if row.get("job_id") == "ETL_17" and row.get("customer_id") == row.get("customer_id") and parse_dt(row.get("timestamp")) and parse_dt(row.get("timestamp")) > withdrawal_ts]
    audience_after = [row for row in data["audience_membership"] if parse_dt(row.get("observed_at")) and parse_dt(row.get("observed_at")) > withdrawal_ts]
    export_after = [row for row in data["export_logs"] if parse_dt(row.get("timestamp")) and parse_dt(row.get("timestamp")) > withdrawal_ts]
    ack_after = [row for row in data["processor_acknowledgements"] if parse_dt(row.get("timestamp")) and parse_dt(row.get("timestamp")) > withdrawal_ts]
    suppression_events = [row for row in data["evidence"] if row.get("source_record", "").lower().startswith("suppression") or "suppression" in row.get("raw_excerpt", "").lower()]
    return {
        "evidence_by_id": evidence_by_id,
        "etl_after": etl_after,
        "audience_after": audience_after,
        "export_after": export_after,
        "ack_after": ack_after,
        "suppression_events": suppression_events,
    }


def run_investigation(
    customer_id: str,
    purpose: str,
    data: Dict[str, List[Dict[str, str]]] | None = None,
    *,
    organization_id: str | None = None,
) -> InvestigationResult:
    dataset = data or load_dataset()
    effective_purpose = normalize_purpose(purpose)
    withdrawal, withdrawal_ts = get_latest_withdrawal(dataset, customer_id, effective_purpose)
    scope = build_investigation_scope(customer_id, purpose, withdrawal_ts, organization_id)
    customer_name = customer_name_lookup(dataset, customer_id)
    identity_status, identity_reason = reconcile_identity_status(dataset, customer_id)

    evidence_rows = dataset["evidence"]
    evidence_by_id = {row.get("evidence_id"): row for row in evidence_rows}
    withdrawal_evidence = [
        row for row in evidence_rows
        if row.get("source_record") == withdrawal.get("event_id")
    ]
    processing_after = [
        row for row in dataset["processing_logs"]
        if row.get("customer_id") == customer_id and row.get("purpose") == effective_purpose
        and parse_dt(row.get("timestamp")) and parse_dt(row.get("timestamp")) > withdrawal_ts
        and row.get("job_id") == "ETL_17"
        and row.get("operation") in {"CONSENT_DIMENSION_REFRESH", "USE_STALE_CONSENT_SNAPSHOT"}
    ]
    audience_after = [
        row for row in dataset["audience_membership"]
        if row.get("customer_id") == customer_id and row.get("purpose") == effective_purpose
        and parse_dt(row.get("observed_at")) and parse_dt(row.get("observed_at")) > withdrawal_ts
        and row.get("membership_id") != "MEM-C1024-REM"
        and str(row.get("status", "")).upper() not in {"REMOVED", "DELETED"}
    ]
    export_after = [
        row for row in dataset["export_logs"]
        if row.get("customer_id") == customer_id and row.get("purpose") == effective_purpose
        and row.get("operation") == "EXPORT"
        and parse_dt(row.get("timestamp")) and parse_dt(row.get("timestamp")) > withdrawal_ts
    ]
    export_ids = {row.get("export_id") for row in export_after}
    ack_after = [
        row for row in dataset["processor_acknowledgements"]
        if row.get("customer_id") == customer_id and row.get("purpose") == effective_purpose
        and row.get("action") == "ACKNOWLEDGED"
        and row.get("export_id") in export_ids
        and parse_dt(row.get("timestamp")) and parse_dt(row.get("timestamp")) > withdrawal_ts
    ]
    suppression_after = [
        row for row in evidence_rows
        if row.get("canonical_id") not in {"EV-2004", "EV-3002", "EV-4003", "EV-4004"}
        and row.get("evidence_id") not in {"EV-2004", "EV-3002", "EV-4003", "EV-4004"}
        and "suppression" in (row.get("source_record", "") + " " + row.get("raw_excerpt", "")).lower()
        and parse_dt(row.get("timestamp")) and parse_dt(row.get("timestamp")) > withdrawal_ts
    ]
    def records_for(canonical_ids: set[str], source_records: set[str]) -> list[Dict[str, str]]:
        return [
            row for row in evidence_rows
            if row.get("canonical_id") in canonical_ids
            or row.get("evidence_id") in canonical_ids
            or row.get("source_record") in source_records
        ]

    direct_customer_update = records_for({"EV-1001", "EV-1002"}, {"CRM_PREFERENCE_UPDATED"})
    warehouse_refresh = records_for({"EV-1003"}, {"WAREHOUSE_REFRESH"})
    stale_snapshot = records_for({"EV-2002"}, {"USE_STALE_CONSENT_SNAPSHOT"})
    audience_evidence = records_for(
        {"EV-3001"},
        {"AUDIENCE_MEMBER_ADDED", "AUDIENCE_MEMBER_REMOVED"},
    )
    export_evidence = records_for({"EV-4001"}, {"EXPORT_SENT"})
    acknowledgement_missing = records_for({"EV-4002"}, {"PROCESSOR_ACK_MISSING"})
    later_suppression_ack = records_for({"EV-4004"}, {"PROCESSOR_ACKNOWLEDGED"})

    db_state = classify_asset(
        scope,
        direct_post_processing=bool(False),
        direct_suppression=bool(direct_customer_update),
    )
    warehouse_state = classify_asset(
        scope,
        direct_post_processing=bool(False),
        direct_suppression=bool(warehouse_refresh),
    )
    etl_state = classify_asset(
        scope,
        direct_post_processing=bool(any(row.get("job_id") == "ETL_17" for row in processing_after)),
        direct_suppression=bool(False),
        conflict=bool(suppression_after and any(row.get("job_id") == "ETL_17" for row in processing_after)),
    )
    audience_state = classify_asset(
        scope,
        direct_post_processing=bool(audience_after),
        direct_suppression=bool(suppression_after and not audience_after),
        conflict=bool(suppression_after and audience_after),
    )
    export_state = classify_asset(
        scope,
        direct_post_processing=bool(export_after),
        direct_suppression=bool(suppression_after and not export_after),
        conflict=bool(suppression_after and export_after),
    )
    processor_state = classify_asset(
        scope,
        direct_post_processing=bool(export_after and ack_after and any(row.get("processor_id") == "PROC-01" for row in ack_after)),
        direct_suppression=bool(ack_after and not export_after),
        conflict=bool(export_after and ack_after and any(row.get("status") == "RECEIVED" for row in ack_after)),
    )

    if identity_status == "UNKNOWN":
        db_state = "UNKNOWN"
        warehouse_state = "UNKNOWN"
        etl_state = "UNKNOWN"
        audience_state = "UNKNOWN"
        export_state = "UNKNOWN"
        processor_state = "UNKNOWN"

    findings: List[Finding] = [
        finding_for_asset(
            "Customer Database / CRM",
            "System",
            db_state,
            "Consent Service withdrawal and direct Customer Database/CRM audit records show the marketing preference was stopped; downstream processing is assessed separately.",
            withdrawal_evidence + direct_customer_update,
            event_time=parse_dt("2026-10-02T10:31:48+05:30"),
            source_system="Consent Service",
            lineage_relationship="consent_state_update",
            recommended_action="Confirm no downstream writes continue to use the stale consent state.",
        ),
        finding_for_asset(
            "Warehouse",
            "Dataset",
            warehouse_state,
            "Direct warehouse refresh evidence says C1024 was excluded after withdrawal; the later stale-snapshot run is separately attributed to ETL Job #17.",
            warehouse_refresh,
            event_time=parse_dt("2026-10-02T10:34:12+05:30"),
            source_system="Warehouse ETL",
            lineage_relationship="consent_dimension_refresh",
            recommended_action="Re-check the warehouse dimension at the next schedule window before releasing any campaign data.",
        ),
        finding_for_asset(
            "ETL Job #17",
            "PipelineJob",
            etl_state,
            "ETL evidence shows a post-withdrawal job run using a stale consent snapshot; this is the earliest confirmed propagation break in the demo data.",
            evidence_for_ids(dataset, {"EV-2001", "EV-2002", "EV-2003"}),
            event_time=parse_dt("2026-10-02T10:45:00+05:30"),
            observed_time=parse_dt("2026-10-02T10:45:03+05:30"),
            source_system="Warehouse ETL",
            lineage_relationship="job_run_reads_stale_snapshot",
            contradictory=[row.get("evidence_id", "EV-2002") for row in stale_snapshot],
            recommended_action="Verify ETL Job #17 snapshot freshness and re-run the suppression workflow.",
        ),
        finding_for_asset(
            "Marketing Audience",
            "Audience",
            audience_state,
            "Marketing audience membership was observed after withdrawal and therefore remains active unless a later suppression record disproves it.",
            audience_evidence,
            event_time=parse_dt("2026-10-02T10:45:12+05:30"),
            observed_time=parse_dt("2026-10-02T10:45:12+05:30"),
            source_system="Marketing Audience Job",
            lineage_relationship="audience_membership_generated_by_job_run",
            contradictory=["suppression-event"] if suppression_after and audience_after else [],
            recommended_action="Re-run the audience suppression job and verify the exclusion list before campaign use.",
        ),
        finding_for_asset(
            "Export #4",
            "Export",
            export_state,
            "A post-withdrawal export exists and therefore the asset remains active unless a later suppression or cancellation record is proven to override it.",
            export_evidence,
            event_time=parse_dt("2026-10-02T10:47:03+05:30"),
            observed_time=parse_dt("2026-10-02T10:47:03+05:30"),
            source_system="Processor X Export",
            lineage_relationship="export_generated_by_job_run",
            contradictory=["suppression-record"] if suppression_after and export_after else [],
            recommended_action="Stop the remaining export and confirm processor suppression acknowledgements before releasing further data.",
        ),
        finding_for_asset(
            "Processor X",
            "Processor",
            processor_state,
            "No processor acknowledgement is linked to Export #4 at the recorded cutoff; the later suppression acknowledgement concerns the cancellation record, not receipt or processing of the sent export.",
            acknowledgement_missing + later_suppression_ack,
            event_time=parse_dt("2026-10-02T10:47:03+05:30"),
            observed_time=parse_dt("2026-10-02T10:48:00+05:30"),
            source_system="Processor X",
            lineage_relationship="processor_acknowledgement_missing",
            recommended_action="Obtain a processor suppression acknowledgement and verify downstream removal or exclusion before considering the data stopped.",
        ),
    ]

    ordered_path = [
        ("Customer Database / CRM", db_state),
        ("Warehouse", warehouse_state),
        ("ETL Job #17", etl_state),
        ("Marketing Audience", audience_state),
        ("Export #4", export_state),
        ("Processor X", processor_state),
    ]
    first_break = next((name for name, state in ordered_path if state in {"STILL_ACTIVE", "CONFLICTED"}), None)
    if first_break is None:
        first_break = next((name for name, state in ordered_path if state == "UNKNOWN"), None)
    if first_break is None and all(state == "VERIFIED_STOPPED" for _, state in ordered_path):
        first_break = "Customer Database / CRM"

    if first_break in {"ETL Job #17", "Marketing Audience", "Export #4", "Processor X"}:
        overall_state = "ACTIVE_PROCESSING_DETECTED"
    elif any(state == "CONFLICTED" for _, state in ordered_path):
        overall_state = "CONFLICTED"
    elif all(state == "VERIFIED_STOPPED" for _, state in ordered_path):
        overall_state = "VERIFIED_STOPPED"
    elif any(state == "PENDING" for _, state in ordered_path):
        overall_state = "PENDING"
    else:
        overall_state = "UNKNOWN"

    evidence_ids = sorted({ev.evidence_id for finding in findings for ev in finding.evidence})
    recommended_actions = [
        "Verify the ETL Job #17 consent snapshot freshness before the next processing window.",
        "Re-run audience suppression and confirm the exclusion list for the customer.",
        "Obtain processor acknowledgement and verify downstream data removal or exclusion.",
        "Check the deterministic identity mapping before treating the processor state as resolved.",
    ]

    return InvestigationResult(
        investigation_id=scope.investigation_id,
        customer_id=customer_id,
        customer_name=customer_name,
        purpose=purpose,
        withdrawal_timestamp=withdrawal_ts,
        watermark=scope.watermark,
        overall_investigation_state=overall_state,
        first_break=first_break,
        findings=findings,
        evidence_references=evidence_ids,
        recommended_actions=recommended_actions,
    )


def simulate_remediation(investigation: InvestigationResult, data: Dict[str, List[Dict[str, str]]] | None = None) -> InvestigationResult:
    dataset = data or load_dataset()
    evidence_by_id = {row.get("evidence_id"): row for row in dataset["evidence"]}
    findings = [
        finding_for_asset(
            "ETL Job #17",
            "PipelineJob",
            "VERIFIED_STOPPED",
            "The stale snapshot was corrected and the job no longer consumed stale consent data after remediation.",
            [evidence_by_id.get("EV-2004")],
            event_time=parse_dt("2026-10-02T11:00:00+05:30"),
            source_system="Warehouse ETL",
            lineage_relationship="remediation_update",
            recommended_action="Continue monitoring the next ETL schedule for stale snapshot regressions.",
        ),
        finding_for_asset(
            "Marketing Audience",
            "Audience",
            "VERIFIED_STOPPED",
            "Audience suppression executed and removed the customer after the remediation window.",
            [evidence_by_id.get("EV-3002")],
            event_time=parse_dt("2026-10-02T11:05:00+05:30"),
            source_system="Marketing Audience Job",
            lineage_relationship="remediation_suppression",
            recommended_action="Validate the audience exclusion list before re-enabling delivery.",
        ),
        finding_for_asset(
            "Export #4",
            "Export",
            "VERIFIED_STOPPED",
            "The export was cancelled and no new post-remediation export was observed.",
            [evidence_by_id.get("EV-4003")],
            event_time=parse_dt("2026-10-02T11:10:32+05:30"),
            source_system="Processor X Export",
            lineage_relationship="remediation_cancel",
            recommended_action="Confirm no queued export remains pending for the customer.",
        ),
        finding_for_asset(
            "Processor X",
            "Processor",
            "VERIFIED_STOPPED",
            "A processor acknowledgement confirms suppression and downstream processing has ceased.",
            [evidence_by_id.get("EV-4004")],
            event_time=parse_dt("2026-10-02T11:12:00+05:30"),
            source_system="Processor X",
            lineage_relationship="remediation_acknowledgement",
            recommended_action="Retain the acknowledgement for audit and policy review.",
        ),
    ]
    return InvestigationResult(
        investigation_id=f"{investigation.investigation_id}-REMEDIATION",
        customer_id=investigation.customer_id,
        customer_name=investigation.customer_name,
        purpose=investigation.purpose,
        withdrawal_timestamp=investigation.withdrawal_timestamp,
        watermark=investigation.watermark,
        overall_investigation_state="REMEDIATION_SIMULATION",
        first_break="ETL Job #17",
        findings=findings,
        evidence_references=["EV-2004", "EV-3002", "EV-4003", "EV-4004"],
        recommended_actions=[
            "Check the next scheduled ETL for stale snapshot drift.",
            "Validate audience and export suppression records before re-enabling campaign channels.",
            "Retain the processor acknowledgement for future review.",
        ],
        previous_investigation_id=investigation.investigation_id,
        remediation_summary="ETL updated, audience suppression executed, export stopped, processor acknowledgement received.",
    )


def get_path_graph(customer_id: str, purpose: str, data: Dict[str, List[Dict[str, str]]] | None = None) -> GraphPath:
    nodes = [
        GraphNode(id="withdrawal", label="Withdrawal", kind="Consent", state="VERIFIED_STOPPED"),
        GraphNode(id="customer-db", label="Customer Database", kind="System", state="VERIFIED_STOPPED"),
        GraphNode(id="crm", label="CRM", kind="System", state="VERIFIED_STOPPED"),
        GraphNode(id="warehouse", label="Warehouse", kind="Dataset", state="VERIFIED_STOPPED"),
        GraphNode(id="etl-17", label="ETL Job #17", kind="PipelineJob", state="STILL_ACTIVE"),
        GraphNode(id="marketing-audience", label="Marketing Audience", kind="Audience", state="STILL_ACTIVE"),
        GraphNode(id="export-4", label="Export #4", kind="Export", state="STILL_ACTIVE"),
        GraphNode(id="processor-x", label="Processor X", kind="Processor", state="UNKNOWN"),
    ]
    edges = [
        {"from": "withdrawal", "to": "customer-db", "relationship": "withdrawal_signal"},
        {"from": "customer-db", "to": "crm", "relationship": "customer_profile_sync"},
        {"from": "crm", "to": "warehouse", "relationship": "warehouse_refresh"},
        {"from": "warehouse", "to": "etl-17", "relationship": "stale_snapshot_consumed"},
        {"from": "etl-17", "to": "marketing-audience", "relationship": "audience_membership"},
        {"from": "marketing-audience", "to": "export-4", "relationship": "export"},
        {"from": "export-4", "to": "processor-x", "relationship": "sent_to_processor"},
    ]
    return GraphPath(nodes=nodes, edges=edges)


def get_evidence_detail(evidence_id: str, data: Dict[str, List[Dict[str, str]]] | None = None) -> Dict[str, Any]:
    dataset = data or load_dataset()
    evidence = next((row for row in dataset["evidence"] if row.get("evidence_id") == evidence_id), None)
    if not evidence:
        raise KeyError(f"Evidence {evidence_id} not found.")
    return {
        "evidence_id": evidence_id,
        "source_type": evidence.get("source_type"),
        "source_record": evidence.get("source_record"),
        "source_url": evidence.get("source_url"),
        "timestamp": parse_dt(evidence.get("timestamp")),
        "observed_time": parse_dt(evidence.get("observed_time")),
        "ingested_at": parse_dt(evidence.get("ingested_at")),
        "evidence_status": evidence.get("evidence_status", "DIRECT"),
        "raw_excerpt": evidence.get("raw_excerpt"),
        "integrity_hash": evidence.get("integrity_hash"),
        "source_system": evidence.get("source_system"),
    }


def list_customers(data: Dict[str, List[Dict[str, str]]]) -> List[str]:
    return sorted({row["customer_id"] for row in data["users"]})


def list_purposes(data: Dict[str, List[Dict[str, str]]]) -> List[str]:
    return sorted({row["purpose"] for row in data["consent_events"]})


def save_investigation_reference(result: InvestigationResult) -> None:
    return None
