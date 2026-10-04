# Company webhook integration

This guide documents the authenticated company integration API and the local
DEMO/SANDBOX deployment. The API is a security boundary, not a compliance
decision engine: authenticated ingestion does not imply that processing stopped
or that an organization is compliant.

## 1. Authentication and tenant identity

Every tenant data endpoint requires an API key. Send it as:

```http
Authorization: Bearer ct_<key_id>.<secret>
```

The key identifies one organization and one role. The server derives
`organization_id` from that stored identity for every protected operation.
**organization_id supplied by the caller is not trusted as tenant authority.**
In event and investigation request bodies it is optional for compatibility. If
it is present and differs from the authenticated key's organization, the API
returns `403`. It cannot switch the key's tenant. Reads and resource lookups are
scoped by the authenticated organization.

Never put a production API key in a browser bundle, mobile client, source
repository, URL, or log. Store integration keys in a server-side secret manager.
`/health` and `/ready` are public and report only health/readiness signals; they
do not return database or graph connection URLs, credentials, or tenant data.

## 2. Roles

The supported roles and minimum permissions are:

| Role | Permissions |
| --- | --- |
| `ADMIN` | Manage keys; read, investigate, and view audit records within its organization. |
| `PRIVACY_ANALYST` | Create investigations; read evidence, lineage, and ingestion status. |
| `DATA_GOVERNANCE` | Create investigations; read evidence, lineage, and ingestion status. |
| `AUDITOR` | Read investigations, evidence, lineage, ingestion status, and audit records; cannot ingest or run investigations. |
| `VIEWER` | Read investigations, evidence, and lineage within its organization. |
| `CONNECTOR` | Ingest events and read ingestion status; cannot read investigation/evidence data. |

Ingestion is restricted to `CONNECTOR`. An `ADMIN` can issue and revoke keys but
does not impersonate an ingestion connector. Create a separate connector key
for each integration/source boundary.

## 3. API-key creation, rotation, and revocation

An administrator creates a key for its own organization:

```http
POST /api/v1/admin/api-keys
Authorization: Bearer <administrator-key>
Content-Type: application/json
```

```json
{"name": "CRM event connector", "role": "CONNECTOR"}
```

The `201` response contains `key_id`, `role`, `name`, and `secret`. Save the
secret immediately: it is returned only at creation and is not returned by
`GET /api/v1/admin/api-keys`. The database stores a salted scrypt verifier for
bearer authentication. Where HMAC is enabled, the API secret is encrypted with
AES-GCM using `API_KEY_ENCRYPTION_KEY`; plaintext is not stored.

Rotate without downtime by creating a replacement key, updating the integration,
verifying successful ingestion, and revoking the old key:

```http
POST /api/v1/admin/api-keys/{key_id}/revoke
Authorization: Bearer <administrator-key>
```

Revocation is immediate. A revoked key receives `401`. The key list is scoped
to the administrator's organization and exposes metadata only, never key
hashes, encrypted material, or secrets.

## 4. HMAC request signing

Bearer authentication is supported for simpler integrations. Machine clients
may instead use HMAC-SHA256 over the exact raw request body. For HMAC, do not
send the `Authorization` header. Send:

```http
X-ConsentTrace-Key-Id: <key_id>
X-ConsentTrace-Timestamp: <unix-seconds>
X-ConsentTrace-Signature: <lowercase-hex-hmac-sha256>
```

The HMAC key is the API secret returned once at key creation. Sign these UTF-8
bytes (with newline separators and no trailing newline):

```text
HTTP_METHOD
URL_PATH
UNIX_TIMESTAMP
<exact raw request body bytes>
```

For example, the method/path portion for event ingestion is
`POST\n/api/v1/ingest/events\n`. Query parameters are not part of the signed
path. Serialize JSON once, sign those exact bytes, and transmit the same bytes.
Timestamps outside `HMAC_REPLAY_WINDOW_SECONDS` (default 300 seconds) are
rejected. A successfully used signature cannot be reused; replay fingerprints
are stored with a time-bounded expiry. HMAC requires the server-side
`API_KEY_ENCRYPTION_KEY` so the secret can be decrypted for verification.

Example client-side signing (keep `API_SECRET` in a server-side environment,
never in browser code):

```python
import hashlib
import hmac
import time

timestamp = str(int(time.time()))
raw_body = b'{"event_id":"crm-123","event_type":"PREFERENCE_UPDATED",...}'
message = b"\n".join((b"POST", b"/api/v1/ingest/events", timestamp.encode(), raw_body))
signature = hmac.new(API_SECRET.encode(), message, hashlib.sha256).hexdigest()
```

## 5. Event schema and minimum data

```http
POST /api/v1/ingest/events
Content-Type: application/json
```

Required:

| Field | Meaning |
| --- | --- |
| `event_id` | Stable source event ID. Keep it unchanged when retrying. |
| `event_type` | A supported event type below. |
| `event_time` | Source occurrence time in ISO 8601. |
| `source_system` | Registered/source-system display name. |
| `person_ref` | Organization-local pseudonymous subject reference. |

Optional: `observed_time`, `purpose`, `payload` (object), `evidence_metadata`
(object), and `organization_id`. The authenticated organization is applied by
the server. Send only fields needed to explain the event; prefer pseudonymous
references over names, emails, or other direct identifiers. Avoid placing
unneeded personal data in `raw_excerpt`.

Supported event types:

```text
CONSENT_GRANTED, CONSENT_WITHDRAWN, PREFERENCE_UPDATED,
PROCESSING_STARTED, PROCESSING_COMPLETED, DATASET_READ, DATASET_WRITE,
AUDIENCE_MEMBER_ADDED, AUDIENCE_MEMBER_REMOVED, EXPORT_CREATED, EXPORT_SENT,
PROCESSOR_ACKNOWLEDGED, SUPPRESSION_COMPLETED, IDENTITY_MAPPED,
EXCEPTION_CREATED, LINEAGE_DEFINED, EVIDENCE_OBSERVED
```

Example:

```json
{
  "event_id": "crm-01J8A3M2M8E7",
  "event_type": "PREFERENCE_UPDATED",
  "event_time": "2026-10-02T10:31:46+05:30",
  "observed_time": "2026-10-02T10:31:47+05:30",
  "source_system": "Example CRM",
  "organization_id": "org-example",
  "person_ref": "customer-123",
  "purpose": "MARKETING",
  "payload": {"preference": "opted_out"},
  "evidence_metadata": {
    "source_type": "crm_audit",
    "source_record": "preference-update-456",
    "evidence_status": "DIRECT",
    "raw_excerpt": "Marketing preference changed to opted out."
  }
}
```

Example using bearer auth:

```bash
curl --request POST "$CONSENTTRACE_URL/api/v1/ingest/events" \
  --header "Authorization: Bearer $CONSENTTRACE_CONNECTOR_KEY" \
  --header "Content-Type: application/json" \
  --header "X-Request-ID: crm-batch-20261002-17" \
  --data-binary @event.json
```

The API validates required top-level fields and event type. It does not yet
enforce a strict payload schema per event type; producers must validate their
own domain schema and avoid sending unsupported fields.

## 6. Timestamps and idempotency

Use ISO 8601 timestamps with `Z` or an explicit UTC offset. Naive timestamps
are interpreted as UTC. `event_time` is when the event occurred;
`observed_time` is when the source observed/recorded it; ingestion time is
assigned by ConsentTrace. Investigation temporal evaluation uses event time,
not arrival order.

The ingestion idempotency key is `(authenticated organization, event_id)`.
New events return `201` with `status: "accepted"` and
`idempotent: false`. Replays return `200` with `status: "duplicate"` and
`idempotent: true`; the original evidence is retained. Use globally unique
event IDs because the current PostgreSQL schema also uses `event_id` as its
primary key. Retry with the original event ID and unchanged event body; never
reuse an ID for changed content.

Duplicate ingestion does not retry Neo4j projection. If the original response
reports `GRAPH_PROJECTION_FAILED`, raise an operational incident; a duplicate
retry does not repair the graph.

## 7. Error codes and retry behavior

| HTTP | Meaning | Recommended action |
| --- | --- | --- |
| `200` | Duplicate/idempotent event. | Treat as already accepted; do not create a new ID. |
| `201` | Event persisted; inspect `projection_status`. | Record event ID, request ID, evidence ID, and projection outcome. |
| `401` | Missing, invalid, or revoked credentials; invalid HMAC or stale/replayed signature. | Check credentials, timestamp, raw body/signature construction, and key status. |
| `403` | Authenticated key lacks permission or supplied organization mismatches its tenant. | Correct the requested action/organization; do not retry unchanged. |
| `404` | Resource absent in the authenticated organization. | Check the tenant and resource reference. |
| `413` | Configured body/event/evidence limit exceeded. | Reduce payload size; do not retry unchanged. |
| `422` | Request/model validation failed. | Correct the request; do not retry unchanged. |
| `429` | Rate limit exceeded. | Honor `X-Request-ID`; back off with jitter before retrying. |
| `500` | Unexpected server failure. Persistence may precede a projection failure. | Check status/evidence and contact operations before retrying. |
| `503` | Database/runtime dependency unavailable. | Retry the same event ID/body with bounded exponential backoff and jitter. |

Do not interpret HTTP `201` alone as graph success: the response may carry
`projection_status: "GRAPH_PROJECTION_FAILED"`. A `4xx` response should not be
retried without correcting the request.

## 8. Request and rate limits

Defaults are configurable through environment:

| Setting | Default | Scope |
| --- | ---: | --- |
| `MAX_JSON_BODY_BYTES` | 1,048,576 | Maximum general JSON body. |
| `MAX_INGESTION_EVENT_BYTES` | 262,144 | Maximum ingestion event body. |
| `MAX_EVIDENCE_PAYLOAD_BYTES` | 65,536 | Combined ingestion `payload` and `evidence_metadata`. |
| `RATE_LIMIT_AUTH_PER_MINUTE` | 20 | Authentication failures per source IP. |
| `RATE_LIMIT_INGEST_PER_MINUTE` | 120 | Ingestion requests per API key. |
| `RATE_LIMIT_INVESTIGATION_PER_MINUTE` | 30 | Investigation creations per API key. |

Oversize requests return `413`; exceeded rates return `429`. Current limiting is
an in-process fixed-window implementation and is suitable only for a
single-instance MVP. Multi-instance/production deployments must replace or
coordinate it with a distributed limiter (for example Redis) and should also
enforce edge/gateway limits.

## 9. Correlation and audit trail

Send an optional safe `X-Request-ID` (1–128 ASCII letters, digits, `.`, `_`,
`:`, or `-`). Otherwise the service generates one. Every response includes
`X-Request-ID`; error bodies include the ID where the API uses its error
envelope. Include it with event/key IDs when contacting operations.

Security audit records capture authentication success/failure, denied
authorization, event ingestion, investigation creation, evidence/lineage
access attempts, API-key listing/creation/revocation, sandbox reset, and
relevant simulations.
Records include tenant/principal/role where known, action/resource, outcome,
timestamp, request ID, source IP, and minimal metadata. Authorization headers,
API secrets, and raw payloads are not logged. Unauthenticated failures have no
trusted tenant identity and are recorded without assigning a tenant. Audit
records are append-only through the application API; database administrators
remain a separate trust boundary. `GET /api/v1/audit-events` is available to
`ADMIN` and `AUDITOR`, scoped to their organization.

## 10. DEMO, SANDBOX, and PRODUCTION

`APP_MODE` must be `DEMO`, `SANDBOX`, or `PRODUCTION`.

- `DEMO` uses synthetic AcmePay sample data.
- `SANDBOX` enables the fixed synthetic DemoCorp event scenarios only when
  `SANDBOX_ENABLED=true` and `APP_ENV` is `development` or `test`. Sandbox
  controls require an administrator key bound to `org-democorp-sandbox`.
  Scenario adapters use a separate server-side `CONNECTOR` key and submit
  events through the actual ingestion API. Reset is limited to the fixed
  DemoCorp organization.
- `PRODUCTION` rejects sandbox configuration and development bootstrap keys,
  requires PostgreSQL, a dedicated API-key pepper, and a valid 32-byte
  `API_KEY_ENCRYPTION_KEY`. Supply these through a secret manager. A
  `PRODUCTION_ADMIN_API_KEY` plus `PRODUCTION_ADMIN_ORG_ID` can provision the
  initial administrator; remove that bootstrap credential from the runtime
  environment after provisioning. Production startup fails closed on missing
  mandatory secret/database configuration.

Compose defaults are intentionally local-only demo credentials, not suitable
for deployment. Before production deployment, override/blank development
bootstrap settings, disable sandbox, supply production secrets, terminate
public development ports, and verify the effective environment.

## 11. Security responsibilities and maturity

ConsentTrace provides organization-bound API-key identity, role checks,
tenant-scoped database/resource queries, scrypt API-key verifiers, encrypted
HMAC material, replay prevention, request limits, single-instance rate limits,
correlation, and application audit events. HMAC is optional; bearer API keys
remain supported.

The deployment operator remains responsible for TLS, secret storage/rotation,
network isolation, gateway-level DDoS and distributed rate limits, backups and
retention, database access control, audit retention/immutability outside the
application, monitoring/alerting, incident response, and legal/data-processing
requirements. Request signing does not replace TLS. The deterministic evidence
engine remains the sole source of investigation classifications; authentication
does not change `VERIFIED_STOPPED`, `STILL_ACTIVE`, `UNKNOWN`, `EXCEPTION`,
`CONFLICTED`, or `PENDING`.

Temporal scopes remain `ACTIVE`; late events may trigger recomputation and
there is no finalization protocol. Investigation results must be treated as
revisable.
