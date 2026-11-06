# pai-repo — PAI filing-cabinet repository

Canonical source repo for PAI per the LOCKED plan `FILING_CABINET_PLAN_V1.md`
(Tân locked all 4 decisions, chat 2026-11-05 09:01 PT; decision record:
`docs/decisions/DECISION_2026-11-05_FILING_CABINET_PLAN_LOCK.md`).

## One layered system

PAI is one filing cabinet with layered doors — not separate tools. A
reader enters through exactly one layer at a time, and each layer only
does its own job:

```
sources / owner stores (the truth — files, never this repo's indexes)
  → packages/cabinet    the single READ DOOR over the cabinet
  → packages/retrieval  the QUERY FRONT DOOR over the spine
  → packages/context    lane-side context packs + usage accounting
  → host / provider executors → verified results / evidence
  → invalidate / reindex
```

The original plan chain, unchanged: source/owner manifest → typed
task+evidence spine → owner-scoped cabinet rooms →
validity/privacy/freshness-gated retrieval → bounded context packages →
host/provider executors → verified results/evidence →
invalidate/reindex.

### Layer 1 — `packages/cabinet/` — the single read door

`read_api.py` is the one read-only surface over the filing cabinet:
every cabinet read goes through it (usage: `packages/cabinet/READ_API.md`).
Privacy/forget semantics are the read API's §6 semantics — an explicit
`privacy` field wins, ratified namespace defaults apply otherwise, and
an unknown level fails closed: no read entitlement, the exclusion is
reported, and forgotten members appear only as tombstones.
`registrar.py` is the production Cabinet Registrar append/project tool
behind it. This package is the only read door; callers do not read
cabinet stores directly.

### Layer 2 — `packages/retrieval/` — the query front door

Spine retrieval: `retrieval_index.py` builds the index,
`retrieval_query.py` answers queries through the validity gate in
`validity.py` (state → applicability → freshness → counterevidence →
relevance → budget) before any lexical ranking. The front door returns
small evidence packs — bounded snippets with source path + line anchor
and a freshness gate — instead of whole files, so a question costs a
snippet, not a file (token-frugal by design). Sources are the truth;
retrieval is advisory and every result carries its citation.

### Layer 3 — `packages/context/` — context packs + usage ledger

Phase 4, implemented 2026-11-06. Lane-side context packaging and its
accounting, in five modules:

- `pack.py` — bounded, budgeted context packs assembled from the
  cabinet read API and served under serve-time §6 rights (see
  `contracts/context-package.md`, reconciled 2026-11-06).
- `ledger.py` / `rollup.py` — the unified usage ledger: append-only,
  hash-chained event streams with a head-commitment sidecar, folded by
  a deterministic rollup. Provider-reported and locally estimated
  tokens are kept in separate fields/strata and are never summed.
- `shadow.py` — lane instrumentation + shadow measurement: it observes
  lane runs, serves a pack and accounts the serve in the ledger, but
  never hands the pack to the lane as its context. Slice 4 shadow mode
  went LIVE on MSI on 2026-11-06.
- `gate.py` — gate machinery only (G1/G2/G3 components). The method is
  a DRAFT, not frozen; no gate week has run. The freeze waits for the
  2026-11-14 review.
- `components.py` — component adapters, **LEGACY-WRAPPED** (see below).

### `packages/context/components.py` — LEGACY-WRAPPED adapters

The engines behind these adapters do **not** live in this repo and were
**not** rewritten here. Per the Slice 3 recon verdict
(wrap-not-rewrite), `components.py` only wraps them behind one adapter
interface (budget counted before invocation, output post-checked,
over-budget raises loudly):

- Chief context-economy — the engine lives on **HOME**
  (generation-pinned JS: context capsule, cursor continuity, tool-result
  reducers, typed outward contracts).
- Resident packet compiler — the engine lives on **HOME** (r27); there
  is no MSI deployment.
- home-cp bounded readers — on HOME.
- Retrieval snippet assembly — this repo's own `packages/retrieval/`,
  called in-process.

### `packages/spine/` — skeleton only (stated honestly)

Phase 1 skeleton: this package currently contains **only its
`README.md` — no implementation yet**. Its responsibility (spine
read-model & ingestion, mirroring HOME task/evidence state read-only)
is described there; nothing in the layers above depends on code in
this package today.

## Versioning

One scheme for the three implemented packages: each of
`packages/cabinet/`, `packages/retrieval/` and `packages/context/`
carries a `VERSION` file, and all three read `1.0.0`.

## Layout (plan §6)

- `contracts/` — the five invariant contracts every package obeys.
- `packages/` — spine · cabinet · retrieval · context.
- `adapters/` — per-host deployment manifests + transport (home · msi · muse-vm). No secrets.
- `domains/` — domain stores stay intact behind adapters (tom · scoring · solution-knowledge).
- `docs/asset-register/` — living pointer register of house assets (seed; Phase 0 manifest supersedes/merges).
- `docs/decisions/` — locked decisions with chat citations.
- `evals/retrieval/` — golden question sets + per-round measurements.

House rules baked in: files are the truth, DBs are machines, indexes are
rebuildable catalogues; no LLM on the write/organization path; live DBs, WALs,
credentials and runtime state NEVER enter this repo (see `.gitignore`).

Status: cabinet, retrieval and context are implemented (Phases 2–4);
spine is still a Phase 1 skeleton (README only). Per-package status
lives in each package's own `README.md`.
