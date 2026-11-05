# Spec — Cabinet ID (shared crosswalk key)

Status: DESIGN — Phase 3, prerequisite slice 1 (2026-11-05). Nothing in this
spec is implemented yet: no ID has been minted, nothing has been stamped.
Implementation is a later slice, gated on review of this spec and on the
identity-contract amendment drafted in §7.

Authority: Tân's GO for Phases 3–5 in order (2026-11-05 11:23 PT,
`docs/decisions/DECISION_2026-11-05_PHASES35_GO.md`), under the locked plan
`pai-repo-program/FILING_CABINET_PLAN_V1.md` §8 Phase 3. Evidence base:
`pai-repo-program/phase0/CROSSWALK_HOME_VM.md` — ID-level mapping between the
house systems is 0% in both directions; there is no shared key to discover,
so the key must be minted.

## 1. What a Cabinet ID is — and is not

A Cabinet ID identifies a **work area**: a set of records in different house
systems that concern the same line of work (Phase 0, gap class B: the honest
correspondence between systems is many-to-many at the work-area level, not
1-to-1 at the record level).

A Cabinet ID is a **linkage (grouping) key**, stamped onto records as an
attribute. It is not an identity:

- Every record keeps its native ID, minted by its owning system. Citations
  remain (owning-system, native-ID) pairs, per the identity contract.
- A Cabinet ID never replaces, renames, or re-keys a native ID.
- One record carries **at most one** Cabinet ID. One Cabinet ID normally
  covers many records across two or more systems.
- Object kinds stay distinct inside a work area: an epistemic claim
  (`claim-register:`) and an execution claim (`home-runloop:`) may share a
  Cabinet ID while remaining different kinds with different semantics
  (identity contract rule 7).

## 2. Format

```
cab-NNNN        e.g. cab-0001, cab-0042
```

- Literal lowercase prefix `cab-` + zero-padded decimal sequence, minimum
  4 digits, monotonically increasing, never reused. If the sequence ever
  exceeds 9999 it widens to 5 digits; existing IDs are never re-padded.
- Chosen to be greppable and human-citable (house precedent: `C-NNNN`), and
  collision-free against every existing ID shape: `sp-…` (VM spine),
  `C-NNNN` (claim register — uppercase, case-sensitively distinct),
  `claim_mf_…` / `disp_mf_…` (HOME run loop), `claim_<uuid>` (Claim Service).
- The ID is opaque: it encodes no work-area name, no date, no system, and
  **no content** (identity contract rule 3 — an ID is never derived from the
  object's content; the sequence is assigned at mint time only).

## 3. Minting authority — the Cabinet Registrar

- The single minting authority is the **Cabinet Registrar**: the append-only
  registry kept in this repo at `docs/cabinet-registry/` (machine ledger
  `REGISTRY.jsonl` + human index `INDEX.md`), operated by the PAI Repo
  program under Tân's ownership.
- The Registrar is deliberately **not** a running service (identity contract
  non-goal: "No global ID-minting service in this phase"). Minting is a
  registry append performed by one designated lane at a time
  (single-writer discipline); the sequence is allocated from the registry
  tail, and every append records the previous line's hash so a fork or a
  double-mint is mechanically detectable.
- No other system mints Cabinet IDs. Owning systems keep minting their
  native IDs exactly as today (identity contract rule 1, amended per §7).

## 4. The registry (source of truth for all stamping)

Stamping never happens *inside* a foreign store first. The registry is the
source of truth; every stamp elsewhere is a projection of a registry event.

Event shapes (one JSON object per line, append-only):

```
{"type":"MINT","cabinet_id":"cab-0001","at":"<iso8601>","actor":"<lane/program>",
 "work_area":{"slug":"simlab-paid-test","title":"SimLab Core $49 paid test",
              "domain":"system"},
 "reason":"<why this work area exists>","prev_hash":"<sha256 of previous line>"}

{"type":"LINK","cabinet_id":"cab-0001","at":"<iso8601>","actor":"<lane/program>",
 "member":{"system":"claim-register","id":"C-0071","kind":"epistemic-claim"},
 "evidence":"<path#line anchor or probe reference that proves membership>",
 "prev_hash":"<sha256 of previous line>"}

{"type":"UNLINK","cabinet_id":"cab-0001","at":"<iso8601>","actor":"<lane/program>",
 "member":{"system":"claim-register","id":"C-0071","kind":"epistemic-claim"},
 "reason":"<why the link was wrong>","prev_hash":"<sha256 of previous line>"}
```

- `system` is one of: `vm-spine`, `claim-register`, `home-runloop`,
  `claim-service` (the four namespaces of Phase 0 §2). New systems join by
  spec amendment, not by improvisation.
- `kind` records the member's own object kind (e.g. `planning-task`,
  `epistemic-claim`, `execution-claim`, `dispatch`, `work-unit`) and is
  never rewritten to a common kind — grouping is not merging.
- `domain` uses the plan's controlled tag vocabulary (`domain:` axis,
  plan §5). No free tags.
- Every LINK carries resolvable evidence (identity contract rule 6 applied
  to links: a link without a resolvable anchor is an orphan and MUST NOT be
  recorded).

## 5. Where the ID gets stamped, per namespace

Design only — the write path each owning system would use in the
implementation slice. Until then, membership lives in the registry alone.

### 5.1 VM claim register (`C-NNNN`) — LINK events in the claim ledger

- The register is an append-only event ledger (ADMIT / INVALIDATE).
  Stamping is a **new append-only event type** in the same ledger flow:
  `{"entity":"C-0071","type":"LINK","cabinet_id":"cab-0001", …}` admitted
  through the register's normal inbox path.
- The original ADMIT record is never edited (lifecycle contract rules 3, 5:
  no silent edits; the ledger is the only write path for governed changes).
- Consumers (Phase 2 retrieval) resolve a claim's Cabinet ID by folding its
  LINK events; an INVALIDATE of the claim does not delete its links —
  lifecycle state and linkage are separate axes.

### 5.2 VM spine (`sp-…`) — registry-only; derived projection, never a write

- The spine is a read-model (lifecycle contract rule 6: read-models mirror
  state read-only and MUST NOT originate transitions). The Registrar
  therefore **never writes to spine.db**.
- Spine-task membership is asserted in the registry, keyed by
  (`vm-spine`, `sp-…` task_id), with evidence (title citation of a register
  claim, or the SO-CAI line the task was registered from).
- Any spine-side display of Cabinet IDs is a derived projection rebuilt
  from the registry at ingestion time; if the projection and the registry
  disagree, the registry wins.

### 5.3 HOME run loop (`claim_mf_…` / `work_unit_id`) — registry-only in this phase

- `pai-run-loop.db` is the live execution authority. The Registrar does not
  write to it — no direct DB writes, no schema changes (plan §10: no raw
  merges; decision ①: HOME keeps execution authority).
- Membership is keyed by (`home-runloop`, `work_unit_id`): the work-unit
  slug is the stable, human-meaningful unit of work; per-dispatch leases
  (`claim_mf_…`, `disp_mf_…`) inherit membership transitively through their
  work unit and are not individually stamped.
- Optional later step (separate gated slice, not this spec's
  implementation): the Claim Service — the owning system — could stamp its
  own objects or expose a read projection of registry membership. Per
  identity rule 1's principle (IDs are assigned by the owning system), any
  in-store stamp on HOME is applied **by the Claim Service itself**, on a
  Registrar proposal — never by an outside writer.

### 5.4 HOME Claim Service (`claim_<uuid>`) — registry-only; reconciliation target

- Membership is keyed by (`claim-service`, `claim_<uuid>`) in the registry.
- This namespace is the one Phase 0 found split *inside* the HOME family
  (run-loop `claim_mf_*` vs Claim Service `claim_<uuid>`); reconciling the
  pair is a backfill step of its own, sequenced before any VM↔HOME join
  (see the backfill plan). The two claim UUIDs currently held by the MSI
  Resident against this service are named backfill subjects — their work
  area is not guessed in this spec (the Resident↔service link is degraded;
  see the Phase 3 consumer map).

## 6. Conformance with the Phase 1 identity contract

| Identity rule | Position |
|---|---|
| 1 — one ID, assigned by owning system, never reused/reassigned/content-derived | **Amendment needed** — see §7. Native IDs are untouched, but a stamped linkage key is a second identifier on the same record, which rule 1's "exactly one ID" does not currently admit. |
| 2 — IDs namespaced by owning system; cross-system reference = (system, ID) pair | **Conforms.** Cabinet citations are always the triple (cabinet_id, system, native ID); a bare native ID is never treated as cross-system, and a bare Cabinet ID cites a work area, never a record. |
| 3 — content_hash detects change only; hash is never an ID | **Conforms.** Cabinet IDs are sequential, assigned at mint; registry `prev_hash` is a chain-integrity device, never an identifier. |
| 4 — one execution authority (HOME); mirrors carry the authority's (system, ID) pair and never mint a second identity | **Conforms.** The Cabinet ID is not a task identity and confers no execution authority; HOME's authority is unchanged; the VM spine remains a read-model (§5.2). |
| 5 — attempt/result reference (task ID, ordinal) | **Conforms / unaffected.** Run-loop attempts and results inherit work-area membership through their work unit (§5.3); their native references are unchanged. |
| 6 — fact/record carries a `path#line` provenance anchor; orphans are not admitted | **Conforms, extended to links.** Every LINK event must carry resolvable evidence (§4); an unanchored link MUST NOT be recorded. |
| 7 — epistemic claims and execution claims are different kinds; never merge semantics | **Conforms.** `kind` is recorded per member and never rewritten (§4); a shared Cabinet ID asserts "same work area", never "same kind of claim". |

Lifecycle contract: LINK/UNLINK are append-only registry events with
actor, timestamp, and reason (§4), matching rule 5's event shape; nothing
in this spec edits or deletes an existing record in any store (rules 3, 8).
Admission/privacy/forget contract: registry entries contain no record
content and no secrets — only IDs, kinds, and evidence anchors (§4), so a
Cabinet ID inherits no privacy level of its own; a member's privacy level
stays with the member (rule 4) and a forget on a member leaves its LINK
events as tombstone-grade metadata (IDs + timestamps, no content),
consistent with rule 6(b).

## 7. Draft amendment to the identity contract (NOT applied)

The following text is drafted for review. It is **not** in force and has
not been written into `contracts/identity.md`. If approved, it is inserted
as a new rule 8, and the non-goal "No global ID-minting service in this
phase" gains the footnote marked [*].

> **8. Linkage keys (Cabinet IDs).** A record MAY carry at most one
> Cabinet ID (`cab-NNNN`) in addition to its native ID. A Cabinet ID
> identifies a **work area** — a set of records, in one or more systems,
> that concern the same line of work — and never the record itself.
> A Cabinet ID is not an identity under rules 1–2: citations remain
> (owning-system, native-ID) pairs, optionally annotated with the record's
> Cabinet ID; native IDs are never renamed, re-keyed, or superseded by a
> Cabinet ID. Cabinet IDs are minted only by the Cabinet Registrar (the
> append-only registry in `docs/cabinet-registry/`), are sequential and
> never reused, and are assigned without reference to any record's content.
> Membership changes are append-only registry events (LINK / UNLINK with
> evidence, actor, timestamp, reason). A record's Cabinet ID confers no
> execution authority and merges no semantics: members of one work area
> keep their own kinds, lifecycles, and owners.
>
> [*] The Cabinet Registrar is a registry-keeping function of the PAI Repo
> program, not a runtime ID-minting service; owning systems still mint all
> native IDs.

## 8. What this spec deliberately does not do

- No minting, no stamping, no registry creation — design only (slice 1).
- No changes to any live store, endpoint, or config on HOME/MSI/VM.
- No resolution of ambiguous memberships: where evidence supports two
  work areas (e.g. the M8 / Store overlap flagged in Phase 0), the backfill
  plan flags the pair for a human decision — the Registrar never guesses
  (plan §3 rule 7 pattern).
- No new namespaces, tag axes, or object kinds.
