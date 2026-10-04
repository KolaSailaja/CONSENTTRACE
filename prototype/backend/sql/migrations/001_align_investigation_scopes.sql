ALTER TABLE investigation_scopes
  ADD COLUMN IF NOT EXISTS organization_id VARCHAR(128),
  ADD COLUMN IF NOT EXISTS person_ref VARCHAR(128),
  ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'ACTIVE';

UPDATE investigation_scopes
SET organization_id = 'legacy-' || md5(investigation_id)
WHERE organization_id IS NULL;

UPDATE investigation_scopes
SET policy_version = 'v1'
WHERE policy_version IS NULL;

UPDATE investigation_scopes
SET status = 'ACTIVE'
WHERE status IS NULL;

ALTER TABLE investigation_scopes
  ALTER COLUMN organization_id SET NOT NULL,
  ALTER COLUMN person_ref SET NOT NULL,
  ALTER COLUMN purpose SET NOT NULL,
  ALTER COLUMN withdrawal_event TYPE VARCHAR(128),
  ALTER COLUMN withdrawal_event DROP NOT NULL,
  ALTER COLUMN policy_version SET NOT NULL,
  ALTER COLUMN status SET NOT NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'investigation_scopes'
      AND column_name = 'customer_id'
  ) THEN
    EXECUTE 'UPDATE investigation_scopes SET person_ref = customer_id WHERE person_ref IS NULL';
    EXECUTE 'ALTER TABLE investigation_scopes ALTER COLUMN customer_id DROP NOT NULL';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'investigation_scopes'
      AND column_name = 'window_start'
      AND data_type = 'timestamp without time zone'
  ) THEN
    ALTER TABLE investigation_scopes
      ALTER COLUMN window_start TYPE TIMESTAMPTZ USING window_start AT TIME ZONE 'UTC';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'investigation_scopes'
      AND column_name = 'window_end'
      AND data_type = 'timestamp without time zone'
  ) THEN
    ALTER TABLE investigation_scopes
      ALTER COLUMN window_end TYPE TIMESTAMPTZ USING window_end AT TIME ZONE 'UTC';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'investigation_scopes'
      AND column_name = 'watermark'
      AND data_type = 'timestamp without time zone'
  ) THEN
    ALTER TABLE investigation_scopes
      ALTER COLUMN watermark TYPE TIMESTAMPTZ USING watermark AT TIME ZONE 'UTC';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'investigation_scopes'
      AND column_name = 'created_at'
      AND data_type = 'timestamp without time zone'
  ) THEN
    ALTER TABLE investigation_scopes
      ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC';
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_investigation_scopes_organization_id ON investigation_scopes (organization_id);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_person_ref ON investigation_scopes (person_ref);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_purpose ON investigation_scopes (purpose);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_window_start ON investigation_scopes (window_start);
CREATE INDEX IF NOT EXISTS ix_investigation_scopes_window_end ON investigation_scopes (window_end);