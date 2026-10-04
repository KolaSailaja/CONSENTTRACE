# DEMO

## Canonical scenario

Customer: `C1024`
Purpose: `MARKETING`
Withdrawal time: `2026-10-02T10:31:42+05:30`

## Presenter script

1. Open CONSENTTRACE and explain the product in one sentence: it reconstructs whether consent withdrawals propagated downstream.
2. Select `C1024` and `MARKETING`.
3. Click `Investigate withdrawal`.
4. Point to the withdrawal timestamp and the first confirmed break.
5. Explain that the stale ETL snapshot is the earliest confirmed runtime break.
6. Open the evidence detail for `ETL Job #17` and explain the missing or stale consent state.
7. Walk through the downstream audience and export nodes.
8. Highlight the processor as `UNKNOWN` and explain that this means there is not enough evidence to prove it stopped, not that it is confirmed active.
9. Trigger `Simulate remediation` and explain the evidence-backed cleanup path.
10. Re-investigate and show the before/after comparison.

Expected outcome: the initial investigation identifies stale ETL processing as the first break, while the processor layer remains `UNKNOWN` until explicit evidence exists. After remediation, the path should reflect the new evidence, not a generic score.
