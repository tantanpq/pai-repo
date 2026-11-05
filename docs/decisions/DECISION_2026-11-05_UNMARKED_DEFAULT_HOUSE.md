# DECISION 2026-11-05 — Unmarked claim-register records default to `house` (gate G1 policy)

- **Decided by:** Tan, main chat, 2026-11-05 13:22 PT — replied "1" to Leona's numbered options
  (protocol 1-2-3): "Mac dinh house, chuan hoa tien le retrieval" (default `house`, ratify the
  retrieval precedent). Leona's recommendation, stated before the options, was option 1.
- **Question (from CODEX_REVIEW_QUALIFICATION_2026-11-05.md finding C1 and
  qualification/FIX1_REPORT.md section C1):** the admission-privacy-forget contract defines the
  privacy levels and the inheritance duty but no default for a record carrying no `privacy`
  field; measured 0 of 266 ADMIT claims in the live claim register carry the field. Spec
  section 6 inheritance therefore had no level to inherit for claim-register members.
- **Decision:** an unmarked claim-register record is **`house`** for all inheritance purposes
  (registry entries, INDEX.md, projections, retrieval). This ratifies as POLICY the default the
  Phase 2 retrieval implementation already applies in code
  (`packages/retrieval/retrieval_index.py`: `privacy = claim.get("privacy") or "house"`,
  namespace `room:decisions`), which was built and reviewed under this contract in Phase 2.
  Scope: the claim-register namespace default only. An explicit `privacy` field on a record
  always wins over this default; the strictest-member rule for combined entries is unchanged;
  other namespaces' defaults are unaffected.
- **Effect on gate G1:** the policy half of G1 is satisfied by this record plus the default
  note added under rule 4 of `contracts/admission-privacy-forget.md` in the same commit. The
  remaining G1 half — the access/readback demonstration on the three surfaces (claim register,
  cabinet registry, projections) — is executed and evidenced by the deployment lane before D3,
  using the access facts already measured in FIX1_REPORT.md section C1 (register dir 2770 /
  files 660 on the single-user VM; pai-repo private, unauthenticated probe 404).
