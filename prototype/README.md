# CONSENTTRACE

CONSENTTRACE is an evidence-backed privacy operations investigation tool that reconstructs whether a consent withdrawal propagated through downstream systems and leaves a durable audit trail of the evidence.

## Core principle

The product does not decide legal compliance. It reconstructs the evidence so a human investigator can determine what happened and what remains uncertain.

## Architecture

- Frontend: Next.js + TypeScript
- Backend: FastAPI + Pydantic
- Investigation engine: deterministic Python logic
- Relational evidence layer: PostgreSQL schema and seed artifacts
- Graph lineage layer: Neo4j topology artifacts

## Runtime modes

### Unit mode (default)

Use SQLite for local validation and fast tests without external services.

```bash
cd backend
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONPATH='.'
python -m pytest tests/test_ingestion.py tests/test_investigation.py tests/test_evidence_api.py -q
```

### Real stack mode

Use PostgreSQL and Neo4j for live verification.

1. Copy `.env.example` to `.env` and adjust values as needed.
2. Ensure Docker is running.
3. Start the stack:

```bash
docker compose up --build
```

4. Confirm health:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

5. Run the real-stack integration test only when the environment is explicitly configured:

```bash
cd backend
$env:REAL_STACK_MODE='1'
$env:PYTHONPATH='.'
python -m pytest tests/test_real_stack_e2e.py -q
```

## Environment variables

`.env.example` documents the required variables for both SQLite and Docker-backed modes.

- `DATABASE_URL`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `REAL_STACK_MODE`

Inside Docker, `POSTGRES_HOST` must be the Compose service name (`postgres`) and `NEO4J_URI` must point at `bolt://neo4j:7687` instead of `localhost`.

## Quick start

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and use the canonical customer `C1024` with purpose `MARKETING`.

## Canonical demo scenario

- Customer: `C1024` — Kiran Rao
- Purpose: `MARKETING`
- Withdrawal: `2026-10-02T10:31:42+05:30`
- First confirmed break: `ETL Job #17`

The investigation should surface a stale consent snapshot that continued to feed the downstream marketing audience and export path.

## Demo script

1. Open CONSENTTRACE.
2. Explain the problem in one sentence: a withdrawal occurred, and the tool reconstructs whether downstream systems continued processing. 
3. Select `C1024` and `MARKETING`.
4. Run the investigation.
5. Point to the withdrawal timestamp and the first confirmed break.
6. Open the ETL evidence and explain the stale snapshot.
7. Trace the audience and export impact.
8. Highlight the processor result as `UNKNOWN` and explain that this means insufficient evidence, not a stopped state.
9. Simulate remediation.
10. Re-investigate and compare before/after states.

The presentation should take roughly 2–4 minutes.

## Verification

```bash
cd backend
python -m pytest -q
```

```bash
cd frontend
npm run build
```

## Important constraint

This tool is evidence-first. It preserves uncertainty, surfaces contradictory or missing evidence, and avoids pretending to be a legal verdict engine.
