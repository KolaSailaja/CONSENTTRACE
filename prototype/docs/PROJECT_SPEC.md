# PROJECT SPEC

## What it is

CONSENTTRACE is a synthetic evidence-first privacy investigation tool for reconstructing downstream processing after consent withdrawal. The system investigates runtime events and evidence to determine the first confirmed propagation break.

## Users

- Privacy operations analyst
- DPO analyst
- Data governance engineer
- Internal audit/compliance analyst

## Must do

- Constrain investigations to a person + purpose + withdrawal + time window
- Preserve uncertain states using `PENDING`, `UNKNOWN`, and `CONFLICTED`
- Separate control plane, data plane, and evidence plane
- Use deterministic rule-based investigation logic
- Show explicit evidence and timestamps
- Identify the first confirmed break in withdrawal propagation

## Must not do

- Generic consent management
- Legal compliance certification
- Automatic deletion or processor commands
- AI-based compliance decisions
- Static lineage-only decisions

## Data model

The synthetic dataset includes AcmePay systems, datasets, pipeline jobs, identity mappings, exports, acknowledgements, and evidence artifacts. All data is synthetic and uses `.invalid` domains for email addresses.

## Constraints

- No real personal data
- Evidence must be provable and traceable
- Missing evidence is not proof of stopped processing
- Static lineage is not runtime evidence

## Done condition

The MVP is complete when a user can investigate `C1024` and `MARKETING`, review evidence, identify the first confirmed break, simulate remediation, rerun the investigation, and preserve historical findings.

## Unknowns

The application is designed as a technical evidence viewer and does not offer legal advice or compliance certification. Any AI explanations are clearly marked as supportive and non-authoritative.
