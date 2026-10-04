CREATE TABLE IF NOT EXISTS customers (
  customer_id VARCHAR(64) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  email_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS consent_events (
  event_id VARCHAR(64) PRIMARY KEY,
  customer_id VARCHAR(64) NOT NULL,
  purpose VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL,
  event_time TIMESTAMPTZ NOT NULL,
  notice_version VARCHAR(64),
  source_system VARCHAR(128)
);

CREATE TABLE IF NOT EXISTS ingestion_events (
  event_id VARCHAR(128) PRIMARY KEY,
  organization_id VARCHAR(128) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  event_time TIMESTAMPTZ NOT NULL,
  observed_time TIMESTAMPTZ,
  ingested_time TIMESTAMPTZ NOT NULL,
  source_system VARCHAR(128) NOT NULL,
  person_ref VARCHAR(128) NOT NULL,
  purpose VARCHAR(128),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  request_id VARCHAR(128) NOT NULL,
  projection_status VARCHAR(64) NOT NULL DEFAULT 'RECEIVED',
  projection_notes TEXT,
  recomputation_status VARCHAR(64) NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (organization_id, event_id)
);

CREATE TABLE IF NOT EXISTS evidence_records (
  evidence_id VARCHAR(128) PRIMARY KEY,
  organization_id VARCHAR(128) NOT NULL,
  source_type VARCHAR(64) NOT NULL,
  source_event_id VARCHAR(128) NOT NULL REFERENCES ingestion_events(event_id),
  source_record VARCHAR(255) NOT NULL,
  content_hash VARCHAR(128) NOT NULL,
  hash_algorithm VARCHAR(32) NOT NULL DEFAULT 'SHA-256',
  event_time TIMESTAMPTZ NOT NULL,
  observed_time TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ NOT NULL,
  evidence_status VARCHAR(32) NOT NULL DEFAULT 'DIRECT',
  reliability_tier VARCHAR(32) NOT NULL DEFAULT 'MEDIUM',
  normalization_version VARCHAR(32) NOT NULL DEFAULT 'v1',
  raw_excerpt TEXT,
  source_system VARCHAR(128),
  request_id VARCHAR(128),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_health (
  id SERIAL PRIMARY KEY,
  organization_id VARCHAR(128) NOT NULL,
  source_name VARCHAR(128) NOT NULL,
  source_type VARCHAR(64) NOT NULL DEFAULT 'webhook',
  last_successful_ingestion TIMESTAMPTZ,
  last_event VARCHAR(128),
  event_count INTEGER NOT NULL DEFAULT 0,
  failed_events INTEGER NOT NULL DEFAULT 0,
  duplicate_events INTEGER NOT NULL DEFAULT 0,
  validation_failures INTEGER NOT NULL DEFAULT 0,
  current_cursor VARCHAR(255),
  connection_status VARCHAR(32) NOT NULL DEFAULT 'connected',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (organization_id, source_name)
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id VARCHAR(64) PRIMARY KEY,
  source_type VARCHAR(64) NOT NULL,
  source_record VARCHAR(255) NOT NULL,
  source_url TEXT,
  observed_time TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ,
  raw_excerpt TEXT,
  integrity_hash VARCHAR(128),
  evidence_status VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS identity_mappings (
  mapping_id SERIAL PRIMARY KEY,
  source_system VARCHAR(128) NOT NULL,
  source_identifier VARCHAR(255) NOT NULL,
  canonical_customer_id VARCHAR(64) NOT NULL,
  mapping_method VARCHAR(64) NOT NULL,
  mapping_status VARCHAR(32) NOT NULL,
  confidence_band VARCHAR(32) NOT NULL,
  valid_from TIMESTAMPTZ,
  valid_to TIMESTAMPTZ,
  evidence_id VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS investigation_scopes (
  investigation_id VARCHAR(128) PRIMARY KEY,
  organization_id VARCHAR(128) NOT NULL,
  person_ref VARCHAR(128) NOT NULL,
  purpose VARCHAR(128) NOT NULL,
  withdrawal_event VARCHAR(128),
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  watermark TIMESTAMPTZ NOT NULL,
  policy_version VARCHAR(64) NOT NULL DEFAULT 'v1',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE'
);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_organization_id ON investigation_scopes (organization_id);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_person_ref ON investigation_scopes (person_ref);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_purpose ON investigation_scopes (purpose);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_window_start ON investigation_scopes (window_start);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_window_end ON investigation_scopes (window_end);

CREATE TABLE IF NOT EXISTS findings (
  finding_id SERIAL PRIMARY KEY,
  investigation_id VARCHAR(128) NOT NULL,
  asset VARCHAR(255) NOT NULL,
  asset_type VARCHAR(128) NOT NULL,
  finding_state VARCHAR(32) NOT NULL,
  reason TEXT,
  evidence_ids TEXT,
  event_time TIMESTAMPTZ,
  source_system VARCHAR(128),
  recommended_action TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
  recommendation_id SERIAL PRIMARY KEY,
  investigation_id VARCHAR(128) NOT NULL,
  recommendation_text TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS remediation_actions (
  remediation_id SERIAL PRIMARY KEY,
  investigation_id VARCHAR(128) NOT NULL,
  action_name VARCHAR(255) NOT NULL,
  action_status VARCHAR(32) NOT NULL,
  executed_at TIMESTAMPTZ,
  evidence_id VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS investigation_snapshots (
  snapshot_id SERIAL PRIMARY KEY,
  investigation_id VARCHAR(128) NOT NULL,
  snapshot_json JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
