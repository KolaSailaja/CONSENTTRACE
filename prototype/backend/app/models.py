from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "event_id", name="uq_ingestion_event_org_event"),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    observed_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    person_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    purpose: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    projection_status: Mapped[str] = mapped_column(String(64), nullable=False, default="RECEIVED")
    projection_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recomputation_status: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    evidence_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(128), ForeignKey("ingestion_events.event_id"), nullable=False, index=True)
    source_record: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    hash_algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="SHA-256")
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DIRECT")
    reliability_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="MEDIUM")
    normalization_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SourceHealth(Base):
    __tablename__ = "source_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="webhook")
    last_successful_ingestion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connection_status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "source_name", name="uq_source_health_org_source"),
    )


class InvestigationScope(Base):
    __tablename__ = "investigation_scopes"

    investigation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    person_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    withdrawal_event: Mapped[str | None] = mapped_column(String(128), nullable=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
