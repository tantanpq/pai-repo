# Contract — Lifecycle

Purpose: one lifecycle vocabulary for claims/facts and for tasks, where every
state change is an appended, auditable event — nothing is silently edited,
merged, or deleted.

## Rules

1. Fact/claim states: `unadmitted` → `admitted` → one of `invalidated`,
   `superseded`, `expired`. No other transitions are valid; a record never
   returns from a terminal state (a correction is a NEW record that
   supersedes the old one).
2. Two-layer time: `valid_at` is set when a record is admitted; `invalid_at`
   is set when it is invalidated, superseded, or expired. Empty `invalid_at`
   means currently in force.
3. INVALIDATE semantics: invalidation appends an event carrying reason,
   actor, timestamp, and — when one exists — a pointer to the replacement
   record. The original record's content is never edited or deleted.
4. Default retrieval MUST exclude records whose `invalid_at` is set.
   Invalidated records are returned only when history is explicitly
   requested, and are then marked as invalidated.
5. Every state transition of any governed object is an event in an
   append-only mutation ledger: (entity (system, ID), from-state, to-state,
   at, actor, reason). The ledger is the only write path for lifecycle
   changes; there are no silent edits.
6. Task lifecycle (execution): `created` → `admitted` → `claimed` →
   `running` → `result-recorded` → `closed`. Leases, fences, and digests are
   HOME-authority semantics; read-models mirror task state read-only and
   MUST NOT originate transitions.
7. Dedup is tiered and deterministic: exact match → identity attributes →
   high similarity. An ambiguous pair is kept as two records plus a flag for
   a human decision — never auto-merged.
8. Retirement (`expired`) is a lifecycle event with a reason, not a deletion.
   Physical deletion happens only under the admission-privacy-forget
   contract's forget procedure.

## Non-goals

- This contract does not schedule work and does not define retry policy.
- No retroactive rewriting of historical ledgers; past events stand as written.
- No LLM participation in any lifecycle transition (plan §3 rule 1).
