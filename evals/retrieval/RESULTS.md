# Phase 2 retrieval — golden-set results

Run: 2026-11-05 (final run of the build session; `last_run.json` is the
machine-readable record of this exact run — re-running `run_eval.py`
rebuilds the index from live sources, so numbers drift as sources do).
Status: **built + measured, awaiting Codex review — not DONE.**

## Gate verdict (plan §8, Phase 2)

| Gate | Required | Measured | Verdict |
|---|---|---|---|
| Correctness on golden set | ≥ 95% | **31/32 = 96.9%** (snippet mode) | PASS |
| Tokens: new path beats old path | EVERY question | **32/32 wins**, worst margin **+3 tokens** | PASS |
| STALE / WAL gate | works | Package tests `test_stale_gate_flags_exactly_the_modified_source` + `test_spine_wal_only_change_trips_stale_gate` PASS (suite 22/22) | PASS |
| Full test suite | green | 22/22 OK | PASS |

Diagnostic: whole-record (`--full`) correctness is 32/32 — retrieval
finds the right record for every question; the single snippet-mode
miss below is a snippet-window selection issue, not a retrieval miss.

## Headline numbers

- Questions: 32 (pilot's 10 extended; all five source kinds + cross-kind;
  3 freshness probes whose gold entered/changed in its source on
  2026-11-05 — Q13, Q17, Q18 — all pass, so a stale index would fail them).
- Total answer-context tokens: old **2,098,977** → new **8,037** (−99.6%).
  Trust the per-question ratios, not the absolutes (declared estimator
  `ceil(chars/4)`, identical on both paths).
- Latency: mean **0.221 s**, max **0.318 s** per query (includes the
  per-query freshness re-fingerprint of all 89 sources).
- Index: 628 records (claim 282 · goal 125 · status 116 · task 63 ·
  memory 43 — counts vary as sources drift; goal count dropped from the
  pilot-era shape because ≤600-char files now index as single records),
  built in ~1.4 s.

## Method (same as the pilot, SPEC_V1 §6.2)

- Correct = the gold string (quoted verbatim from the live source named
  in `questions.json`) appears in the union of returned snippets.
- Old path = whole `old_files` read into context; for the spine `.db`,
  the text dump of the `tasks` table (the no-index scan cost of finding
  one task among all rows — stated here so the comparison is auditable).
- Per-question `limit` in `questions.json` is the Knowledge Room budget
  for that question, sized to the source (1 for single-record files).

## Per-question results

| Q | kind | correct | old tok | new tok | margin | latency s |
|---|---|---|---|---|---|---|
| Q01 | claim | ✓ | 38,712 | 278 | +38,434 | 0.205 |
| Q02 | claim | ✓ | 38,712 | 212 | +38,500 | 0.226 |
| Q03 | claim | ✓ | 38,712 | 561 | +38,151 | 0.317 |
| Q04 | claim | ✓ | 38,712 | 239 | +38,473 | 0.248 |
| Q05 | claim | ✓ | 38,712 | 229 | +38,483 | 0.318 |
| Q06 | claim | ✓ | 38,712 | 352 | +38,360 | 0.215 |
| Q07 | task | ✓ | 570,634 | 180 | +570,454 | 0.199 |
| Q08 | task | ✓ | 570,634 | 180 | +570,454 | 0.226 |
| Q09 | task | ✓ | 570,634 | 180 | +570,454 | 0.280 |
| Q10 | status | ✓ | 527 | 257 | +270 | 0.202 |
| Q11 | status | ✓ | 527 | 274 | +253 | 0.202 |
| Q12 | status | ✓ | 3,108 | 424 | +2,684 | 0.208 |
| Q13 | status ·fresh | ✓ | 3,108 | 561 | +2,547 | 0.201 |
| Q14 | status | ✓ | 320 | 183 | +137 | 0.226 |
| Q15 | status | ✓ | 425 | 198 | +227 | 0.200 |
| Q16 | status | ✓ | 425 | 356 | +69 | 0.211 |
| Q17 | memory ·fresh | ✓ | 4,098 | 229 | +3,869 | 0.195 |
| Q18 | memory ·fresh | ✓ | 4,098 | 217 | +3,881 | 0.192 |
| Q19 | memory | ✓ | 4,098 | 413 | +3,685 | 0.197 |
| Q20 | memory | ✓ | 4,098 | 146 | +3,952 | 0.193 |
| Q21 | goal | ✗ | 118 | 94 | +24 | 0.197 |
| Q22 | goal | ✓ | 118 | 107 | +11 | 0.204 |
| Q23 | goal | ✓ | 118 | 112 | +6 | 0.206 |
| Q24 | goal | ✓ | 118 | 115 | +3 | 0.237 |
| Q25 | goal | ✓ | 317 | 111 | +206 | 0.227 |
| Q26 | goal | ✓ | 317 | 110 | +207 | 0.231 |
| Q27 | goal | ✓ | 118 | 114 | +4 | 0.200 |
| Q28 | cross | ✓ | 42,810 | 291 | +42,519 | 0.218 |
| Q29 | cross | ✓ | 39,029 | 264 | +38,765 | 0.222 |
| Q30 | cross | ✓ | 38,712 | 520 | +38,192 | 0.223 |
| Q31 | cross | ✓ | 4,098 | 330 | +3,768 | 0.237 |
| Q32 | memory | ✓ | 4,098 | 200 | +3,898 | 0.195 |

## The one miss — Q21, stated plainly

Q21 asks for the Olympus kit's 45mm lens spec (`45mm f/1.8`, GOAL.md
line 6). The right record ranks first and its full text contains the
gold (full-mode ✓), but at this file's proportional cap (157 chars —
the file is 472 chars, so a third of it), the snippet assembly spends
the budget on the title + slug units, whose windows repeat more query
terms, and the description unit's cap-sized window no longer fits.
Mechanism understood; a coverage-first window-selection change is the
candidate fix, left for the review to judge rather than tuned against
a single question here. The tightest token margins (Q24 +3, Q27 +4,
Q23 +6) are all on this same 472-char file: any cited answer costs
roughly the file's size, and the new path still wins every one.

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

## Reproduce

```
cd ~/workspace/pai-repo
python3 packages/retrieval/retrieval_index.py   # or let the runner build
python3 evals/retrieval/run_eval.py             # writes last_run.json
python3 -m unittest discover -s packages/retrieval/tests
```
