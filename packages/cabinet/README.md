# packages/cabinet — rooms, consolidation, lifecycle engine

Responsibility: The filing cabinet itself: room registry (a room = real directory + named index set + schema'd tag set), the deterministic consolidator that derives facts from immutable sources, tiered dedup, and the invalidate/lifecycle machinery over cabinet records.

Contract dependencies: contracts/identity.md · contracts/lifecycle.md · contracts/admission-privacy-forget.md

Status: Phase 1 skeleton — implementation lands in its phase.
