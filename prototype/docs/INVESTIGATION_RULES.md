# INVESTIGATION RULES

## Rule 1: Static lineage is not runtime evidence

Static lineage describes what could flow through a system. It does not prove that processing actually occurred. The engine requires runtime evidence such as job runs, audience membership records, export logs, or acknowledgements before classifying a downstream asset as `STILL_ACTIVE`.

## Rule 2: Missing logs are not proof of stoppage

Absence of a log is evidence of absence only when the observation window has closed and relevant evidence has been audited. Otherwise the result remains `UNKNOWN` or `PENDING`.

## Rule 3: Conflicts become `CONFLICTED`

If direct evidence points in opposite directions, the engine marks the finding as `CONFLICTED` and surfaces the contradictory evidence rather than forcing a single conclusion.

## Rule 4: Watermark and observation window affect `PENDING`

If the investigation watermarks have not been reached, the engine returns `PENDING` instead of finalizing a result. This preserves uncertainty in evolving systems.

## Rule 5: Exceptions are evaluated explicitly

A valid exception can override a generally active path only when it is scoped to the relevant person, purpose, system, and time validity window.

## Rule 6: First break detection

The engine traverses the downstream path from withdrawal to the earliest node where propagation fails or remains unresolved. The first confirmed break is the earliest asset with direct post-withdrawal processing or contradictory unresolved evidence.

## Rule 7: Identity mapping is deterministic

The system uses pre-created identity mappings for controlled resolution. If identity mapping fails or confidence is insufficient, the result is `UNKNOWN` instead of a guess.

## Rule 8: Remediation is a new evidence event

After a remediation simulation, the previous investigation remains as historical evidence, and a new investigation is created using new runtime facts and evidence.

## Verified runtime behavior for the seeded demo

The default C1024 / MARKETING scenario currently resolves the first confirmed break at ETL Job #17. The engine requires post-withdrawal runtime evidence to classify an asset as STILL_ACTIVE. A remediation run switches the result to VERIFIED_STOPPED only when new runtime evidence such as suppression, cancellation, or acknowledgement records are applied in a separate investigation event.
