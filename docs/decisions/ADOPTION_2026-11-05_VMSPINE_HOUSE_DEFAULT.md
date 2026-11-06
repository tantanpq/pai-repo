# ADOPTION RECORD 2026-11-05 — Unmarked vm-spine records default to `house` (Phase 3 Step 3 finding F02)

- **Adopted by:** Leona, under delegated operational authority (operational leadership
  delegation, standing since 2026-10-16/17). This is an **adoption record, not an
  owner-signed decision**: it is deliberately written in the adoption form (pattern:
  `ADOPTION_2026-11-05_CAB0013_SPLIT.md`), not in the DECISION form of Tan's two
  rulings it extends.
- **Authority relied on, stated exactly:** (a) the owner's two identical rulings of
  2026-11-05 establishing this default pattern —
  `DECISION_2026-11-05_UNMARKED_DEFAULT_HOUSE.md` (C1, claim-register, 13:22 PT)
  and `DECISION_2026-11-05_HOME_NAMESPACES_HOUSE_DEFAULT.md` (home-runloop +
  home-claim-service, 18:59 PT) — and (b) the owner's instruction of 2026-11-05
  20:09 PT to complete the Phase 3 work fully without further choice rounds.
  This adoption does **not** rest on silence-as-ratification: it rests on the
  recorded delegation plus the owner's own twice-stated rule for the same
  situation, applied to the one namespace his rulings had not yet named.
- **Question (from `pai-repo-program/phase3/CODEX_REVIEW_STEP3_2026-11-05.md`
  finding F02, Ruling 6(a) option (i)):** backfill Step 3 stamped 46 vm-spine
  tasks (47 relations) into the cabinet registry. The ratified defaults covered
  claim-register, home-runloop and home-claim-service only; the vm-spine
  namespace had no default, the spine tasks table carries no privacy column,
  and the segment records provide no source privacy classification — so the
  effective inherited level for vm-spine members could not be established and
  Step 5 check 4 blocked Step 3 closure.
- **Rule adopted:** an unmarked record in the `vm-spine` namespace is
  **`house`** for all §6 inheritance purposes (registry entries, INDEX.md,
  projections, retrieval). Rationale, the same as the owner's two rulings:
  vm-spine records are the house's own planning registrations on the owner's
  own VM — the same trust domain as the claim register, with no external
  party. An explicit `privacy` field on a record always wins over this
  default; the strictest-member rule for combined entries is unchanged;
  namespaces other than claim-register, home-runloop, home-claim-service and
  vm-spine remain unaffected (no default).
- **Effect on C1:** C1's scope sentence is superseded in part by this record —
  the default now covers four named namespaces. C1 and the HOME-namespaces
  decision otherwise stand (their records are not edited; decision history is
  append-only).
- **Effect on Step 3 / F02:** the policy half of F02 is satisfied by this
  record plus the extension note added under rule 4 of
  `contracts/admission-privacy-forget.md` in the same commit. The
  demonstration half — effective levels computed over all 65 active vm-spine
  memberships on the current registry (head `5370e59e…`), with
  INDEX/PROJECTION binding — is executed in
  `pai-repo-program/phase3/STEP3_F02_DEMONSTRATION.md`. Grading of both
  halves belongs to the Codex Step 3 fix re-review; Ruling 6(a)'s interim
  rule (unknown privacy = no established read entitlement for vm-spine)
  remains in force until that review accepts this discharge.
- **Overturn paths (standing):** this adoption is reversed by append-only
  correction if either arrives: (a) an owner decision by Tan recorded in
  `docs/decisions/` (including a decision replacing this adoption with his
  own ruling of either direction); or (b) contrary evidence that a vm-spine
  record carries, or should carry, a stricter level — in which case the
  explicit level wins for that record under the rule above and the affected
  derived entries are recomputed.
