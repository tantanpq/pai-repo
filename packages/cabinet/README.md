# packages/cabinet — rooms, consolidation, lifecycle engine

Responsibility: The filing cabinet itself: room registry (a room = real directory + named index set + schema'd tag set), the deterministic consolidator that derives facts from immutable sources, tiered dedup, and the invalidate/lifecycle machinery over cabinet records.

Contract dependencies: contracts/identity.md · contracts/lifecycle.md · contracts/admission-privacy-forget.md

Status: Phase 1 skeleton — implementation lands in its phase.

Tooling: `registrar.py` — the production Cabinet Registrar append/project
tool (spec §3–§4: expected-head acceptance, allocation from the greatest
accepted MINT, full candidate-fold validation, append-only writes,
MINT/LINK/UNLINK projection with readback, governed partial-tail
recovery — only an unterminated final line is a partial tail; hard §4
errors are never truncated, and every recovery writes its §4 removal
record to INDEX.md before truncating — plus `forget-member`, the §6
same-operation linkage purge). It replaces the Step 1 genesis builder
for all appends from Step 2 onward. Tests: `tests/test_registrar.py`
(scratch registries only, plus a read-only projection-parity check
against the accepted registry).

Tooling: `read_api.py` — the Phase 3 read API: one read-only surface
across the Cabinet namespaces with per-namespace rights enforced
(contract rule 4 / spec §6: explicit field wins, ratified namespace
defaults, unknown = no read entitlement, HOME namespaces registry-only
per §5.1). Usage: `READ_API.md`. Tests: `tests/test_read_api.py`
(fixture-local state only).
