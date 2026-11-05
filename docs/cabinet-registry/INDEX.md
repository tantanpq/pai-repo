# Cabinet Registrar — Index

Human index of the Cabinet Registrar registry (`REGISTRY.jsonl`, the source of
truth; this file is a projection of its accepted fold). Work-area labels live
only on this surface and in projections — never in registry history lines
(spec §6 history rule). A record is always cited by its native
(owning-system, ID) pair; a Cabinet ID names a work area only.

- Accepted head: `24d0b715fa4e61d85aaa4dfa49ae25e56e95267270a1805db3d5789cab4fd716` · 58 registry lines · Step 1 pilot,
  appended 2026-11-05T12:20:55-08:00 by `pai-repo-phase3-impl-step1` against the empty (genesis) head.
- Claim-ledger projection (spec §5.1): not yet admitted — the register's
  admission path is not qualified for LINK/UNLINK events; see the Step 1
  report (`pai-repo-program/phase3/STEP1_REPORT.md`).

## Cabinets

| Cabinet | INDEX label | Members (owning-system: native ID — relation) |
|---|---|---|
| cab-0001 | personal-intelligence-spine | vm-spine: sp-20261102-spine---personal-intelligence-spine---le-881013 — primary<br>claim-register: C-0027 — primary<br>claim-register: C-0177 — primary |
| cab-0002 | user-owned-continuity | vm-spine: sp-20261102-m2-user-owned-continuity--claim-c-0032-348d11 — primary<br>claim-register: C-0032 — primary |
| cab-0003 | verified-capability-lifecycle | vm-spine: sp-20261102-m8-verified-capability-lifecycle---libra-9a6cbe — primary<br>claim-register: C-0033 — primary |
| cab-0004 | commercial-sequence | vm-spine: sp-20261102-commercial-sequence-plan-v2--claim-c-007-d1bbdb — primary<br>claim-register: C-0070 — primary<br>claim-register: C-0082 — primary |
| cab-0005 | simlab-paid-test | vm-spine: sp-20261102-simlab-core--49-paid-test--claims-c-0071-a71ada — primary<br>claim-register: C-0071 — primary<br>claim-register: C-0072 — primary |
| cab-0006 | commercial-decision-3a | vm-spine: sp-20261102-commercial-decision-3a---cheap-paid-test-86c810 — primary<br>claim-register: C-0075 — primary |
| cab-0007 | pai-spine-kit | vm-spine: sp-20261102-pai-spine-kit-phase-a--claim-c-0080--gom-39b3b7 — primary<br>claim-register: C-0080 — primary<br>claim-register: C-0081 — primary |
| cab-0008 | public-task-inbox | vm-spine: sp-20261102-domain-public-task-inbox---watch--5-tool-7e91dc — primary<br>claim-register: C-0103 — primary |
| cab-0009 | scheduler-independence | vm-spine: sp-20261102-scheduler-independence-phase-2---build-s-0b2bf3 — primary<br>claim-register: C-0104 — primary |
| cab-0010 | portable-continuity-r1 | vm-spine: sp-20261102-portable-continuity-r1-promotion---watch-104321 — primary<br>claim-register: C-0107 — primary |
| cab-0011 | moats-completion | vm-spine: sp-20261102-moats-done-basic---no-luc-con-lai-theo-r-78e818 — primary<br>claim-register: C-0122 — primary |
| cab-0012 | negative-space-surplus | vm-spine: sp-20261102-negative-space---surplus-s1-s15-cho-quye-5b417e — primary<br>claim-register: C-0136 — primary<br>claim-register: C-0168 — primary<br>claim-register: C-0169 — primary<br>claim-register: C-0170 — primary |
| cab-0013 | unverified-systems | vm-spine: sp-20261102-unverified-systems-u1-u20---cho-kiem-chu-57ea63 — primary<br>vm-spine: sp-20261102-orphan-briefs---101-brief-chua-co-result-dc93de — primary<br>claim-register: C-0139 — primary<br>claim-register: C-0140 — primary |
| cab-0014 | intent-excavation | vm-spine: sp-20261102-intent-excavation-mechanism--claim-c-017-ebc799 — primary<br>claim-register: C-0174 — primary |
| cab-0015 | claim-register-automation | vm-spine: sp-20261102-claim-register---slice-2-tu-dong-hoa--cl-2be477 — primary<br>claim-register: C-0175 — primary |
| cab-0016 | drive-parked-archive | vm-spine: sp-20261102-drive-parked-archive---parked-by-design--f16b25 — primary<br>claim-register: C-0192 — primary<br>claim-register: C-0194 — primary |

## Pending exhibits (not stamped — no Cabinet ID)

- **M8 ↔ Store / Domain / Library pair relation** — PENDING a human decision.
  Members concerned: vm-spine: sp-20261102-m8-verified-capability-lifecycle---libra-9a6cbe (primary member of cab-0003 via its
  C-0033 citation — that membership proceeds) and vm-spine: sp-20261102-domain--store---domain---library--design-27b44f
  (not a Step 1 member). Evidence: the M8 task's spine title records a
  "suspected overlap" with the Store / Domain / Library task (title segment in
  `pai-repo-program/phase3/step1-evidence/SPINE_SEGMENTS.json`); Phase 0
  crosswalk appendix rows 49 and 43; backfill plan Step 1 ambiguity flag.
  Suspicion is not evidence: no LINK, no secondary relation, and no merge is
  recorded for this pair until a human decides on evidence.

## Coverage (Step 1)

- Cabinets minted: 16 (cab-0001…cab-0016).
- Primary memberships: 42 — 17 vm-spine planning tasks + 25 claim-register
  epistemic claims. Secondary memberships: 0.
- Pending exhibits: 1 pair relation (above). Step 1 orphans: none — every
  Step 1 task and claim in the plan table carries a primary Cabinet ID.

