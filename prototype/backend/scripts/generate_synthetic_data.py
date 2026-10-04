from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

base = Path(__file__).resolve().parents[1]
data_dir = base / "data"
data_dir.mkdir(exist_ok=True)

TIMEZONE = timezone(timedelta(hours=5, minutes=30))


def iso(dt: datetime) -> str:
    return dt.astimezone(TIMEZONE).isoformat()


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


customers = [
    {"customer_id": "C1001", "name": "Aarav Mehta", "email_hash": "d3d5d1a1", "created_at": iso(datetime(2026, 1, 11, 9, 45, tzinfo=TIMEZONE))},
    {"customer_id": "C1002", "name": "Bhavna Nair", "email_hash": "b4af7e01", "created_at": iso(datetime(2026, 1, 14, 10, 10, tzinfo=TIMEZONE))},
    {"customer_id": "C1003", "name": "Chitra Iyer", "email_hash": "1f5c0de3", "created_at": iso(datetime(2026, 2, 1, 8, 30, tzinfo=TIMEZONE))},
    {"customer_id": "C1004", "name": "Dinesh Sen", "email_hash": "9113aab7", "created_at": iso(datetime(2026, 2, 6, 11, 5, tzinfo=TIMEZONE))},
    {"customer_id": "C1005", "name": "Esha Verma", "email_hash": "4d41eef9", "created_at": iso(datetime(2026, 2, 18, 7, 28, tzinfo=TIMEZONE))},
    {"customer_id": "C1006", "name": "Farhan Ali", "email_hash": "7eaad1f8", "created_at": iso(datetime(2026, 2, 23, 15, 11, tzinfo=TIMEZONE))},
    {"customer_id": "C1007", "name": "Gautam Das", "email_hash": "4c9347e1", "created_at": iso(datetime(2026, 3, 11, 12, 2, tzinfo=TIMEZONE))},
    {"customer_id": "C1008", "name": "Hina Kapoor", "email_hash": "ec5a5c9d", "created_at": iso(datetime(2026, 3, 12, 9, 46, tzinfo=TIMEZONE))},
    {"customer_id": "C1009", "name": "Ishaan Roy", "email_hash": "acdd7bc1", "created_at": iso(datetime(2026, 4, 2, 8, 19, tzinfo=TIMEZONE))},
    {"customer_id": "C1010", "name": "Jiya Shah", "email_hash": "b84511b1", "created_at": iso(datetime(2026, 4, 9, 14, 1, tzinfo=TIMEZONE))},
    {"customer_id": "C1011", "name": "Karan Singh", "email_hash": "0b42f08b", "created_at": iso(datetime(2026, 5, 1, 10, 15, tzinfo=TIMEZONE))},
    {"customer_id": "C1012", "name": "Lata Reddy", "email_hash": "a1187964", "created_at": iso(datetime(2026, 6, 11, 17, 10, tzinfo=TIMEZONE))},
    {"customer_id": "C1013", "name": "Manoj Pillai", "email_hash": "2b10532d", "created_at": iso(datetime(2026, 6, 14, 13, 25, tzinfo=TIMEZONE))},
    {"customer_id": "C1014", "name": "Nisha Rao", "email_hash": "53a1f803", "created_at": iso(datetime(2026, 7, 2, 8, 58, tzinfo=TIMEZONE))},
    {"customer_id": "C1024", "name": "Kiran Rao", "email_hash": "7f58e96c", "created_at": iso(datetime(2026, 8, 12, 9, 5, tzinfo=TIMEZONE))},
]

write_csv(data_dir / "users.csv", ["customer_id", "name", "email_hash", "created_at"], customers)

consent_rows = []
for idx, customer in enumerate(customers, start=1):
    base_time = datetime(2026, 1, 1, 9, 0, tzinfo=TIMEZONE) + timedelta(days=idx * 6)
    consent_rows.append({
        "event_id": f"CONS-{idx:04d}",
        "customer_id": customer["customer_id"],
        "purpose": "MARKETING",
        "status": "CONSENTED",
        "timestamp": iso(base_time),
        "notice_version": "v3.1",
        "source_system": "Consent Service",
    })
    consent_rows.append({
        "event_id": f"CONS-{idx:04d}-P2",
        "customer_id": customer["customer_id"],
        "purpose": "PRODUCT",
        "status": "CONSENTED",
        "timestamp": iso(base_time + timedelta(minutes=5)),
        "notice_version": "v3.1",
        "source_system": "Consent Service",
    })
    if customer["customer_id"] in {"C1001", "C1002", "C1007", "C1010"}:
        consent_rows.append({
            "event_id": f"CONS-{idx:04d}-WD",
            "customer_id": customer["customer_id"],
            "purpose": "MARKETING",
            "status": "WITHDRAWN",
            "timestamp": iso(base_time + timedelta(days=28)),
            "notice_version": "v3.2",
            "source_system": "Consent Service",
        })

# Add exact C1024 demo withdrawal events
consent_rows.extend([
    {"event_id": "CONS-C1024-001", "customer_id": "C1024", "purpose": "MARKETING", "status": "CONSENTED", "timestamp": "2026-08-12T09:05:00+05:30", "notice_version": "v3.1", "source_system": "Consent Service"},
    {"event_id": "CONS-C1024-002", "customer_id": "C1024", "purpose": "MARKETING", "status": "WITHDRAWN", "timestamp": "2026-10-02T10:31:42+05:30", "notice_version": "v3.2", "source_system": "Consent Service"},
    {"event_id": "CONS-C1024-003", "customer_id": "C1024", "purpose": "MARKETING", "status": "CONSENTED", "timestamp": "2026-09-12T08:00:00+05:30", "notice_version": "v3.1", "source_system": "Consent Service"},
    {"event_id": "CONS-C1024-004", "customer_id": "C1024", "purpose": "PRODUCT", "status": "CONSENTED", "timestamp": "2026-08-18T09:00:00+05:30", "notice_version": "v3.1", "source_system": "Consent Service"},
])

write_csv(data_dir / "consent_events.csv", ["event_id", "customer_id", "purpose", "status", "timestamp", "notice_version", "source_system"], consent_rows)

systems = [
    {"system_id": "SYS-01", "name": "AcmePay Consumer App", "type": "APP", "owner_team": "Product", "processor_flag": "FALSE", "purpose_scope": "CUSTOMER_ACCOUNT"},
    {"system_id": "SYS-02", "name": "Consent Service", "type": "CONSENT", "owner_team": "Privacy Engineering", "processor_flag": "FALSE", "purpose_scope": "CONSENT"},
    {"system_id": "SYS-03", "name": "Customer Database", "type": "DATABASE", "owner_team": "Data Platform", "processor_flag": "FALSE", "purpose_scope": "MARKETING"},
    {"system_id": "SYS-04", "name": "CRM", "type": "CRM", "owner_team": "Sales Ops", "processor_flag": "FALSE", "purpose_scope": "MARKETING"},
    {"system_id": "SYS-05", "name": "CDC Event Stream", "type": "STREAM", "owner_team": "Data Platform", "processor_flag": "FALSE", "purpose_scope": "MARKETING"},
    {"system_id": "SYS-06", "name": "Warehouse ETL", "type": "ETL", "owner_team": "Analytics Engineering", "processor_flag": "FALSE", "purpose_scope": "MARKETING"},
    {"system_id": "SYS-07", "name": "Customer Analytics Table", "type": "DATASET", "owner_team": "Analytics", "processor_flag": "FALSE", "purpose_scope": "MARKETING"},
    {"system_id": "SYS-08", "name": "Marketing Audience Job", "type": "JOB", "owner_team": "Audience Ops", "processor_flag": "FALSE", "purpose_scope": "MARKETING"},
    {"system_id": "SYS-09", "name": "Processor X Export", "type": "EXPORT", "owner_team": "Data Exchange", "processor_flag": "TRUE", "purpose_scope": "MARKETING"},
    {"system_id": "SYS-10", "name": "Processor X", "type": "PROCESSOR", "owner_team": "Vendor Management", "processor_flag": "TRUE", "purpose_scope": "MARKETING"},
]
write_csv(data_dir / "systems.csv", ["system_id", "name", "type", "owner_team", "processor_flag", "purpose_scope"], systems)

datasets = [
    {"dataset_id": "DS-01", "system_id": "SYS-03", "name": "customer_db", "contains_personal_data": "TRUE", "purpose_scope": "MARKETING", "identifier_column": "customer_id"},
    {"dataset_id": "DS-02", "system_id": "SYS-04", "name": "crm_customer_profile", "contains_personal_data": "TRUE", "purpose_scope": "MARKETING", "identifier_column": "customer_id"},
    {"dataset_id": "DS-03", "system_id": "SYS-05", "name": "cdc_customer_events", "contains_personal_data": "TRUE", "purpose_scope": "MARKETING", "identifier_column": "customer_id"},
    {"dataset_id": "DS-04", "system_id": "SYS-06", "name": "warehouse_consent_dimension", "contains_personal_data": "TRUE", "purpose_scope": "MARKETING", "identifier_column": "customer_id"},
    {"dataset_id": "DS-05", "system_id": "SYS-07", "name": "customer_analytics_table", "contains_personal_data": "TRUE", "purpose_scope": "MARKETING", "identifier_column": "customer_id"},
    {"dataset_id": "DS-06", "system_id": "SYS-08", "name": "marketing_audience", "contains_personal_data": "TRUE", "purpose_scope": "MARKETING", "identifier_column": "customer_id"},
    {"dataset_id": "DS-07", "system_id": "SYS-09", "name": "processor_x_export", "contains_personal_data": "TRUE", "purpose_scope": "MARKETING", "identifier_column": "customer_id"},
    {"dataset_id": "DS-08", "system_id": "SYS-10", "name": "processor_x_inbox", "contains_personal_data": "TRUE", "purpose_scope": "MARKETING", "identifier_column": "customer_id"},
    {"dataset_id": "DS-09", "system_id": "SYS-03", "name": "customer_support_db", "contains_personal_data": "TRUE", "purpose_scope": "SUPPORT", "identifier_column": "customer_id"},
    {"dataset_id": "DS-10", "system_id": "SYS-06", "name": "product_analytics", "contains_personal_data": "TRUE", "purpose_scope": "PRODUCT", "identifier_column": "customer_id"},
    {"dataset_id": "DS-11", "system_id": "SYS-08", "name": "product_audience", "contains_personal_data": "TRUE", "purpose_scope": "PRODUCT", "identifier_column": "customer_id"},
    {"dataset_id": "DS-12", "system_id": "SYS-09", "name": "vendor_export", "contains_personal_data": "TRUE", "purpose_scope": "PRODUCT", "identifier_column": "customer_id"},
]
write_csv(data_dir / "datasets.csv", ["dataset_id", "system_id", "name", "contains_personal_data", "purpose_scope", "identifier_column"], datasets)

lineage_rows = [
    {"lineage_id": "LN-01", "from_type": "System", "from_id": "SYS-02", "relationship": "controls", "to_type": "System", "to_id": "SYS-03", "evidence_id": "EV-1001", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
    {"lineage_id": "LN-02", "from_type": "System", "from_id": "SYS-03", "relationship": "syncs_to", "to_type": "System", "to_id": "SYS-04", "evidence_id": "EV-1002", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
    {"lineage_id": "LN-03", "from_type": "System", "from_id": "SYS-04", "relationship": "feeds", "to_type": "System", "to_id": "SYS-05", "evidence_id": "EV-1003", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
    {"lineage_id": "LN-04", "from_type": "System", "from_id": "SYS-05", "relationship": "input_to", "to_type": "System", "to_id": "SYS-06", "evidence_id": "EV-2001", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
    {"lineage_id": "LN-05", "from_type": "System", "from_id": "SYS-06", "relationship": "outputs_to", "to_type": "Dataset", "to_id": "DS-05", "evidence_id": "EV-2002", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
    {"lineage_id": "LN-06", "from_type": "Dataset", "from_id": "DS-05", "relationship": "input_to", "to_type": "System", "to_id": "SYS-08", "evidence_id": "EV-3001", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
    {"lineage_id": "LN-07", "from_type": "System", "from_id": "SYS-08", "relationship": "outputs_to", "to_type": "Dataset", "to_id": "DS-06", "evidence_id": "EV-3001", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
    {"lineage_id": "LN-08", "from_type": "Dataset", "from_id": "DS-06", "relationship": "input_to", "to_type": "System", "to_id": "SYS-09", "evidence_id": "EV-4001", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
    {"lineage_id": "LN-09", "from_type": "System", "from_id": "SYS-09", "relationship": "sent_to", "to_type": "System", "to_id": "SYS-10", "evidence_id": "EV-4002", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00"},
]
write_csv(data_dir / "lineage.csv", ["lineage_id", "from_type", "from_id", "relationship", "to_type", "to_id", "evidence_id", "valid_from", "valid_to"], lineage_rows)

processing_logs = []
for idx in range(1, 16):
    ts = datetime(2026, 8, 12, 9, 15, tzinfo=TIMEZONE) + timedelta(minutes=idx * 17)
    processing_logs.append({
        "log_id": f"LOG-{idx:03d}",
        "run_id": f"RUN-{idx:03d}",
        "job_id": "ETL_17",
        "timestamp": iso(ts),
        "operation": "CONSENT_DIMENSION_REFRESH",
        "input_dataset": "DS-04",
        "output_dataset": "DS-05",
        "customer_id": "C1024",
        "purpose": "MARKETING",
        "status": "SUCCESS",
    })
    processing_logs.append({
        "log_id": f"LOG-{idx:03d}-R",
        "run_id": f"RUN-{idx:03d}-R",
        "job_id": "AUDIO_08",
        "timestamp": iso(ts + timedelta(minutes=3)),
        "operation": "AUDIENCE_BUILD",
        "input_dataset": "DS-05",
        "output_dataset": "DS-06",
        "customer_id": "C1024",
        "purpose": "MARKETING",
        "status": "SUCCESS",
    })

# Add explicit post-withdrawal C1024 logs
processing_logs.extend([
    {"log_id": "LOG-ETL-017", "run_id": "RUN-ETL-017", "job_id": "ETL_17", "timestamp": "2026-10-02T10:45:00+05:30", "operation": "CONSENT_DIMENSION_REFRESH", "input_dataset": "DS-04", "output_dataset": "DS-05", "customer_id": "C1024", "purpose": "MARKETING", "status": "SUCCESS"},
    {"log_id": "LOG-ETL-017-STALE", "run_id": "RUN-ETL-017", "job_id": "ETL_17", "timestamp": "2026-10-02T10:45:03+05:30", "operation": "USE_STALE_CONSENT_SNAPSHOT", "input_dataset": "DS-04", "output_dataset": "DS-05", "customer_id": "C1024", "purpose": "MARKETING", "status": "WARNING"},
    {"log_id": "LOG-ETL-018", "run_id": "RUN-ETL-018", "job_id": "ETL_18", "timestamp": "2026-10-02T10:50:00+05:30", "operation": "SUPPRESSION_REFRESH", "input_dataset": "DS-06", "output_dataset": "DS-05", "customer_id": "C1024", "purpose": "MARKETING", "status": "SUCCESS"},
])
write_csv(data_dir / "processing_logs.csv", ["log_id", "run_id", "job_id", "timestamp", "operation", "input_dataset", "output_dataset", "customer_id", "purpose", "status"], processing_logs)

audience_membership = []
for idx in range(1, 31):
    obs = datetime(2026, 8, 20, 9, 0, tzinfo=TIMEZONE) + timedelta(days=idx)
    audience_membership.append({
        "membership_id": f"MEM-{idx:03d}",
        "audience_id": "marketing_audience",
        "customer_id": customers[(idx - 1) % len(customers)]["customer_id"],
        "purpose": "MARKETING",
        "observed_at": iso(obs),
        "source_run_id": f"RUN-{idx:03d}",
    })
# Add explicit C1024 marketing audience membership after withdrawal
audience_membership.extend([
    {"membership_id": "MEM-C1024-POST", "audience_id": "marketing_audience", "customer_id": "C1024", "purpose": "MARKETING", "observed_at": "2026-10-02T10:45:12+05:30", "source_run_id": "RUN-ETL-017"},
    {"membership_id": "MEM-C1024-REM", "audience_id": "marketing_audience", "customer_id": "C1024", "purpose": "MARKETING", "observed_at": "2026-10-02T11:05:00+05:30", "source_run_id": "RUN-ETL-018"},
])
write_csv(data_dir / "audience_membership.csv", ["membership_id", "audience_id", "customer_id", "purpose", "observed_at", "source_run_id"], audience_membership)

export_logs = []
for idx in range(1, 12):
    export_logs.append({
        "export_id": f"EXP-{idx:03d}",
        "customer_id": customers[idx % len(customers)]["customer_id"],
        "purpose": "MARKETING",
        "dataset_id": "DS-06",
        "processor_id": "PROC-01",
        "timestamp": iso(datetime(2026, 9, 3, 9, 0, tzinfo=TIMEZONE) + timedelta(days=idx * 2)),
        "operation": "EXPORT",
        "status": "SENT",
        "ack_id": f"ACK-{idx:03d}",
    })
export_logs.extend([
    {"export_id": "EXP-C1024-004", "customer_id": "C1024", "purpose": "MARKETING", "dataset_id": "DS-06", "processor_id": "PROC-01", "timestamp": "2026-10-02T10:47:03+05:30", "operation": "EXPORT", "status": "SENT", "ack_id": "ACK-MISSING"},
    {"export_id": "EXP-C1024-004-STOP", "customer_id": "C1024", "purpose": "MARKETING", "dataset_id": "DS-06", "processor_id": "PROC-01", "timestamp": "2026-10-02T11:10:32+05:30", "operation": "SUPPRESSION", "status": "CANCELLED", "ack_id": "ACK-STOP"},
])
write_csv(data_dir / "export_logs.csv", ["export_id", "customer_id", "purpose", "dataset_id", "processor_id", "timestamp", "operation", "status", "ack_id"], export_logs)

processor_ack = [
    {"ack_id": "ACK-001", "processor_id": "PROC-01", "customer_id": "C1001", "purpose": "MARKETING", "action": "ACKNOWLEDGED", "timestamp": "2026-09-01T12:00:00+05:30", "status": "RECEIVED", "export_id": ""},
    {"ack_id": "ACK-002", "processor_id": "PROC-01", "customer_id": "C1002", "purpose": "MARKETING", "action": "ACKNOWLEDGED", "timestamp": "2026-09-05T12:00:00+05:30", "status": "RECEIVED", "export_id": ""},
    {"ack_id": "ACK-003", "processor_id": "PROC-01", "customer_id": "C1007", "purpose": "MARKETING", "action": "ACKNOWLEDGED", "timestamp": "2026-09-11T12:00:00+05:30", "status": "RECEIVED", "export_id": ""},
    {"ack_id": "ACK-STOP", "processor_id": "PROC-01", "customer_id": "C1024", "purpose": "MARKETING", "action": "SUPPRESSION", "timestamp": "2026-10-02T11:12:00+05:30", "status": "RECEIVED", "export_id": "EXP-C1024-004-STOP"},
]
write_csv(data_dir / "processor_acknowledgements.csv", ["ack_id", "processor_id", "customer_id", "purpose", "action", "timestamp", "status", "export_id"], processor_ack)

exceptions = [
    {"exception_id": "EXC-001", "customer_id": "C1024", "purpose": "MARKETING", "system_id": "SYS-04", "basis": "LEGAL_HOLD", "review_owner": "DPO Office", "valid_from": "2026-10-01T00:00:00+05:30", "valid_to": "2026-10-05T00:00:00+05:30", "evidence_id": "EV-9001"},
    {"exception_id": "EXC-002", "customer_id": "C1001", "purpose": "MARKETING", "system_id": "SYS-08", "basis": "CONSENT_OPT_IN", "review_owner": "Marketing Ops", "valid_from": "2026-09-01T00:00:00+05:30", "valid_to": "2026-12-31T00:00:00+05:30", "evidence_id": "EV-9002"},
]
write_csv(data_dir / "exceptions.csv", ["exception_id", "customer_id", "purpose", "system_id", "basis", "review_owner", "valid_from", "valid_to", "evidence_id"], exceptions)

identity_mappings = [
    {"mapping_id": "IM-001", "source_system": "Consent Service", "source_identifier": "cust-1024", "canonical_customer_id": "C1024", "mapping_method": "deterministic_customer_id", "mapping_status": "MATCHED", "confidence_band": "HIGH", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00", "evidence_id": "EV-9901"},
    {"mapping_id": "IM-002", "source_system": "CRM", "source_identifier": "crm-user-1024", "canonical_customer_id": "C1024", "mapping_method": "deterministic_customer_id", "mapping_status": "MATCHED", "confidence_band": "HIGH", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00", "evidence_id": "EV-9902"},
    {"mapping_id": "IM-003", "source_system": "Warehouse ETL", "source_identifier": "customer_1024", "canonical_customer_id": "C1024", "mapping_method": "deterministic_customer_id", "mapping_status": "MATCHED", "confidence_band": "HIGH", "valid_from": "2026-08-12T09:05:00+05:30", "valid_to": "9999-12-31T00:00:00+00:00", "evidence_id": "EV-9903"},
]
write_csv(data_dir / "identity_mappings.csv", ["mapping_id", "source_system", "source_identifier", "canonical_customer_id", "mapping_method", "mapping_status", "confidence_band", "valid_from", "valid_to", "evidence_id"], identity_mappings)

# Evidence records: 100+ entries with statuses
raw_evidence = []
for idx in range(1, 121):
    raw_evidence.append({
        "evidence_id": f"EV-{idx:04d}",
        "source_type": "audit_log",
        "source_record": f"RUN-{idx:03d}",
        "source_url": f"https://example.invalid/audit/{idx:04d}",
        "timestamp": iso(datetime(2026, 8, 12, 9, 0, tzinfo=TIMEZONE) + timedelta(minutes=idx * 6)),
        "observed_time": iso(datetime(2026, 8, 12, 9, 0, tzinfo=TIMEZONE) + timedelta(minutes=idx * 6)),
        "ingested_at": iso(datetime(2026, 8, 12, 9, 0, tzinfo=TIMEZONE) + timedelta(minutes=idx * 7)),
        "raw_excerpt": f"Synthetic evidence item {idx:04d} for demo investigation.",
        "integrity_hash": f"sha256:{idx:04d}deadbeef",
        "evidence_status": "DIRECT",
        "source_system": "Synthetic Control Plane",
    })

# deliberate evidence records for the demo scenario
special_evidence = [
    {"evidence_id": "EV-0000", "source_type": "consent_event", "source_record": "CONS-C1024-002", "source_url": "https://example.invalid/consent/CONS-C1024-002", "timestamp": "2026-10-02T10:31:42+05:30", "observed_time": "2026-10-02T10:31:42+05:30", "ingested_at": "2026-10-02T10:31:43+05:30", "raw_excerpt": "Consent Service emitted withdrawal event CONS-C1024-002 for C1024 and purpose MARKETING.", "integrity_hash": "sha256:0000", "evidence_status": "DIRECT", "source_system": "Consent Service"},
    {"evidence_id": "EV-1001", "source_type": "database_audit", "source_record": "customer_preference_update", "source_url": "https://example.invalid/db/consent/C1024", "timestamp": "2026-10-02T10:31:46+05:30", "observed_time": "2026-10-02T10:31:46+05:30", "ingested_at": "2026-10-02T10:31:48+05:30", "raw_excerpt": "Customer preference update set marketing_consent = false for customer C1024 after withdrawal.", "integrity_hash": "sha256:1001", "evidence_status": "DIRECT", "source_system": "Customer Database"},
    {"evidence_id": "EV-1002", "source_type": "crm_audit", "source_record": "crm_preference_false", "source_url": "https://example.invalid/crm/consent/C1024", "timestamp": "2026-10-02T10:31:48+05:30", "observed_time": "2026-10-02T10:31:48+05:30", "ingested_at": "2026-10-02T10:31:49+05:30", "raw_excerpt": "CRM preference became false for Kiran Rao after withdrawal record was emitted.", "integrity_hash": "sha256:1002", "evidence_status": "DIRECT", "source_system": "CRM"},
    {"evidence_id": "EV-1003", "source_type": "warehouse_refresh_log", "source_record": "warehouse_consent_dimension_refresh", "source_url": "https://example.invalid/warehouse/refresh/consent", "timestamp": "2026-10-02T10:34:12+05:30", "observed_time": "2026-10-02T10:34:12+05:30", "ingested_at": "2026-10-02T10:34:13+05:30", "raw_excerpt": "Warehouse consent dimension refreshed and excluded C1024 from marketing after withdrawal.", "integrity_hash": "sha256:1003", "evidence_status": "DIRECT", "source_system": "Warehouse ETL"},
    {"evidence_id": "EV-2001", "source_type": "etl_job_run", "source_record": "ETL_17", "source_url": "https://example.invalid/jobs/ETL_17", "timestamp": "2026-10-02T10:45:00+05:30", "observed_time": "2026-10-02T10:45:00+05:30", "ingested_at": "2026-10-02T10:45:02+05:30", "raw_excerpt": "ETL Job #17 ran after withdrawal and processed the marketing purpose dataset.", "integrity_hash": "sha256:2001", "evidence_status": "DIRECT", "source_system": "Warehouse ETL"},
    {"evidence_id": "EV-2002", "source_type": "job_warning", "source_record": "USE_STALE_CONSENT_SNAPSHOT", "source_url": "https://example.invalid/jobs/ETL_17/warn", "timestamp": "2026-10-02T10:45:03+05:30", "observed_time": "2026-10-02T10:45:03+05:30", "ingested_at": "2026-10-02T10:45:05+05:30", "raw_excerpt": "Job warning: stale consent snapshot used for customer ID C1024.", "integrity_hash": "sha256:2002", "evidence_status": "STALE", "source_system": "Warehouse ETL"},
    {"evidence_id": "EV-2003", "source_type": "runtime_log", "source_record": "customer_analytics_table_update", "source_url": "https://example.invalid/warehouse/analytics/C1024", "timestamp": "2026-10-02T10:45:08+05:30", "observed_time": "2026-10-02T10:45:08+05:30", "ingested_at": "2026-10-02T10:45:09+05:30", "raw_excerpt": "Customer analytics table entry persisted for C1024 after withdrawal.", "integrity_hash": "sha256:2003", "evidence_status": "DIRECT", "source_system": "Customer Analytics Table"},
    {"evidence_id": "EV-3001", "source_type": "audience_membership", "source_record": "marketing_audience", "source_url": "https://example.invalid/audience/membership/C1024", "timestamp": "2026-10-02T10:45:12+05:30", "observed_time": "2026-10-02T10:45:12+05:30", "ingested_at": "2026-10-02T10:45:14+05:30", "raw_excerpt": "C1024 appears in marketing_audience for purpose MARKETING after withdrawal.", "integrity_hash": "sha256:3001", "evidence_status": "DIRECT", "source_system": "Marketing Audience Job"},
    {"evidence_id": "EV-3002", "source_type": "audience_suppression", "source_record": "marketing_audience_suppression", "source_url": "https://example.invalid/audience/suppression/C1024", "timestamp": "2026-10-02T11:05:00+05:30", "observed_time": "2026-10-02T11:05:00+05:30", "ingested_at": "2026-10-02T11:05:05+05:30", "raw_excerpt": "Audience suppression job removed C1024 from the marketing audience after remediation.", "integrity_hash": "sha256:3002", "evidence_status": "DIRECT", "source_system": "Marketing Audience Job"},
    {"evidence_id": "EV-4001", "source_type": "export_log", "source_record": "EXP-C1024-004", "source_url": "https://example.invalid/exports/EXP-C1024-004", "timestamp": "2026-10-02T10:47:03+05:30", "observed_time": "2026-10-02T10:47:03+05:30", "ingested_at": "2026-10-02T10:47:05+05:30", "raw_excerpt": "Export #4 sent C1024 to Processor X after withdrawal.", "integrity_hash": "sha256:4001", "evidence_status": "DIRECT", "source_system": "Processor X Export"},
    {"evidence_id": "EV-4002", "source_type": "no_acknowledgement", "source_record": "processor_ack_missing", "source_url": "https://example.invalid/processor/ack/missing/C1024", "timestamp": "2026-10-02T10:48:00+05:30", "observed_time": "2026-10-02T10:48:00+05:30", "ingested_at": "2026-10-02T10:48:02+05:30", "raw_excerpt": "No processor acknowledgement was recorded for this export at the cutoff.", "integrity_hash": "sha256:4002", "evidence_status": "ABSENT", "source_system": "Processor X"},
    {"evidence_id": "EV-4003", "source_type": "export_cancellation", "source_record": "EXP-C1024-004-STOP", "source_url": "https://example.invalid/exports/EXP-C1024-004-STOP", "timestamp": "2026-10-02T11:10:32+05:30", "observed_time": "2026-10-02T11:10:32+05:30", "ingested_at": "2026-10-02T11:10:34+05:30", "raw_excerpt": "Export cancellation executed after remediation and stopped the file transfer.", "integrity_hash": "sha256:4003", "evidence_status": "DIRECT", "source_system": "Processor X Export"},
    {"evidence_id": "EV-4004", "source_type": "processor_acknowledgement", "source_record": "ACK-STOP", "source_url": "https://example.invalid/processor/acks/ACK-STOP", "timestamp": "2026-10-02T11:12:00+05:30", "observed_time": "2026-10-02T11:12:00+05:30", "ingested_at": "2026-10-02T11:12:04+05:30", "raw_excerpt": "Processor acknowledgement confirmed suppression and no further processing.", "integrity_hash": "sha256:4004", "evidence_status": "DIRECT", "source_system": "Processor X"},
    {"evidence_id": "EV-9001", "source_type": "exception", "source_record": "EXC-001", "source_url": "https://example.invalid/exceptions/EXC-001", "timestamp": "2026-10-01T00:00:00+05:30", "observed_time": "2026-10-01T00:00:00+05:30", "ingested_at": "2026-10-01T00:00:10+05:30", "raw_excerpt": "Legal hold exception valid during the investigation window.", "integrity_hash": "sha256:9001", "evidence_status": "DIRECT", "source_system": "Privacy Review"},
    {"evidence_id": "EV-9901", "source_type": "identity_mapping", "source_record": "IM-001", "source_url": "https://example.invalid/idmapping/IM-001", "timestamp": "2026-08-12T09:05:00+05:30", "observed_time": "2026-08-12T09:05:00+05:30", "ingested_at": "2026-08-12T09:05:05+05:30", "raw_excerpt": "Deterministic mapping for Consent Service to customer C1024.", "integrity_hash": "sha256:9901", "evidence_status": "DIRECT", "source_system": "Identity Service"},
    {"evidence_id": "EV-9902", "source_type": "identity_mapping", "source_record": "IM-002", "source_url": "https://example.invalid/idmapping/IM-002", "timestamp": "2026-08-12T09:05:00+05:30", "observed_time": "2026-08-12T09:05:00+05:30", "ingested_at": "2026-08-12T09:05:10+05:30", "raw_excerpt": "CRM identity mapped directly to customer C1024.", "integrity_hash": "sha256:9902", "evidence_status": "DIRECT", "source_system": "Identity Service"},
    {"evidence_id": "EV-9903", "source_type": "identity_mapping", "source_record": "IM-003", "source_url": "https://example.invalid/idmapping/IM-003", "timestamp": "2026-08-12T09:05:00+05:30", "observed_time": "2026-08-12T09:05:00+05:30", "ingested_at": "2026-08-12T09:05:15+05:30", "raw_excerpt": "Warehouse ETL identity mapping to C1024 is deterministic and valid.", "integrity_hash": "sha256:9903", "evidence_status": "DIRECT", "source_system": "Identity Service"},
]
all_evidence = raw_evidence + special_evidence
write_csv(data_dir / "evidence.csv", ["evidence_id", "source_type", "source_record", "source_url", "timestamp", "observed_time", "ingested_at", "raw_excerpt", "integrity_hash", "evidence_status", "source_system"], all_evidence)

print(f"Synthetic data generated in {data_dir}")
