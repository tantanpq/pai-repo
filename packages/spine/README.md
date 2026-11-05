# packages/spine — spine read-model & ingestion

Responsibility: Ingestion and read-model of the typed task+evidence spine. HOME is the execution authority (locked decision 1); this package mirrors HOME task/evidence state read-only, keeps the VM ingestion pipeline (shadow-1a lineage) as the read-model source, and links the claim-register as a separate epistemic ledger by (system, ID) pairs — never merged semantics.

Contract dependencies: contracts/identity.md · contracts/lifecycle.md · contracts/host-qualification.md

Status: Phase 1 skeleton — implementation lands in its phase.
