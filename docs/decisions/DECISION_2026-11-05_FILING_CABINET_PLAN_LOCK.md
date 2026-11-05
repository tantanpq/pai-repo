# DECISION — Filing Cabinet Plan V1 LOCKED (all 4 decisions as proposed)

- **Date:** 2026-11-05
- **Decided by:** Tân, in main chat, 2026-11-05 09:01 PT —
  "Khóa cả 4 quyết — chạy Pha 0–2" (lock all 4 decisions — run Phases 0–2).
- **Plan:** `~/workspace/pai-repo-program/FILING_CABINET_PLAN_V1.md` (§7).

## The 4 locked decisions

1. **Spine authority:** HOME = execution authority; the VM spine is the
   read-model; ID/lifecycle crosswalk comes first. NO cutover to the VM
   until crosswalk evidence proves equivalence.
2. **Repo home:** ONE private Git repo is the canonical source; installs on
   HOME/MSI are deployments, reconciled by commit manifest. (The public
   `pai-cp-free` remains a release artifact, never a home for house
   knowledge.)
3. **Memory Rooms:** standardize the room contract (plan §5) and converge
   HOME's two Rooms deployments onto one engine behind the adapter —
   keeping the HOME implementation as the engine, NOT a file-first rewrite
   from zero.
4. **Execution cadence:** Phases 0–2 execute immediately after this lock;
   Phases 3–5 return with crosswalk evidence for review before proceeding.

## Effect

- Phase 0 (manifest + crosswalk), Phase 1 (this repo skeleton + contracts),
  and Phase 2 (retrieval as the front door) are authorized work.
- Nothing in this lock authorizes moving, merging, or deleting any live
  store; consolidation steps follow the plan's per-phase gates.
