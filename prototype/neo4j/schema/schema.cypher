CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.customer_id IS UNIQUE;
CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:Evidence) REQUIRE e.evidence_id IS UNIQUE;
CREATE CONSTRAINT investigation_id IF NOT EXISTS FOR (i:Investigation) REQUIRE i.investigation_id IS UNIQUE;

CREATE (:Person {customer_id: 'C1024', name: 'Kiran Rao'});
CREATE (:Purpose {name: 'MARKETING'});
CREATE (:System {system_id: 'SYS-03', name: 'Customer Database'});
CREATE (:System {system_id: 'SYS-04', name: 'CRM'});
CREATE (:System {system_id: 'SYS-06', name: 'Warehouse ETL'});
CREATE (:System {system_id: 'SYS-08', name: 'Marketing Audience Job'});
CREATE (:System {system_id: 'SYS-09', name: 'Processor X Export'});
CREATE (:System {system_id: 'SYS-10', name: 'Processor X'});

MATCH (p:Person {customer_id: 'C1024'}), (purpose:Purpose {name: 'MARKETING'}), (db:System {system_id: 'SYS-03'}), (crm:System {system_id: 'SYS-04'}), (etl:System {system_id: 'SYS-06'}), (aud:System {system_id: 'SYS-08'}), (exp:System {system_id: 'SYS-09'}), (proc:System {system_id: 'SYS-10'})
CREATE (p)-[:GAVE_CONSENT_FOR]->(:Consent {purpose: 'MARKETING', status: 'CONSENTED', timestamp: '2026-08-12T09:05:00+05:30'})
CREATE (p)-[:WITHDREW_CONSENT_FOR]->(:WithdrawalEvent {purpose: 'MARKETING', timestamp: '2026-10-02T10:31:42+05:30'})
CREATE (db)-[:OWNS_DATASET]->(:Dataset {dataset_id: 'DS-01', name: 'customer_db'})
CREATE (crm)-[:OWNS_DATASET]->(:Dataset {dataset_id: 'DS-02', name: 'crm_customer_profile'})
CREATE (etl)-[:OWNS_DATASET]->(:Dataset {dataset_id: 'DS-05', name: 'customer_analytics_table'})
CREATE (aud)-[:OWNS_DATASET]->(:Dataset {dataset_id: 'DS-06', name: 'marketing_audience'})
CREATE (exp)-[:OWNS_DATASET]->(:Dataset {dataset_id: 'DS-07', name: 'processor_x_export'})
CREATE (proc)-[:OWNS_DATASET]->(:Dataset {dataset_id: 'DS-08', name: 'processor_x_inbox'})
CREATE (db)-[:HAS_RUN]->(:JobRun {run_id: 'RUN-ETL-017', timestamp: '2026-10-02T10:45:00+05:30'})
CREATE (etl)-[:HAS_RUN]->(:JobRun {run_id: 'RUN-ETL-017', timestamp: '2026-10-02T10:45:00+05:30'})
CREATE (:Evidence {evidence_id: 'EV-2002', source_record: 'USE_STALE_CONSENT_SNAPSHOT'})
CREATE (:Finding {asset: 'ETL Job #17', state: 'STILL_ACTIVE'})
;
