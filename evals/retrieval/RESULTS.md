# Phase 2 retrieval — golden-set results

Run: 2026-11-05, **fix round 1 rerun** (after the Codex Phase 2 review
FAIL — 8 blockers; see `FIX1_ADDENDUM.md`). `last_run.json` is the
machine-readable record of this exact run — re-running `run_eval.py`
rebuilds the index from live sources, so numbers drift as sources do.
Status: **fix round 1 applied + measured, awaiting targeted Codex
re-review — not DONE.**

## Gate verdict (plan §8, Phase 2)

| Gate | Required | Measured | Verdict |
|---|---|---|---|
| Correctness on golden set | ≥ 95% | **31/32 = 96.9%** (snippet mode) | PASS |
| Tokens: new path beats old path | EVERY question | **26/32 wins** — 6 losses, worst margin **−31** | **NOT MET after fix round 1** (was 32/32 before it; mechanism below, stated plainly) |
| STALE / WAL gate | works | Package tests `test_stale_gate_flags_exactly_the_modified_source` + `test_spine_wal_only_change_trips_stale_gate` PASS (suite 33/33) | PASS |
| Full test suite | green | 33/33 OK | PASS |

**Why the token gate regressed — the honest mechanism.** Fix round 1
made lifecycle / admission / privacy / namespace labels mandatory in
the snippet JSON payload (Codex blockers 1 + 5: an opted-in unadmitted
or private result must never travel unlabelled). Those labels cost
≈ +66 chars ≈ +17 tokens per returned result. Every loss sits where
the ENTIRE old path is a tiny file: five questions read one 472-char
GOAL.md whose whole content costs **118 tokens** — less than any
honestly labelled answer envelope (Q21 −9 · Q22 −22 · Q23 −27 ·
Q24 −31 · Q27 −29) — and Q16's 425-token status file, where several
labelled results together exceed it (−20). The other 26 questions win
by margins from +47 to +574,228. This is a real tension between the
plan's per-question token gate and the contracts' labelling
requirements, surfaced for the re-review / Tân to weigh — the numbers
are reported as measured, not tuned around.

Diagnostic: whole-record (`--full`) correctness is 32/32 — retrieval
finds the right record for every question; the single snippet-mode
miss below is a snippet-window selection issue, not a retrieval miss.

## Headline numbers

- Questions: 32 (pilot's 10 extended; all five source kinds + cross-kind;
  3 freshness probes whose gold entered/changed in its source on
  2026-11-05 — Q13, Q17, Q18 — all pass, so a stale index would fail them).
- Total answer-context tokens: old **2,110,416** → new **10,236**
  (−99.5%). Trust the per-question ratios, not the absolutes (declared
  estimator `ceil(chars/4)`, identical on both paths). Totals drift
  from the pre-fix run (2,098,977 → 8,037) because the live spine grew
  and the snippet payload now carries the mandatory labels.
- Latency: mean **0.213 s**, max **0.254 s** per query (includes the
  per-query freshness re-fingerprint of all 89 sources).
- Index: **630 records (claim 284 · goal 124 · status 116 · task 63 ·
  memory 43 — sums to 630)**, 89 sources, 0 orphans dropped, built in
  ~1.4 s. (This corrects the pre-fix headline, which said 628 while
  its own kind counts summed to 629 — Codex Phase 2 review, extra (b).)

## Method (same as the pilot, SPEC_V1 §6.2)

- Correct = the gold string (quoted verbatim from the live source named
  in `questions.json`) appears in the union of returned snippets.
- Old path = whole `old_files` read into context; for the spine `.db`,
  the text dump of the `tasks` table (the no-index scan cost of finding
  one task among all rows — stated here so the comparison is auditable).
  `old_files` paths are re-rooted at the current machine's home by
  `run_eval.py`, so the stock eval runs off-VM; the `.db` baseline is
  read from a snapshot copy, never opened in place.
- Per-question `limit` in `questions.json` is the Knowledge Room budget
  for that question, sized to the source (1 for single-record files).

## Per-question results

| Q | kind | correct | old tok | new tok | margin | latency s |
|---|---|---|---|---|---|---|
| Q01 | claim | ✓ | 38,712 | 335 | +38,377 | 0.208 |
| Q02 | claim | ✓ | 38,712 | 270 | +38,442 | 0.205 |
| Q03 | claim | ✓ | 38,712 | 619 | +38,093 | 0.204 |
| Q04 | claim | ✓ | 38,712 | 296 | +38,416 | 0.221 |
| Q05 | claim | ✓ | 38,712 | 287 | +38,425 | 0.216 |
| Q06 | claim | ✓ | 38,712 | 409 | +38,303 | 0.218 |
| Q07 | task | ✓ | 574,447 | 219 | +574,228 | 0.201 |
| Q08 | task | ✓ | 574,447 | 219 | +574,228 | 0.198 |
| Q09 | task | ✓ | 574,447 | 220 | +574,227 | 0.196 |
| Q10 | status | ✓ | 527 | 381 | +146 | 0.199 |
| Q11 | status | ✓ | 527 | 398 | +129 | 0.202 |
| Q12 | status | ✓ | 3,108 | 513 | +2,595 | 0.208 |
| Q13 | status ·fresh | ✓ | 3,108 | 650 | +2,458 | 0.219 |
| Q14 | status | ✓ | 320 | 273 | +47 | 0.210 |
| Q15 | status | ✓ | 425 | 286 | +139 | 0.245 |
| Q16 | status | ✓ | 425 | 445 | −20 | 0.200 |
| Q17 | memory ·fresh | ✓ | 4,098 | 321 | +3,777 | 0.193 |
| Q18 | memory ·fresh | ✓ | 4,098 | 314 | +3,784 | 0.229 |
| Q19 | memory | ✓ | 4,098 | 497 | +3,601 | 0.218 |
| Q20 | memory | ✓ | 4,098 | 234 | +3,864 | 0.238 |
| Q21 | goal | ✗ | 118 | 127 | −9 | 0.202 |
| Q22 | goal | ✓ | 118 | 140 | −22 | 0.254 |
| Q23 | goal | ✓ | 118 | 145 | −27 | 0.238 |
| Q24 | goal | ✓ | 118 | 149 | −31 | 0.202 |
| Q25 | goal | ✓ | 317 | 169 | +148 | 0.210 |
| Q26 | goal | ✓ | 317 | 168 | +149 | 0.197 |
| Q27 | goal | ✓ | 118 | 147 | −29 | 0.199 |
| Q28 | cross | ✓ | 42,810 | 364 | +42,446 | 0.220 |
| Q29 | cross | ✓ | 39,029 | 328 | +38,701 | 0.217 |
| Q30 | cross | ✓ | 38,712 | 597 | +38,115 | 0.220 |
| Q31 | cross | ✓ | 4,098 | 431 | +3,667 | 0.221 |
| Q32 | memory | ✓ | 4,098 | 285 | +3,813 | 0.202 |

## The one miss — Q21, stated plainly

Q21 asks for the Olympus kit's 45mm lens spec (`45mm f/1.8`, in the
goal workspace's GOAL.md). The right record ranks first and its full
text contains the gold (full-mode ✓), but the snippet assembly spends
its proportional cap (byte-based: the file is 521 bytes) on the title +
slug units, whose windows repeat more query terms, and the description
unit's window no longer fits. Mechanism understood; a coverage-first
window-selection change is the candidate fix, left for the review to
judge rather than tuned against a single question here. After fix
round 1 this question also loses on tokens (−9): at 118 tokens the
whole file is cheaper than a labelled snippet envelope (see the gate
note above).

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
- Fix round 1 (post-review): the golden set's six token losses are all
  attributable to the mandatory contract labels, itemized in the gate
  note above — recorded here so the regression is evidence, not rumor.

## Reproduce

```
cd ~/workspace/pai-repo
python3 packages/retrieval/retrieval_index.py   # or let the runner build
python3 evals/retrieval/run_eval.py             # writes last_run.json
python3 -m unittest discover -s packages/retrieval/tests   # 33 tests
```
