# Contract — Context Package

Purpose: one shape for bounded context packages handed to executors and
models, with public budgets and honest token accounting, so context is
compiled — never hydrated wholesale.

> Reconciled 2026-11-06 against the as-built Phase 4 code
> (`packages/context/{pack,ledger,rollup,shadow,gate}.py`) and the
> Phase 4 build closure. Each as-built paragraph names its source in
> `docs/CONTEXT_PACKAGE_RECONCILIATION_2026-11-06.md`. Invariants the
> build held are stated verbatim as before; gate semantics (e.g. the
> G2-partial rule) are NOT codified here — the gate method is a draft
> pending its freeze, not contract text.

## Rules

1. A context package has three parts: a header (package ID, created-at,
   purpose/query, and a source manifest listing every included record as
   (system, ID) + anchor + content_hash), body sections, and a footer
   (usage accounting + continuation cursor, rule 5).

   As-built (Phase 4, `pack.py`): a pack is versioned — `pack_id` is
   stable, any manifest change (source set, a source's content_hash,
   budgets, purpose) mints `version + 1` and supersedes the previous
   version. Packs are keyed by (domain, task-type) and stored as an
   append-only JSONL manifest (`manifest.jsonl`) with a hash chain and
   a head-commitment sidecar in the caller-supplied room directory —
   the only file the pack layer writes. A serve result carries, beside
   header/sections/footer: `version`, `served_at`, `consumer`,
   `snapshot_mode`, the serve-time `derived_level`, per-source
   `freshness`, `tombstones`, `exclusions`, and
   `status` / `entitlement_result`. In serve output (not in the room
   manifest), a member's `content_hash` is published ONLY when that
   member's content is served in that response; excluded, denied,
   pointer-only and forgotten members carry no hash.
2. Every section declares its budget (character limit and/or token budget)
   next to the content, and the budget is counted BEFORE the package is
   loaded or sent (plan §3 rule 6). The always-loaded layer carries its
   ceiling on its face.

   As-built (Phase 4, `pack.py`): budgets are counted at ASSEMBLY time,
   before assembly completes — each section plan records
   `char_budget` / `token_budget` (defaults 4000 chars / 1000 tokens),
   the full counted chars/bytes/tokens, and whether the served segment
   is truncated. The effective segment limit is
   `min(char_budget, token_budget × 4)`. Component adapters
   (`components.py`) count the declared budget before invoking a
   wrapped component and post-check its output: an over-budget output
   raises `AdapterBudgetError` loudly, never a silent truncation.
   Resident packet units are BYTES and are named bytes — their
   ceilings are never called tokens.
3. Oversize content is bounded-read: the package carries a truncated segment
   with an explicit truncation marker and a continuation cursor — content is
   never silently dropped.

   As-built (Phase 4, `pack.py`): the marker is the literal
   `\n[TRUNCATED: continuation cursor in footer]` and it counts INSIDE
   the budget. An effective budget that cannot hold the marker plus at
   least one content char (effective limit < 44) fails loudly with
   `PackBudgetError` at assembly/serve/resume instead of serving over
   budget or minting a cursor that never advances; a resume must
   strictly advance every offset it continues.
4. Token accounting keeps two separate fields and never sums them together:
   `reported_tokens` (provider-reported usage) and `estimated_tokens`
   (local estimate, with the estimator named, e.g. char/4 or bytes). A
   number without a named source is not accounting.

   As-built field shapes (Phase 4, `ledger.py` / `pack.py`):
   `reported_tokens` is `{provider, input, output, cached_input?}`;
   `estimated_tokens` is `{value, estimator}`. A ledger event is
   metered OR estimated, never both, and any combined/summed token
   field is rejected by the ledger's closed schema. A third, separate
   counted field, `context_tokens_served`, carries the counted size of
   what a serve delivered, always with its named `token_counter`
   (`char/4` at the pack layer); it is not a reported or an estimated
   figure and is never summed with either. The pack footer states this
   on its face: `reported_tokens` is explicitly `null` at the pack
   layer (no provider meter exists there) beside the estimated figure.
5. A continuation cursor is opaque and bound to the source revision
   (content_hash set) it was issued against. Resuming with a cursor whose
   source revision has changed MUST fail loudly as STALE rather than return
   shifted content.

   As-built (Phase 4, `pack.py`): a cursor is honoured only for the
   exact (pack_id, version, source-hash-set) it was issued against AND
   only while that version is live. A superseded version fails STALE
   on resume even when its source-hash set is unchanged; hash-set
   drift fails STALE and serves nothing. The refusal surface is
   deliberately asymmetric: `serve()` reports a retired pack as a
   returned denied dict (`denial_reason: pack-retired`, no content)
   and raises no cursor exception, while `resume()` raises
   `RetiredPackError` for a retired pack and `StaleCursorError` for a
   superseded or drifted cursor.
6. Packages are retrieval-only by default: they carry records plus citations
   (anchors), not generated prose. Summaries, when present, are separate
   derived records under the identity + lifecycle contracts.

   As-built serve-time rights (Phase 4, `pack.py`, inheriting the
   cabinet read API's §6 semantics): a pack's derived level is the
   strictest member level, computed AT SERVE TIME from fresh
   resolutions — never stamped into the manifest at assembly. Any
   member whose current level is `unknown` denies the WHOLE serve,
   with the exclusion named. Members merely above the consumer's
   entitlement are served around: entitled sections plus a named
   exclusion report. HOME registry-only members (`home-runloop`,
   `claim-service`) are served as POINTER sections — structure +
   level, no body. Forgotten members appear only as tombstones (the
   §6 closed set: system, ID, forget timestamp, actor); when every
   member is forgotten the serve returns the tombstone-only posture
   and can never report `served_full`. The default wiring constructs
   a fresh ReadAPI per serve; a single live instance is accepted only
   with the explicit opt-in `snapshot_ok=True`, and every serve
   output then carries `snapshot_mode: true` on its face.
7. Freshness is gated: a package records the freshness check result per
   source (fresh / stale with the changed source named). A package MUST NOT
   present stale content as current.

   As-built (Phase 4, `pack.py`): the per-source status in serve
   output is `FRESH` / `STALE`, computed per record by comparing the
   record's current content_hash against the hash recorded at
   assembly (`content_hash_at_assembly` vs `content_hash_current`,
   published only for served members, per rule 1). A stale section is
   excluded and named (`STALE: source changed since assembly`), never
   served as current.
8. Usage ledger (as-built, Phase 4, `ledger.py` / `rollup.py`): serves,
   resumes, assemblies, fallbacks and corrections are accounted in one
   append-only JSONL event stream per host. Every stored line carries
   a `prev_hash` content-hash chain, and the writer maintains a
   head-commitment sidecar (`<stream>.head.json`, atomically replaced
   after every append); a stream with no sidecar still folds in the
   rollup but is named `tail_uncommitted`. Corrections are new events,
   never edits: a structured correction carries
   `corrects: {target_event_id, set}` where `set` may replace only
   `reported_tokens` / `estimated_tokens` / `context_tokens_served`,
   judged never-both on the corrected result, and corrections never
   target corrections. `corrects` may carry an optional `kind` —
   `error_fix` or `late_accounting` (absent means `error_fix`); kind
   is a discriminator for tooling only and does not change how the
   correction is applied. Duplicate `event_id`s are excluded from all
   totals and named; the first occurrence counts. The rollup is a
   derived, rebuildable catalog: folding the same ordered streams
   yields a byte-identical report, with reported and estimated strata
   aggregated separately in every view (gate totals, per-pack,
   per-class, per-brief).
9. Shadow mode (as-built, Phase 4, `shadow.py`): the observer assembles
   and serves a pack for a lane run's (domain, task-type) key and
   accounts the serve in the ledger, but the pack is NEVER handed to
   the lane as its context — the lane's real context path is
   untouched. A key with no pack, or a serve the read API denies,
   produces a first-class `fallback` ledger event carrying the
   requested key. The join key for a finished brief is the codex-cp
   `job_key` (the job/receipt identity); the receipt's own `brief_id`
   field (a Drive source ID) is kept as provenance
   (`receipt_brief_id`), never as the key. A serve/fallback event is
   written without reported tokens and carries no `estimated_tokens`;
   when the receipt lands, late accounting arrives as a `correction`
   event with `corrects.kind: late_accounting` — the raw serve row is
   byte-unchanged. `emit_run` returns an accounting summary ONLY: no
   serve bodies (sections) exist anywhere in the returned structure.

## Non-goals

- No ranking or vector policy here (that is the retrieval package's phase).
- No provider-specific wire formats; adapters translate this shape.
- No prompt-engineering guidance; this contract governs shape and budgets,
  not wording.
