# Contract — Identity

Purpose: one stable identity scheme for tasks, attempts, results, and
fact/records across all PAI systems, so any object can be cited, linked, and
reconciled across machines without name collisions or silent re-identity.

## Rules

1. Every task, attempt, result, claim, and fact/record carries exactly one ID,
   assigned once by its owning system at creation. An ID is never reused,
   never reassigned, and never derived from the object's content.
2. IDs are namespaced by owning system (e.g. `home-runloop:`, `vm-spine:`,
   `claim-register:`). A cross-system reference is always the pair
   (owning-system, ID) — a bare ID is not a valid cross-system citation.
3. `content_hash` (SHA-256 over the object's canonical bytes) detects change
   only. Changing content MUST change the hash and MUST NOT change the ID.
   A hash is never used as an ID.
4. Every task has exactly one execution authority (per locked decision 1:
   HOME). Mirrors and read-models (e.g. the VM spine) carry the authority's
   (system, ID) pair plus a local pointer; a mirror never mints a second
   identity for the same task.
5. An attempt references exactly one task ID plus a monotonically increasing
   attempt ordinal. A result references exactly one (task ID, attempt ordinal).
6. A fact/record carries a provenance anchor to its immutable source segment
   in the form `path#line` (file path plus line or heading anchor). A fact
   without a resolvable anchor is an orphan and MUST NOT be admitted.
7. Claim-register claims (epistemic assertions) and HOME execution claims
   (work leases) are different object kinds. They link by (system, ID) pairs;
   their identities and semantics MUST NOT be merged because they share the
   word "claim".

## Non-goals

- No global ID-minting service in this phase; owning systems keep minting.
- No renaming or re-keying of existing IDs in legacy stores.
- No identity for transient runtime objects (processes, sockets, sessions)
  beyond their host's own bookkeeping.
