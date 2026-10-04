# ARCHITECTURE

## Frontend

The frontend is a Next.js investigation workstation for a privacy operations analyst. It allows selecting a customer, choosing a purpose, running the withdrawal investigation, and inspecting the propagation path, timeline, findings, evidence detail, remediation flow, and audit history.

## Backend

The backend exposes FastAPI endpoints for customers, purposes, investigations, finding details, evidence detail, graph traversal, remediation simulation, and re-investigation. The deterministic engine remains the source of truth and the UI must not calculate finding states independently.

## PostgreSQL

PostgreSQL holds the durable evidence and event store used by the investigation engine. It includes customer data, withdrawal events, processing logs, evidence records, identity mappings, and remediation metadata.

## Neo4j

Neo4j stores lineage topology and system relationships. The graph describes how data flows between systems, while runtime evidence determines whether those relationships were active after withdrawal.

## Investigation engine

The engine resolves the customer purpose and withdrawal event, reconstructs the timeline, correlates runtime evidence, validates watershed timing, checks for exceptions and contradictions, and assembles a deterministic first-break classification.

## Evidence model

Evidence is attached to source records, timestamps, integrity values, and status. Status values include `DIRECT`, `INFERRED`, `CONTESTED`, `STALE`, `ABSENT`, and `UNVERIFIED` and should be treated as investigation metadata, not legal verdicts.

## Temporal model

The application uses event-time, observed-time, ingested-time, and investigation watermark logic. `UNKNOWN` is preserved when facts are unavailable, and `PENDING` is used when the observation window is incomplete.

## Optional AI layer

Any AI-generated explanation is clearly labeled and must be grounded in backend findings and cited evidence. It must never override the deterministic state assignment.
