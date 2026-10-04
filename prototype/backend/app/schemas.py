from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

StateValue = Literal["PENDING", "VERIFIED_STOPPED", "STILL_ACTIVE", "UNKNOWN", "EXCEPTION", "CONFLICTED"]
EvidenceStatus = Literal["DIRECT", "INFERRED", "CONTESTED", "STALE", "ABSENT", "UNVERIFIED"]


class EvidenceReference(BaseModel):
    evidence_id: str
    source_type: str
    source_record: str
    source_url: str | None = None
    timestamp: datetime | None = None
    evidence_status: EvidenceStatus
    raw_excerpt: str | None = None


class Finding(BaseModel):
    asset: str
    asset_type: str
    finding_state: StateValue
    reason: str
    evidence: List[EvidenceReference] = Field(default_factory=list)
    event_time: datetime | None = None
    observed_time: datetime | None = None
    source_system: str | None = None
    lineage_relationship: str | None = None
    contradictory_evidence: List[str] = Field(default_factory=list)
    recommended_action: str | None = None


class InvestigationScope(BaseModel):
    investigation_id: str
    customer_id: str
    purpose: str
    withdrawal_event: str
    window_start: datetime
    window_end: datetime
    watermark: datetime
    policy_version: str = "v1-demo"
    created_at: datetime


class InvestigationResult(BaseModel):
    investigation_id: str
    customer_id: str
    customer_name: str
    purpose: str
    withdrawal_timestamp: datetime
    watermark: datetime
    overall_investigation_state: str
    first_break: str | None = None
    findings: List[Finding] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    previous_investigation_id: Optional[str] = None
    remediation_summary: Optional[str] = None


class InvestigationRequest(BaseModel):
    customer_id: str
    purpose: str
    organization_id: str | None = None


class RemediationRequest(BaseModel):
    investigation_id: str
    scenario: str = "demo-remediation"


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str
    state: StateValue | None = None
    timestamp: datetime | None = None


class GraphPath(BaseModel):
    nodes: List[GraphNode]
    edges: List[Dict[str, str]]


class EvidenceDetail(BaseModel):
    evidence_id: str
    source_type: str
    source_record: str
    source_url: str | None = None
    timestamp: datetime | None = None
    observed_time: datetime | None = None
    ingested_at: datetime | None = None
    evidence_status: EvidenceStatus
    raw_excerpt: str | None = None
    integrity_hash: str | None = None
    source_system: str | None = None


class FindingDetail(BaseModel):
    asset: str
    asset_type: str
    finding_state: StateValue
    reason: str
    evidence: List[EvidenceDetail]
    source_system: str | None = None
    lineage_relationship: str | None = None
    contradictory_evidence: List[str] = Field(default_factory=list)
    recommended_action: str | None = None
