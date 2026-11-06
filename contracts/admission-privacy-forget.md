# Contract — Admission · Privacy · Forget

Purpose: govern which records may enter the cabinet, who/what may read them,
and how forgetting works — with namespaces kept separate and admission kept
deterministic.

## Rules

1. Every record belongs to exactly one namespace: a cabinet room or an
   owner scope (e.g. `room:decisions`, `owner:home-personal-memory`).
   Cross-namespace reads go through the retrieval contract surface, never
   through shared tables or copied files.
2. Admission states are `unadmitted`, `admitted`, `invalidated`. Only
   `admitted` records are retrievable by default. Unadmitted material
   (inbox/staging) is never promoted automatically and never surfaces in
   default query results.
3. Admission is by rule or by the namespace owner's recorded decision.
   No LLM admits, promotes, or rejects records (plan §3 rule 1).
4. Privacy levels are exactly: `house` (internal house use), `private`
   (principal-only), `secret-pointer` (the record stores only a pointer to
   where the secret lives — never the secret itself). A record's privacy
   level travels with every derived fact and index entry made from it.

   **Default for unmarked claim-register records (decided by Tan, 2026-11-05 —
   `docs/decisions/DECISION_2026-11-05_UNMARKED_DEFAULT_HOUSE.md`):** a
   claim-register record carrying no `privacy` field is `house`. This ratifies
   as policy the default the Phase 2 retrieval implementation applies in code
   (namespace `room:decisions`). An explicit field always wins; other
   namespaces are unaffected.

   **Extension to the HOME namespaces (decided by Tan, 2026-11-05 —
   `docs/decisions/DECISION_2026-11-05_HOME_NAMESPACES_HOUSE_DEFAULT.md`):**
   an unmarked record in the `home-runloop` or `home-claim-service` namespace
   is likewise `house` for all inheritance purposes. An explicit field always
   wins; namespaces other than claim-register, home-runloop and
   home-claim-service have no default.

   **Extension to the vm-spine namespace (adopted by Leona, 2026-11-05 —
   `docs/decisions/ADOPTION_2026-11-05_VMSPINE_HOUSE_DEFAULT.md`):** an
   unmarked record in the `vm-spine` namespace is likewise `house` for all
   inheritance purposes. An explicit field always wins; namespaces other
   than claim-register, home-runloop, home-claim-service and vm-spine have
   no default. The C1 record's scope sentence is superseded in part by the
   two extensions; the decision records themselves are not edited.
5. Agent-private stores (Codex, Grok, Gemini/Antigravity, Claude histories)
   are outside PAI namespaces. Only explicit, scoped, provenance-preserving
   exports from them may be admitted; raw histories are never merged.
6. Forget procedure, in order: (a) lifecycle event invalidating the record
   with reason `forget`; (b) a tombstone remains carrying (system, ID),
   forget timestamp and actor — content does not remain; (c) index entries
   and derived facts sourced from the record are purged or invalidated in
   the same operation; (d) post-forget verification: a default query returns
   the tombstone, not the content.
7. Physical deletion of source-of-truth files happens only under a recorded
   owner decision (a `docs/decisions/` entry). Forgetting metadata or index
   entries never silently deletes source truth, and deleting a source never
   silently leaves derived facts admitted.

## Non-goals

- No multi-tenant machinery: no orgs, ACL matrices, or role systems
  (plan §3 rule 8 — PAI has one principal).
- No encryption design in this contract; secret storage stays with the
  hosts' existing protected locations.
- No retention schedule invention: retention follows owner decisions, not
  this contract.
