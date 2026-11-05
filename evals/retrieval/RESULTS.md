# Phase 2 retrieval — golden-set results

Run: 2026-11-05, **fix round 2 rerun** (after targeted re-review 1 —
7 of 8 blockers FIXED; round 2 closes blocker 6's snippet-JSON
residual, discharges the stock-eval portability extra, and aligns this
file with Tân's settled token gate. See `FIX2_ADDENDUM.md`).
`last_run.json` is the machine-readable record of this exact run —
re-running `run_eval.py` rebuilds the index from live sources, so
numbers drift as sources do. Status: **fix round 2 applied +
measured, awaiting targeted Codex re-review 2 — not DONE.**

## Gate verdict (plan §8, Phase 2)

| Gate | Required | Measured | Verdict |
|---|---|---|---|
| Correctness on golden set | ≥ 95% | **31/32 = 96.9%** (snippet mode) | PASS |
| Tokens (amended gate, settled — see below) | aggregate win + per-question win; MICRO class excepted | aggregate **2,117,771 → 10,236 (−99.5%)**; **22/22** questions with old-path ≥ 500 tokens win; the 6 losses are all MICRO (old-path < 500) | **PASS under the settled amended gate** |
| STALE / WAL gate | works | Package tests `test_stale_gate_flags_exactly_the_modified_source` + `test_spine_wal_only_change_trips_stale_gate` PASS (suite 36/36) | PASS |
| Full test suite | green | 36/36 OK | PASS |

**The token gate — settled wording (Tân, 2026-11-05).** Two rulings
govern this section, both recorded in `docs/decisions/`:

1. **Labels are retained** (10:25 PT, option 1 —
   `DECISION_2026-11-05_TOKEN_GATE_AMENDMENT.md`): the lifecycle /
   admission / privacy / namespace labels that fix round 1 made
   mandatory (Codex blockers 1 + 5) stay in every payload. That
   question is closed; it is not a tension awaiting anyone's weighing.
2. **The exception criterion is the MICRO class** (10:45 PT, option 1,
   rev2 — `DECISION_2026-11-05_TOKEN_GATE_AMENDMENT_2.md`): the
   exception class is questions whose **old-path cost is < 500
   tokens** — below that, reading the source directly is structurally
   cheaper than any retrieval envelope. Contract labels are retained;
   exceptions are named per question here; **at old-path ≥ 500 tokens
   the per-question win is mandatory, no exceptions.**

Rev2 replaced the 10:25 ruling's original criterion (source smaller
than the label envelope) because re-review 1's measurements refuted
that premise: the complete labelled envelope serializes to 106 tokens
— smaller than the 118-token source it was blamed on — and with all
four labels removed, 4 of the 6 losing questions still lose
(122/127/130/129 > 118). The labels do contribute (≈ +17 tokens per
result; the re-review's ablation shows they alone flip Q16 and Q21),
but they are not the mechanism the criterion now rests on.

**Named MICRO exceptions, this run** (win not required; labels
retained): Q16 (old 425, margin −20) · Q21 (old 118, −9) · Q22
(old 118, −22) · Q23 (old 118, −27) · Q24 (old 118, −31) · Q27
(old 118, −29). In the mandatory zone, all 22 questions with
old-path ≥ 500 tokens win (smallest margin +129 at 527 tokens).

Note: `last_run.json`'s summary still carries the runner's literal
pre-amendment flag (`new_wins_every_question`, i.e. raw 32/32), which
therefore reads false; the gate as settled by Tân is the one assessed
in the table above.

Diagnostic: whole-record (`--full`) correctness is 32/32 — retrieval
finds the right record for every question; the single snippet-mode
miss below is a snippet-window selection issue, not a retrieval miss.

## Headline numbers

- Questions: 32 (pilot's 10 extended; all five source kinds + cross-kind;
  3 freshness probes whose gold entered/changed in its source on
  2026-11-05 — Q13, Q17, Q18 — all pass, so a stale index would fail them).
- Total answer-context tokens: old **2,117,771** → new **10,236**
  (−99.5%). Trust the per-question ratios, not the absolutes (declared
  estimator `ceil(chars/4)`, identical on both paths). Totals drift
  between runs because the live sources grow (the claim register and
  spine gained records between the fix-round runs).
- Latency: mean **0.208 s**, max **0.265 s** per query (includes the
  per-query freshness re-fingerprint of all 89 sources).
- Index: **634 records (claim 288 · goal 124 · status 116 · task 63 ·
  memory 43 — sums to 634)**, 89 sources, 0 orphans dropped, built in
  ~3.6 s.

## Method (same as the pilot, SPEC_V1 §6.2)

- Correct = the gold string (quoted verbatim from the live source named
  in `questions.json`) appears in the union of returned snippets.
- Old path = whole `old_files` read into context; for the spine `.db`,
  the text dump of the `tasks` table (the no-index scan cost of finding
  one task among all rows — stated here so the comparison is auditable).
- Runner portability (fix rounds 1–2): `old_files` paths recorded on
  the authoring machine are re-rooted at the current machine's home;
  `--source-root DIR` additionally maps the canonical workspace root
  onto a local mirror. A question whose baseline resolves nowhere on
  the machine is reported **UNRESOLVED-SOURCE** — excluded from token
  win/loss accounting and from the token totals, and named in
  `last_run.json` (`summary.unresolved_questions`) — never a crash, so
  the stock runner completes on a mirrored or partial workspace. On
  this VM run: **32 resolved, 0 unresolved.**
- Per-question `limit` in `questions.json` is the Knowledge Room budget
  for that question, sized to the source (1 for single-record files).

## Per-question results

| Q | kind | correct | old tok | new tok | margin | latency s |
|---|---|---|---|---|---|---|
| Q01 | claim | ✓ | 38,712 | 335 | +38,377 | 0.265 |
| Q02 | claim | ✓ | 38,712 | 270 | +38,442 | 0.224 |
| Q03 | claim | ✓ | 38,712 | 619 | +38,093 | 0.205 |
| Q04 | claim | ✓ | 38,712 | 296 | +38,416 | 0.202 |
| Q05 | claim | ✓ | 38,712 | 287 | +38,425 | 0.202 |
| Q06 | claim | ✓ | 38,712 | 409 | +38,303 | 0.203 |
| Q07 | task | ✓ | 577,013 | 219 | +576,794 | 0.192 |
| Q08 | task | ✓ | 577,013 | 219 | +576,794 | 0.191 |
| Q09 | task | ✓ | 577,013 | 220 | +576,793 | 0.193 |
| Q10 | status | ✓ | 527 | 381 | +146 | 0.198 |
| Q11 | status | ✓ | 527 | 398 | +129 | 0.201 |
| Q12 | status | ✓ | 3,108 | 513 | +2,595 | 0.201 |
| Q13 | status ·fresh | ✓ | 3,108 | 650 | +2,458 | 0.202 |
| Q14 | status | ✓ | 320 | 273 | +47 | 0.204 |
| Q15 | status | ✓ | 425 | 286 | +139 | 0.207 |
| Q16 | status | ✓ | 425 | 445 | −20 | 0.223 |
| Q17 | memory ·fresh | ✓ | 4,049 | 321 | +3,728 | 0.207 |
| Q18 | memory ·fresh | ✓ | 4,049 | 314 | +3,735 | 0.230 |
| Q19 | memory | ✓ | 4,049 | 497 | +3,552 | 0.224 |
| Q20 | memory | ✓ | 4,049 | 234 | +3,815 | 0.197 |
| Q21 | goal | ✗ | 118 | 127 | −9 | 0.200 |
| Q22 | goal | ✓ | 118 | 140 | −22 | 0.205 |
| Q23 | goal | ✓ | 118 | 145 | −27 | 0.212 |
| Q24 | goal | ✓ | 118 | 149 | −31 | 0.200 |
| Q25 | goal | ✓ | 317 | 169 | +148 | 0.201 |
| Q26 | goal | ✓ | 317 | 168 | +149 | 0.201 |
| Q27 | goal | ✓ | 118 | 147 | −29 | 0.199 |
| Q28 | cross | ✓ | 42,761 | 364 | +42,397 | 0.222 |
| Q29 | cross | ✓ | 39,029 | 328 | +38,701 | 0.219 |
| Q30 | cross | ✓ | 38,712 | 597 | +38,115 | 0.226 |
| Q31 | cross | ✓ | 4,049 | 431 | +3,618 | 0.217 |
| Q32 | memory | ✓ | 4,049 | 285 | +3,764 | 0.198 |

## The one miss — Q21, stated plainly

Q21 asks for the Olympus kit's 45mm lens spec (`45mm f/1.8`, in the
goal workspace's GOAL.md). The right record ranks first and its full
text contains the gold (full-mode ✓), but the snippet assembly spends
its proportional cap (byte-based: the file is 521 bytes) on the title +
slug units, whose windows repeat more query terms, and the description
unit's window no longer fits. Mechanism understood; a coverage-first
window-selection change is the candidate fix, left for the review to
judge rather than tuned against a single question here. Q21 is also
one of the named MICRO token exceptions above (old-path 118 tokens).

## What the golden set caught during the build (kept as evidence)

- A findall-based sentence splitter silently DROPPED text segments
  whose punctuation failed its lookahead (gold sentences vanished from
  units while remaining in records — full-mode ✓, snippet ✗). Replaced
  with a lossless slicing splitter; Q03/Q25 recovered.
- Corpus-IDF snippet weights + lead-in windows + 60%-primary
  multi-passage assembly measured WORSE as a bundle (24/32) and were
  reverted; the shipped configuration (record-local unit-DF weights,
  digit bonus, proportional cap, coverage-factored BM25) is the best
  measured: 31/32.
- One golden question (the pilot's Q10 eBay item number, and the
  Facebook listing IDs) is **not answerable from files at all**: those
  facts live only in the Muse tracked-item store, not in any file.
  The question was retargeted to `GOAL.md` facts and the limitation is
  documented in `packages/retrieval/README.md` (F4 section) — closing
  it needs a tracked-item export adapter, future phase work.
- Fix round 1: the six token losses appeared when the contract labels
  became mandatory. Re-review 1's ablation later separated the causes:
  the labels alone flip two of the six (Q16, Q21); the other four
  exceed their 118-token source even with the labels removed — the
  structural micro-source cost that Tân's rev2 MICRO criterion now
  encodes.
- Fix round 2: re-review 1 found blocker 6's tombstone complete in
  text and `--full` JSON but missing its forget fields in the DEFAULT
  snippet JSON — representation completeness is now pinned per mode by
  `test_blocker6_forget_tombstone_snippet_json`. The same review's
  stock eval died at Q10 on a foreign path; the runner now completes
  on partial workspaces with UNRESOLVED-SOURCE accounting
  (`test_source_root_maps_canonical_workspace_path`,
  `test_unresolved_source_named_not_raised`).

## Reproduce

```
cd ~/workspace/pai-repo
python3 packages/retrieval/retrieval_index.py   # or let the runner build
python3 evals/retrieval/run_eval.py             # writes last_run.json
python3 evals/retrieval/run_eval.py --source-root <mirror-workspace>   # off-VM mirror
python3 -m unittest discover -s packages/retrieval/tests   # 36 tests
```
