# ERRATUM — Round-7 re-review brief: two probe examples misspecified

- **Date:** 2026-11-06 · **Author:** Leona (author of the round-7 re-review brief)
- **Status:** ADOPTED by Leona under delegated authority (2026-11-05 standing
  instruction: decide inside the approved framework, report for veto).
  Overturn paths at the end of this record.
- **Answers:** `CODEX_REREVIEW_READ_API_FIX7_2026-11-06.md`
  (sha256 `b8cafb89…a03`), item 1 — the round's only FAIL.

## What happened

The round-7 re-review found **no executable write bypass**: the accumulated
77-case inventory was independently rebuilt with 0 mismatches, a separate
117-case matrix also matched, the recursive-normalization invariant was
probed directly, and suite (49/49) and regression passed. Item 1 was graded
FAIL for one reason only: the review brief prescribed a **finding** for two
probe examples, and the scanner returns `[]` for them:

```python
open(*((TARGET, *('wb',)),))
open(*([*(TARGET, 'wb')],))
```

## The runtime fact (executed evidence in the verdict)

Both snippets **raise `TypeError`** at call binding
("expected str, bytes or os.PathLike object, not tuple/list"): a starred
expression *inside* the packed container merely contributes a tuple/list
**value** as the call's single positional argument — it never becomes the
call's second argument, no mode is ever bound, and the target file is left
byte-unchanged (24 B). Neither snippet is an executable write path, so the
scanner's `[]` is **semantically correct**. Codex declined to waive the
brief's literal text on its own authority and named two closures:
(a) make the scanner flag the shapes anyway, or (b) formally correct the
brief. This record takes (b).

## Ruling

1. The prescribed disposition for the two examples above is **corrected**
   to: *not a writable call — no finding required; scanner `[]` is
   correct.* They are removed from the gate's required-finding set.
2. Path (a) is **rejected**: forcing the scanner to flag runtime-invalid
   shapes would corrupt the judge-by-runtime-binding semantics every
   round of this gate has enforced (the same principle that accepts
   provably read-only forms by content), and would set the precedent
   that brief text outranks executed evidence.

## Provenance of the error (owned)

The two examples entered the round-7 review brief as probe-shape
suggestions transcribed with prescribed dispositions, without a prior
runtime check by the brief author. **Lesson, binding on future review
briefs I author:** any prescribed disposition for a probe snippet must be
runtime-verified before issuance, or labelled an open question for the
reviewer instead of a requirement.

## Effect

A confirming re-review (round 8) verifies this correction — executes both
snippets (expect TypeError, no write), confirms the rest of the record
stands (inventory, suite, regression per verdict `b8cafb89…a03`) — and
re-issues the Phase 3 gate ruling.

## Overturn

- **Tân** may overturn this erratum at any time; overturning reinstates
  path (a) as a scanner change request.
- **Codex** (or any reviewer) may refute the runtime claim with an
  executed demonstration of either snippet performing a write; that
  evidence would void the correction automatically.
