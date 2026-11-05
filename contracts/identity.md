# Contract — Identity

Purpose: one stable identity scheme for tasks, attempts, results, and
fact/records across all PAI systems, so any object can be cited, linked, and
reconciled across machines without name collisions or silent re-identity.

## Rules

1. Every task, attempt, result, claim, and fact/record carries exactly one ID,
   assigned once by its owning system at creation. An ID is never reused,
   never reassigned, and never derived from the object's content.

   **Clarification (ratified by Tan, 2026-11-05 — see
   `docs/decisions/DECISION_2026-11-05_RULE1_CLARIFICATION_RATIFIED.md`):**
   "Carries exactly one ID" in this rule means exactly one **native identity**:
   the ID assigned once by the object's owning system. Typed references to other
   objects' IDs are references, not identities — this contract itself requires
   them (rules 2, 5, 7) — and rule 1 does not prohibit them. A Cabinet ID
   (`cab-NNNN`) carried by a record is such a reference: a foreign key to a
   separately identified **work-area grouping**, never an identifier of the
   record itself. It never renames, re-keys, or supersedes the native ID; a
   record is addressed and cited only by its native (owning-system, ID) pair,
   which MAY be annotated with its Cabinet ID — the annotation never substitutes
   for the pair. A bare Cabinet ID identifies a work area only, within the
   Cabinet namespace. Primary/secondary/pending membership follows the Cabinet
   spec's policy; shared membership asserts only "concerns this work area" and
   merges no kinds, lifecycles, or semantics (rule 7). **No admission, dispatch,
   lease/fence, closure, ownership, or execution-authority decision may be
   inferred from a Cabinet match** (rule 4 is unaffected). Cabinet IDs are
   allocated only by the Cabinet Registrar, sequentially, never reused, and
   without reference to any record's content; membership changes are append-only
   registry events (LINK / UNLINK, each with evidence, actor, timestamp, and
   reason).
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

- No global ID-minting service in this phase; owning systems keep minting. [*]
- No renaming or re-keying of existing IDs in legacy stores.
- No identity for transient runtime objects (processes, sockets, sessions)
  beyond their host's own bookkeeping.

[*] The Cabinet Registrar **is** the central allocator of grouping keys for the
Cabinet namespace — a registry-keeping function of the PAI Repo program,
deliberately not a runtime service. Owning systems still mint all native IDs.
This footnote records that scope honestly: the non-goal bars a global runtime
ID-minting service; the Registrar's central grouping-key allocation is the
recorded exception, ratified with the rule-1 clarification on 2026-11-05.
