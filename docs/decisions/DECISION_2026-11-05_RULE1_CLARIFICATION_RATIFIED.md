# DECISION 2026-11-05 — Rule-1 clarification RATIFIED (Cabinet ID / Step 0)

- **Decided by:** Tan, main chat, 2026-11-05 12:16 PT — replied "1" to Leona's numbered options
  (protocol 1-2-3): "Ratify clarification nhu da soan" (ratify the clarification as drafted).
- **What was ratified:** the clarification of identity-contract rule 1 drafted in
  `docs/CABINET_ID_SPEC_V1.md` section 7 — "carries exactly one ID" means exactly one NATIVE
  identity assigned by the owning system; a Cabinet ID (`cab-NNNN`) is a typed foreign reference
  to a work-area grouping, never a second identity; records are addressed/cited only by their
  native (owning-system, ID) pair, optionally annotated with the Cabinet ID; NO admission,
  dispatch, lease/fence, closure, ownership, or execution-authority decision may be inferred
  from a Cabinet match; plus footnote [*] recording the Cabinet Registrar as the central
  allocator of grouping keys for the Cabinet namespace (a registry-keeping function, not a
  runtime service; owning systems still mint all native IDs).
- **Review backing (independent, complete before ratification):** Codex review of Phase 3
  slice 1 returned FAIL with 9 findings; three fix rounds; final targeted re-review 3
  (`pai-repo-program/phase3/CODEX_REREVIEW_SLICE1_FIX3_2026-11-05.md`) PASS on both remaining
  routes, open list empty. Finding F09 had already ruled this draft "safe and sufficient as a
  narrowly scoped ratification candidate".
- **Effect:** the clarification note is recorded under rule 1 in `contracts/identity.md` and
  footnote [*] is added to its non-goals, in the same commit as this record. Step 0 of the
  Cabinet backfill plan is satisfied; Phase 3 implementation (Cabinet Registrar registry +
  backfill, starting with Step 1: the 17-task / 25-claim seam) is unblocked. The M8 / Store
  ambiguous pair remains a pending exhibit for a separate human decision, per the plan.
