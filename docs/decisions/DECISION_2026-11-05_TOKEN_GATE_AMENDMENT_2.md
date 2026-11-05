# DECISION 2026-11-05 (revision 2) — Phase 2 token gate: exception criterion corrected

- **Decided by:** Tân, main chat, 2026-11-05 10:45 PT — replied "1" to Leona's numbered options (protocol 1-2-3).
- **Supersedes in part:** `DECISION_2026-11-05_TOKEN_GATE_AMENDMENT.md` (10:25 PT ruling). The labels-retained
  principle of that ruling stands unchanged; only the exception CRITERION is replaced, because Codex's
  measurements in `CODEX_REREVIEW_PHASE2_FIX1_2026-11-05.md` refuted its premise:
  - the full labelled envelope serializes to 106 tokens — smaller than the 118-token source it was blamed on;
  - with all four labels removed, 4 of the 6 losing questions still lose (122/127/130/129 > 118).
  - True mechanism: below a small old-path cost, reading the source directly is structurally cheaper than
    any retrieval envelope. Measured distribution on the 32-question golden set: all 6 losses have old-path
    < 500 tokens (118 x5, 425 x1); every question with old-path >= 527 tokens wins.
- **Options presented:** (1) reword the exception by the measured micro class; (2) Codex's advisory —
  genuinely compact the payload for micro-sources and validate on a held-out set; (3) keep the gate
  verbatim and close Phase 2 with the token section recorded NOT MET on the 6 named questions.
- **Decision:** option 1.
- **Final gate wording (Phase 2):** token win in aggregate AND per question, EXCEPT the micro class —
  questions whose old-path cost is < 500 tokens. In the micro class a win is not required, contract
  labels are retained, and exceptions are named per question in `evals/retrieval/RESULTS.md`.
  At old-path >= 500 tokens the per-question win is mandatory, no exceptions.
- **Effect:** RESULTS.md applies this criterion; targeted re-review 2 judges the token section against it.
