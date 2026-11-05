# DECISION 2026-11-05 — Phase 2 token gate amendment

- **Decided by:** Tân, main chat, 2026-11-05 10:25 PT — replied "1" to Leona's numbered options (protocol 1-2-3).
- **Context:** Phase 2 fix round 1 (commit `914410e`) implemented the contracts' mandatory output labels
  (blockers 1 + 5 of `CODEX_REVIEW_PHASE2_2026-11-05.md`). Per-question token wins fell 32/32 → 26/32.
  All 6 losses are questions whose entire source file is smaller than the label envelope
  (~+17 tokens/result; worst −31; the Olympus GOAL.md source costs ~118 tokens in total).
  Aggregate unchanged in substance: 2,110,416 → 10,236 est. tokens (−99.5%).
- **Options presented:** (1) amend the gate — aggregate + per-question win, except where mandatory
  contract labels exceed the source size; labels retained, exceptions recorded per question.
  (2) measure payload only, labels outside the gate. (3) keep the gate verbatim and record a deliberate deviation.
- **Decision:** option 1.
- **Amended gate** (FILING_CABINET_PLAN_V1 §8, Pha 2): token win in aggregate AND per question,
  EXCEPT questions whose source file is smaller than the mandatory contract-label envelope —
  those keep their labels and are listed as named exceptions in `evals/retrieval/RESULTS.md`.
- **Effect:** the Codex re-review of fix round 1 judges the token section against this amended gate;
  RESULTS.md must enumerate the exception questions.
