# pai-repo — PAI filing-cabinet repository

Canonical source repo for PAI per the LOCKED plan `FILING_CABINET_PLAN_V1.md`
(Tân locked all 4 decisions, chat 2026-11-05 09:01 PT; decision record:
`docs/decisions/DECISION_2026-11-05_FILING_CABINET_PLAN_LOCK.md`).

One chain: source/owner manifest → typed task+evidence spine → owner-scoped
cabinet rooms → validity/privacy/freshness-gated retrieval → bounded context
packages → host/provider executors → verified results/evidence → invalidate/reindex.

Layout (plan §6):
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

Status: Phase 1 skeleton — implementation lands in its phase.
