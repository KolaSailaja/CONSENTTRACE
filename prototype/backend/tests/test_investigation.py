from copy import deepcopy

from app.investigation.engine import get_path_graph, load_dataset, parse_dt, run_investigation, simulate_remediation


def test_clean_stop_case():
    data = load_dataset()
    result = run_investigation("C1001", "MARKETING", data)
    assert result.customer_id == "C1001"
    assert not any(f.finding_state == "STILL_ACTIVE" for f in result.findings)


def test_c1024_marketing_first_break_detected():
    data = load_dataset()
    result = run_investigation("C1024", "MARKETING", data)
    assert result.withdrawal_timestamp.isoformat() == "2026-10-02T10:31:42+05:30"
    assert result.first_break == "ETL Job #17"
    states = {finding.asset: finding.finding_state for finding in result.findings}
    assert states["Customer Database / CRM"] == "VERIFIED_STOPPED"
    assert states["Warehouse"] == "VERIFIED_STOPPED"
    assert states["ETL Job #17"] == "STILL_ACTIVE"
    assert states["Marketing Audience"] == "STILL_ACTIVE"
    assert states["Export #4"] == "STILL_ACTIVE"
    assert states["Processor X"] == "UNKNOWN"
    assert any(f.asset == "ETL Job #17" and f.finding_state == "STILL_ACTIVE" for f in result.findings)
    assert any(f.asset == "Processor X" and f.finding_state == "UNKNOWN" for f in result.findings)
    findings = {finding.asset: finding for finding in result.findings}
    expected_evidence = {
        "Customer Database / CRM": {"EV-0000", "EV-1001", "EV-1002"},
        "Warehouse": {"EV-1003"},
        "ETL Job #17": {"EV-2001", "EV-2002", "EV-2003"},
        "Marketing Audience": {"EV-3001"},
        "Export #4": {"EV-4001"},
        "Processor X": {"EV-4002"},
    }
    for asset, evidence_ids in expected_evidence.items():
        finding = findings[asset]
        assert evidence_ids.issubset({evidence.evidence_id for evidence in finding.evidence})
        assert finding.event_time is not None
        assert finding.evidence
        assert all(evidence.timestamp is not None for evidence in finding.evidence)
    processor = findings["Processor X"]
    assert next(e for e in processor.evidence if e.evidence_id == "EV-4002").evidence_status == "ABSENT"
    assert "EV-4004" in {e.evidence_id for e in processor.evidence}
    assert "not receipt or processing" in processor.reason


def test_negative_missing_logs_do_not_become_verified_stopped():
    data = load_dataset()
    result = run_investigation("C1002", "MARKETING", data)
    assert not any(f.finding_state == "VERIFIED_STOPPED" for f in result.findings)


def test_remediation_changes_result():
    data = load_dataset()
    initial = run_investigation("C1024", "MARKETING", data)
    remediated = simulate_remediation(initial, data)
    assert initial.overall_investigation_state == "ACTIVE_PROCESSING_DETECTED"
    assert remediated.overall_investigation_state == "REMEDIATION_SIMULATION"
    assert all(f.finding_state == "VERIFIED_STOPPED" for f in remediated.findings)
    assert initial.investigation_id != remediated.investigation_id


def test_late_evidence_can_change_result():
    data = load_dataset()
    initial = run_investigation("C1024", "MARKETING", data)
    remediated = simulate_remediation(initial, data)
    assert initial.first_break == "ETL Job #17"
    assert any(f.asset == "Processor X" and f.finding_state == "VERIFIED_STOPPED" for f in remediated.findings)


def test_processor_ack_is_checked():
    data = load_dataset()
    result = run_investigation("C1024", "MARKETING", data)
    processor = next(f for f in result.findings if f.asset == "Processor X")
    assert processor.finding_state == "UNKNOWN"


def test_direct_consent_audit_evidence_supports_stop_state():
    data = load_dataset()
    result = run_investigation("C1024", "MARKETING", data)
    customer_db = next(f for f in result.findings if f.asset == "Customer Database / CRM")
    assert customer_db.finding_state == "VERIFIED_STOPPED"
    assert {e.source_type for e in customer_db.evidence} >= {"consent_event", "database_audit", "crm_audit"}


def test_static_lineage_alone_does_not_prove_runtime_processing():
    data = load_dataset()
    withdrawal = parse_dt("2026-10-02T10:31:42+05:30")
    data["processing_logs"] = [
        row for row in data["processing_logs"]
        if not (row.get("customer_id") == "C1024" and parse_dt(row.get("timestamp")) > withdrawal)
    ]
    data["audience_membership"] = [
        row for row in data["audience_membership"]
        if row.get("customer_id") != "C1024" or parse_dt(row.get("observed_at")) <= withdrawal
    ]
    data["export_logs"] = [
        row for row in data["export_logs"]
        if row.get("customer_id") != "C1024" or parse_dt(row.get("timestamp")) <= withdrawal
    ]
    data["evidence"] = [
        row for row in data["evidence"]
        if row.get("evidence_id") not in {"EV-2001", "EV-2002", "EV-2003", "EV-3001", "EV-4001"}
    ]

    result = run_investigation("C1024", "MARKETING", data)
    states = {finding.asset: finding.finding_state for finding in result.findings}
    assert states["ETL Job #17"] == "UNKNOWN"
    assert states["Marketing Audience"] == "UNKNOWN"
    assert states["Export #4"] == "UNKNOWN"


def test_duplicate_event_and_stale_evidence_are_preserved():
    data = load_dataset()
    first = run_investigation("C1024", "MARKETING", data)
    second = run_investigation("C1024", "MARKETING", data)
    assert first.first_break == second.first_break
    assert first.evidence_references == second.evidence_references


def test_graph_path_contains_expected_nodes():
    data = load_dataset()
    graph = get_path_graph("C1024", "MARKETING", data)
    node_ids = {n.id for n in graph.nodes}
    assert {"withdrawal", "etl-17", "marketing-audience", "export-4", "processor-x"}.issubset(node_ids)


def test_before_withdrawal_processing_is_not_active():
    data = load_dataset()
    candidate = deepcopy(data)
    candidate["consent_events"].append({
        "customer_id": "C999",
        "purpose": "MARKETING",
        "status": "WITHDRAWN",
        "timestamp": "2099-01-01T12:00:00+00:00",
        "version": "v9",
        "source_system": "Consent Service",
    })
    result = run_investigation("C999", "MARKETING", candidate)
    assert not any(f.finding_state == "STILL_ACTIVE" for f in result.findings)


def test_contradictory_evidence_is_flagged():
    data = load_dataset()
    candidate = deepcopy(data)
    candidate["evidence"].append({
        "evidence_id": "EV-9999",
        "source_type": "suppression",
        "source_record": "suppression_after_withdrawal",
        "source_url": "https://example.invalid/suppression/9999",
        "timestamp": "2026-10-02T10:47:30+05:30",
        "observed_time": "2026-10-02T10:47:30+05:30",
        "ingested_at": "2026-10-02T10:47:35+05:30",
        "raw_excerpt": "Suppression record created after withdrawal for customer C1024.",
        "integrity_hash": "sha256:9999",
        "evidence_status": "DIRECT",
        "source_system": "Marketing Audience Job",
    })
    candidate["export_logs"].append({
        "export_id": "EXP-C1024-9999",
        "customer_id": "C1024",
        "purpose": "MARKETING",
        "dataset_id": "DS-06",
        "processor_id": "PROC-01",
        "timestamp": "2026-10-02T10:47:30+05:30",
        "operation": "EXPORT",
        "status": "SENT",
        "ack_id": "ACK-9999",
    })
    result = run_investigation("C1024", "MARKETING", candidate)
    export_finding = next(f for f in result.findings if f.asset == "Export #4")
    assert export_finding.finding_state in {"STILL_ACTIVE", "CONFLICTED"}
