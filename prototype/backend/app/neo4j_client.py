from __future__ import annotations

from typing import Any

try:  # pragma: no cover - optional runtime dependency
    from neo4j import GraphDatabase
except ModuleNotFoundError:  # pragma: no cover - handled gracefully
    GraphDatabase = None

from app.config import settings


class Neo4jClient:
    def __init__(self) -> None:
        self._driver = None

    def health_check(self) -> dict[str, Any]:
        if GraphDatabase is None:
            return {"reachable": False, "status": "driver_missing"}
        try:
            driver = self._driver_instance()
            with driver.session(database="neo4j") as session:
                session.run("RETURN 1")
            return {"reachable": True, "status": "reachable"}
        except Exception as exc:  # pragma: no cover - runtime dependency path
            return {"reachable": False, "status": "unreachable", "error": type(exc).__name__}

    def _driver_instance(self):
        if GraphDatabase is None:
            raise ModuleNotFoundError("neo4j package is not installed")
        if self._driver is not None:
            return self._driver
        try:
            self._driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
            self._driver.verify_connectivity()
        except Exception:
            self._driver = None
            raise
        return self._driver

    def project_event(self, event: dict[str, Any], evidence: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
        payload = payload or {}
        try:
            driver = self._driver_instance()
        except Exception:
            return "GRAPH_PROJECTION_FAILED"

        with driver.session(database="neo4j") as session:
            def write_projection(tx):
                tx.run(
                    """
                    MERGE (person:Person {organization_id: $organization_id, person_ref: $person_ref})
                    MERGE (purpose:Purpose {organization_id: $organization_id, name: $purpose})
                    MERGE (event:Event {event_id: $event_id, organization_id: $organization_id})
                    MERGE (evidence:Evidence {evidence_id: $evidence_id, organization_id: $organization_id})
                    SET event.type = $event_type,
                        event.event_time = $event_time,
                        event.source_system = $source_system,
                        event.source_event_id = $event_id,
                        event.projection_status = 'GRAPH_PROJECTED'
                    SET evidence.source_event_id = $event_id,
                        evidence.content_hash = $content_hash,
                        evidence.hash_algorithm = $hash_algorithm,
                        evidence.observed_time = $observed_time
                    MERGE (person)-[:HAS_PURPOSE]->(purpose)
                    MERGE (person)-[:HAS_EVENT]->(event)
                    MERGE (event)-[:HAS_EVIDENCE]->(evidence)
                    """,
                    organization_id=event["organization_id"],
                    person_ref=event["person_ref"],
                    purpose=event["purpose"] or "UNKNOWN",
                    event_id=event["event_id"],
                    event_type=event["event_type"],
                    event_time=event["event_time"].isoformat() if event.get("event_time") else None,
                    source_system=event["source_system"],
                    evidence_id=evidence["evidence_id"],
                    content_hash=evidence["content_hash"],
                    hash_algorithm=evidence["hash_algorithm"],
                    observed_time=evidence["observed_time"].isoformat() if evidence.get("observed_time") else None,
                )
                asset_payload = payload.get("asset")
                if isinstance(asset_payload, dict) and all(
                    asset_payload.get(field) for field in ("id", "name", "type")
                ):
                    tx.run(
                        """
                        MATCH (event:Event {organization_id: $organization_id, event_id: $event_id})
                        MERGE (asset:Asset {organization_id: $organization_id, asset_id: $asset_id})
                        SET asset.name = $name, asset.asset_type = $asset_type
                        MERGE (event)-[:AFFECTS]->(asset)
                        WITH event, asset
                        MATCH (purpose:Purpose {organization_id: $organization_id, name: $purpose})
                        MERGE (purpose)-[:AFFECTS]->(asset)
                        """,
                        organization_id=event["organization_id"],
                        event_id=event["event_id"],
                        purpose=event["purpose"] or "UNKNOWN",
                        asset_id=asset_payload["id"],
                        name=asset_payload["name"],
                        asset_type=asset_payload["type"],
                    )
                if payload.get("lineage_edges"):
                    tx.run(
                        """
                        UNWIND $edges AS edge
                        MERGE (source:Asset {organization_id: $organization_id, asset_id: edge.from_id})
                        SET source.name = edge.from_name, source.asset_type = edge.from_type
                        MERGE (target:Asset {organization_id: $organization_id, asset_id: edge.to_id})
                        SET target.name = edge.to_name, target.asset_type = edge.to_type
                        MERGE (source)-[lineage:LINEAGE {relationship: edge.relationship}]->(target)
                        """,
                        organization_id=event["organization_id"],
                        edges=payload["lineage_edges"],
                    )
            session.execute_write(write_projection)

        if event["event_type"] == "CONSENT_WITHDRAWN":
            with driver.session(database="neo4j") as session:
                session.execute_write(
                    lambda tx: tx.run(
                        """
                        MERGE (person:Person {organization_id: $organization_id, person_ref: $person_ref})
                        MERGE (purpose:Purpose {organization_id: $organization_id, name: $purpose})
                        MERGE (withdrawal:WithdrawalEvent {organization_id: $organization_id, event_id: $event_id})
                        SET withdrawal.event_time = $event_time,
                            withdrawal.source_system = $source_system
                        MERGE (person)-[:HAS_WITHDRAWAL]->(withdrawal)
                        MERGE (purpose)-[:HAS_WITHDRAWAL]->(withdrawal)
                        """,
                        organization_id=event["organization_id"],
                        person_ref=event["person_ref"],
                        purpose=event["purpose"] or "UNKNOWN",
                        event_id=event["event_id"],
                        event_time=event["event_time"].isoformat() if event.get("event_time") else None,
                        source_system=event["source_system"],
                    )
                )
        elif event["event_type"] == "SUPPRESSION_COMPLETED":
            with driver.session(database="neo4j") as session:
                session.execute_write(
                    lambda tx: tx.run(
                        """
                        MERGE (person:Person {organization_id: $organization_id, person_ref: $person_ref})
                        MERGE (purpose:Purpose {organization_id: $organization_id, name: $purpose})
                        MERGE (suppression:SuppressionEvent {organization_id: $organization_id, event_id: $event_id})
                        SET suppression.event_time = $event_time,
                            suppression.source_system = $source_system
                        MERGE (person)-[:HAS_SUPPRESSION]->(suppression)
                        MERGE (purpose)-[:HAS_SUPPRESSION]->(suppression)
                        """,
                        organization_id=event["organization_id"],
                        person_ref=event["person_ref"],
                        purpose=event["purpose"] or "UNKNOWN",
                        event_id=event["event_id"],
                        event_time=event["event_time"].isoformat() if event.get("event_time") else None,
                        source_system=event["source_system"],
                    )
                )
        return "GRAPH_PROJECTED"

    def get_lineage(self, organization_id: str, person_ref: str, purpose: str) -> list[dict[str, str]]:
        driver = self._driver_instance()
        with driver.session(database="neo4j") as session:
            records = session.run(
                """
                MATCH (person:Person {organization_id: $organization_id, person_ref: $person_ref})
                      -[:HAS_PURPOSE]->
                      (purpose:Purpose {organization_id: $organization_id, name: $purpose})
                      -[:AFFECTS]->
                      (start:Asset {organization_id: $organization_id})
                MATCH path = (start)-[:LINEAGE*0..12]->(target:Asset {organization_id: $organization_id})
                UNWIND relationships(path) AS lineage
                RETURN DISTINCT startNode(lineage).asset_id AS from_id,
                       startNode(lineage).name AS from_name,
                       startNode(lineage).asset_type AS from_type,
                       lineage.relationship AS relationship,
                       endNode(lineage).asset_id AS to_id,
                       endNode(lineage).name AS to_name,
                       endNode(lineage).asset_type AS to_type
                ORDER BY from_id, to_id
                """,
                organization_id=organization_id,
                person_ref=person_ref,
                purpose=purpose,
            )
            return [dict(record) for record in records]

    def clear_organization(self, organization_id: str) -> None:
        driver = self._driver_instance()
        with driver.session(database="neo4j") as session:
            session.run(
                """
                MATCH (node {organization_id: $organization_id})
                DETACH DELETE node
                """,
                organization_id=organization_id,
            )


neo4j_client = Neo4jClient()
