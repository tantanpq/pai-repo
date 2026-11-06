# DECISION 2026-11-05 — Unmarked HOME-namespace records default to `house` (Phase 3 finding F02)

- **Decided by:** Tan, main chat, 2026-11-05 18:59 PT — replied "1" to Leona's numbered
  options (protocol 1-2-3): "Mo rong mac dinh house cho hai namespace HOME" (extend the
  `house` default to the two HOME namespaces). Leona's recommendation, stated before the
  options, was option 1.
- **Question (from CODEX_REVIEW_STEP2_2026-11-05.md finding F02):** backfill Step 2 stamped
  members from the two HOME namespaces (home-runloop work units, claim-service claims) into
  the cabinet registry. HOME source records carry no privacy level.
  DECISION_2026-11-05_UNMARKED_DEFAULT_HOUSE (C1) scoped its default explicitly to the
  claim-register namespace ("other namespaces are unaffected"), so spec section 6
  inheritance for HOME members had no policy to inherit from — check 4 NOT VERIFIED.
- **Decision:** an unmarked record in the `home-runloop` or `home-claim-service` namespace
  is **`house`** for all section 6 inheritance purposes (registry entries, INDEX.md,
  projections, retrieval), the same default C1 set for the claim-register namespace.
  Rationale (as presented to the owner): both HOME namespaces are operational records of
  the owner's own machines — the same trust domain as the claim register, with no external
  party. An explicit `privacy` field on a record always wins over this default; the
  strictest-member rule for combined entries is unchanged; namespaces other than
  claim-register, home-runloop and home-claim-service remain unaffected (no default).
- **Effect on C1:** C1's scope sentence is superseded in part by this record — the default
  now covers three named namespaces. C1 otherwise stands (its record is not edited;
  decision history is append-only).
- **Effect on Step 2:** F02's policy half is satisfied by this record plus the extension
  note added under rule 4 of `contracts/admission-privacy-forget.md` in the same commit.
  The remaining half — a privacy-inheritance demonstration on the corrected Step 2 set
  (cab-0019..cab-0023) under this policy — is executed by the Step 2 closure lane and
  graded by the final Step 2 acceptance check.
