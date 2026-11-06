# Context Package contract — reconciliation note (2026-11-06)

Scope: `contracts/context-package.md` was reconciled against the
as-built Phase 4 code in `packages/context/` (`pack.py`, `ledger.py`,
`rollup.py`, `shadow.py`, `gate.py`, `components.py`) and
`~/workspace/pai-repo-program/phase4/PHASE4_BUILD_CLOSURE_2026-11-06.md`
("closure" below). Every change is doc lag only: code + closure agree,
and the old contract text was generic, silent, or looser than what was
actually built and reviewed. No `.py` file was changed. No locked
ruling, gate semantic, or privacy default was edited (see
"Not changed — out of scope" at the end).

Method: the original sentences of rules 1–7 and all three Non-goals
are preserved verbatim. Each change is an appended "As-built"
paragraph under an existing rule, or a new rule (8–9) for a subsystem
the old contract did not mention at all.

## Changes, with sources

### R1 — Rule 1, new as-built paragraph: versioned pack shape + hash publication

- Pack versioning: stable `pack_id`; any manifest change mints
  `version + 1` and supersedes the previous version.
  Source: `pack.py` `PackAssembler.assemble()`; closure, Slice 2.
- Packs are keyed by (domain, task-type); storage is an append-only
  JSONL room manifest (`manifest.jsonl`) with a hash chain and a
  head-commitment sidecar — the only file the pack layer writes.
  Source: `pack.py` module docstring + `assemble()` /
  `_write_manifest_head_sidecar()`; closure, Slice 2 ("room manifest
  carries a ledger-parity head commitment sidecar").
- Serve-result envelope fields beyond header/sections/footer
  (`version`, `served_at`, `consumer`, `snapshot_mode`,
  `derived_level`, `freshness`, `tombstones`, `exclusions`,
  `status` / `entitlement_result`).
  Source: `pack.py` `serve()` return construction.
- Serve output publishes a member's `content_hash` ONLY for members
  served in that response; the internal room manifest keeps every
  hash. (The old rule-1 wording, read alone, implied every included
  record's hash is listed in the package — the build deliberately
  redacts unserved hashes.)
  Source: `pack.py` `_public_sources()` / `_public_freshness()`
  (Fix-1 #2); closure, Slice 2 ("serve outputs publish content
  hashes only for members served in that response").

### R2 — Rule 2, new as-built paragraph: when and how budgets are counted

- Budgets are counted at assembly time; each section plan records
  `char_budget` / `token_budget`, counted chars/bytes/tokens, and the
  truncated flag. Defaults 4000 chars / 1000 tokens; effective limit
  `min(char_budget, token_budget × 4)`.
  Source: `pack.py` `assemble()` + `_effective_limit()` +
  `DEFAULT_CHAR_BUDGET` / `DEFAULT_TOKEN_BUDGET`; closure, Slice 2
  ("budgets are counted before assembly completes" / contract rule 2
  as implemented).
- Component adapters count before invocation and post-check output;
  over-budget raises `AdapterBudgetError`, never silent truncation.
  Source: `components.py` module docstring (a)–(c); closure, Slice 3.
- Resident packet units are BYTES, never called tokens.
  Source: closure, Slice 3; `components.py` Resident adapter
  (`PREFERRED_CEILING_BYTES` / `HARD_CEILING_BYTES`).

### R3 — Rule 3, new as-built paragraph: the marker, inside the budget

- Marker literal `\n[TRUNCATED: continuation cursor in footer]`,
  counted inside the budget; effective limit < 44 fails loudly with
  `PackBudgetError`; a resume must strictly advance.
  Source: `pack.py` `TRUNCATION_MARKER` + `_bounded_segment()`
  (Fix-1 #3) + `resume()` non-advancing-cursor refusal; closure,
  Slice 2 ("truncation markers count inside budget (budget < 44 ⇒
  PackBudgetError at assembly, resume must strictly advance)").

### R4 — Rule 4, new as-built paragraph: field shapes (invariant untouched)

The never-sum sentence of rule 4 is unchanged. Added only the shapes
the build validates:

- `reported_tokens = {provider, input, output, cached_input?}`;
  `estimated_tokens = {value, estimator}`; a ledger event is metered
  OR estimated, never both; combined token fields are rejected.
  Source: `ledger.py` `_reported_reasons()` / `_estimated_reasons()` /
  `validate_event()`; closure, "Hard invariants held throughout".
- `context_tokens_served` as a third, separate counted field, always
  with a named `token_counter` (`char/4` at the pack layer).
  Source: `ledger.py` `validate_event()` token-accounting block;
  `pack.py` `_footer()` / `TOKEN_ESTIMATOR`.
- Pack footer: `reported_tokens` is explicitly `null` at the pack
  layer beside the estimated figure.
  Source: `pack.py` `_footer()`.

### R5 — Rule 5, new as-built paragraph: exact cursor binding + refusal surface

The STALE invariant sentence of rule 5 is unchanged. Added:

- A cursor is honoured only for the exact (pack_id, version,
  source-hash-set) and only while that version is live; a superseded
  version fails STALE on resume even with an unchanged hash set.
  Source: `pack.py` `resume()` (Fix-1 #1 + coordinator ruling);
  closure, Slice 2 ("cursors honour only the exact (pack_id, version,
  source-hash-set) while live — superseded ⇒ STALE, retired ⇒
  refused (coordinator ruling from dossier §1.3)").
- Deliberate serve/resume asymmetry: `serve()` returns a denied dict
  for a retired pack; `resume()` raises `RetiredPackError` /
  `StaleCursorError`.
  Source: `pack.py` `serve()` and `resume()` docstrings ("deliberate
  asymmetry … adjudicated in the Slice 2 delta re-review"); closure,
  Slice 2 review chain.

### R6 — Rule 6, new as-built paragraph: serve-time §6 rights

Rule 6's retrieval-only sentence is unchanged. Added the serve-time
rights behaviour the pack layer actually implements, inherited from
the cabinet read API:

- Derived level = strictest member level, computed at serve time from
  fresh resolutions, never stamped at assembly; an `unknown` member
  denies the whole serve with the exclusion named; above-entitlement
  members are served around with a named exclusion report.
  Source: `pack.py` module docstring + `_serve_time_state()` /
  `serve()`; closure, Slice 2.
- HOME registry-only members (`home-runloop`, `claim-service`) are
  served as POINTER sections (structure + level, no body).
  Source: `pack.py` `POINTER_SYSTEMS` + `serve()`; read API spec
  §5.1 as cited in `pack.py`.
- Forgotten members appear only as tombstones (the §6 closed set);
  all-forgotten ⇒ tombstone-only posture, never `served_full`.
  Source: `pack.py` `serve()` (Fix-1 #6); closure, Slice 2
  ("all-forgotten ⇒ tombstone posture, never `served_full`").
- Fresh ReadAPI per serve by default; a live instance requires
  `snapshot_ok=True` and outputs carry `snapshot_mode`.
  Source: `pack.py` module docstring F-4 + `__init__()`; closure,
  Slice 2 ("factory wiring default (fresh ReadAPI per serve …)").

### R7 — Rule 7, new as-built paragraph: FRESH/STALE as implemented

The must-not-present-stale invariant of rule 7 is unchanged. Added:

- Per-source status is `FRESH` / `STALE` in serve output, computed by
  per-record content_hash comparison (assembly hash vs current hash).
  Source: `pack.py` `_serve_time_state()`; closure, Slice 2.
- A stale section is excluded and named, not served.
  Source: `pack.py` `serve()` stale branch
  ("STALE: source changed since assembly").

### R8 — New rule 8: the usage ledger (old contract was silent)

The old contract governed only the package footer; the built system
accounts in a separate ledger the contract never described.

- Append-only JSONL stream per host; `prev_hash` chain;
  head-commitment sidecar `<stream>.head.json`; a sidecar-less stream
  folds but is named `tail_uncommitted`.
  Source: `ledger.py` module docstring (F1); `rollup.py` module
  docstring; closure, Slice 1.
- Corrections are new events with
  `corrects: {target_event_id, set}`; `set` replaces only
  `reported_tokens` / `estimated_tokens` / `context_tokens_served`,
  never-both judged on the corrected result; corrections never target
  corrections.
  Source: `ledger.py` module docstring + `_corrects_reasons()`;
  `rollup.py` (R2); closure, Slice 1.
- `corrects.kind` ∈ {`error_fix`, `late_accounting`}, absent =
  `error_fix`, discriminator only.
  Source: `ledger.py` `CORRECTION_KINDS`; closure, Slice 4
  ("Cross-slice attribution").
- Duplicate `event_id`s excluded and named, first counts; rollup is
  deterministic / byte-identical for the same ordered streams, with
  reported and estimated strata separate in every view.
  Source: `rollup.py` module docstring (F2, F7, R3); closure, Slice 1
  (F2/F3 fixes) + Slice 4 (emitted stream folds clean through rollup).

### R9 — New rule 9: shadow mode (old contract was silent)

- Shadow serves a pack and accounts it, but never hands the pack to
  the lane; a missing pack or a denied serve produces a first-class
  `fallback` event carrying the requested key.
  Source: `shadow.py` module docstring; closure, Slice 4.
- Join key is the codex-cp `job_key`, not the receipt `brief_id`
  field; the receipt field is kept as provenance
  (`receipt_brief_id`).
  Source: `shadow.py` module docstring ("Join key"); closure,
  Slice 4 ("Join key = `job_key` … 240 distinct job_key vs 174
  distinct receipt brief_id").
- Serve/fallback events are written without reported tokens and with
  no `estimated_tokens`; late accounting is a correction event with
  `corrects.kind: late_accounting`; the raw serve row is unchanged.
  Source: `shadow.py` module docstring (accounting discipline);
  closure, Slice 4.
- `emit_run` returns an accounting summary ONLY — no serve bodies in
  the returned structure.
  Source: `shadow.py` `emit_run()` (Slice 4 fix F3, test-pinned);
  closure, Slice 4.

## Not changed — invariants the build held (left untouched)

- Rule 4, first paragraph: reported vs estimated tokens are kept in
  two separate fields and never summed; a number without a named
  source is not accounting.
- Rule 5, first paragraph: a cursor resumed against a changed source
  revision MUST fail loudly as STALE.
- Rule 6, first paragraph + rule 9 above: packages are retrieval-only;
  shadow emits a summary only, never serve bodies.
- Serve-time §6 rights as an invariant set (explicit field wins,
  unknown = no entitlement, fail-closed, tombstone-only forget
  surface): the contract's additions in R6 describe the as-built
  enforcement; no privacy default or entitlement rule was altered.
- All three Non-goals, verbatim.

## Not changed — out of scope (decision-like, NOT doc lag)

These were found during reconciliation and deliberately NOT edited
into the contract. They are locked or pending decisions, not lag:

1. **G2-partial gate semantics** — an `adjustment_partial` G2 result
   is `partial`, NOT pass-eligible. This is a coordinator decision
   awaiting Tân's ratification at the GATE_METHOD freeze (TQ1).
   Source: closure, Slice 5. The contract therefore does not codify
   any G1/G2/G3 status semantics; `gate.py`'s method stays DRAFT.
2. **Gate status precedence and thresholds** —
   `overall_status` precedence (invalid > fail > partial >
   not_computable > pass), the `not_computable` tier, G1 coverage
   0.90, G3 harm bound / micro-class / >20%-partial thresholds, and
   the Slice 5 class-taxonomy partition. All belong to the unfrozen
   GATE_METHOD draft and the 2026-11-14 review, not to this contract.
   Source: `gate.py` header + thresholds; closure, Slice 5 + "What
   remains".
3. **Privacy defaults themselves** (which namespaces default to
   `house`, explicit-wins, unknown = no entitlement) — locked in
   `contracts/admission-privacy-forget.md` rule 4 and its decision
   records; this reconciliation only describes how `pack.py`
   enforces them at serve time.
4. **Baseline freeze, library-as-default, TokenEconomizer
   keep-or-drop, and the gate week itself** — explicitly listed in
   the closure as NOT part of the Phase 4 build; no contract text
   was written for them.
