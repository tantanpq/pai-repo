# Contract — Context Package

Purpose: one shape for bounded context packages handed to executors and
models, with public budgets and honest token accounting, so context is
compiled — never hydrated wholesale.

## Rules

1. A context package has three parts: a header (package ID, created-at,
   purpose/query, and a source manifest listing every included record as
   (system, ID) + anchor + content_hash), body sections, and a footer
   (usage accounting + continuation cursor, rule 5).
2. Every section declares its budget (character limit and/or token budget)
   next to the content, and the budget is counted BEFORE the package is
   loaded or sent (plan §3 rule 6). The always-loaded layer carries its
   ceiling on its face.
3. Oversize content is bounded-read: the package carries a truncated segment
   with an explicit truncation marker and a continuation cursor — content is
   never silently dropped.
4. Token accounting keeps two separate fields and never sums them together:
   `reported_tokens` (provider-reported usage) and `estimated_tokens`
   (local estimate, with the estimator named, e.g. char/4 or bytes). A
   number without a named source is not accounting.
5. A continuation cursor is opaque and bound to the source revision
   (content_hash set) it was issued against. Resuming with a cursor whose
   source revision has changed MUST fail loudly as STALE rather than return
   shifted content.
6. Packages are retrieval-only by default: they carry records plus citations
   (anchors), not generated prose. Summaries, when present, are separate
   derived records under the identity + lifecycle contracts.
7. Freshness is gated: a package records the freshness check result per
   source (fresh / stale with the changed source named). A package MUST NOT
   present stale content as current.

## Non-goals

- No ranking or vector policy here (that is the retrieval package's phase).
- No provider-specific wire formats; adapters translate this shape.
- No prompt-engineering guidance; this contract governs shape and budgets,
  not wording.
