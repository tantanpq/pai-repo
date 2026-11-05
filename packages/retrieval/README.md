# packages/retrieval — gated retrieval & query

Responsibility: The front door: validity · privacy · freshness gates, the deterministic lexical index (heading chunks with `path#line` anchors, content-hash incremental sync, WAL-aware freshness — inheriting the pai-query-layer pilot, Codex PASS 2026-11-05), query, and exact fetch by anchor. Optional rankers sit behind the gates only after benchmark on the golden set in evals/retrieval/.

Contract dependencies: contracts/identity.md · contracts/admission-privacy-forget.md · contracts/context-package.md

Status: Phase 1 skeleton — implementation lands in its phase.
