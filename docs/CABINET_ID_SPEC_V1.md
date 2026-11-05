# Spec — Cabinet ID (shared crosswalk key)

Status: DESIGN — Phase 3, prerequisite slice 1 (2026-11-05). Nothing in this
spec is implemented yet: no ID has been minted, nothing has been stamped.
Implementation is a later slice, gated on review of this spec and on
Tân's ratification of the identity-contract clarification drafted in §7.

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
- Membership is typed **primary / secondary / pending** (the 1-per-record
  assumption of the first draft did not survive review — some records
  genuinely span lines of work: the Phase 0 appendix's SimLab spine task
  joins a push window *and* a CMM pilot milestone in one registration,
  and claim C-0139 is cited by both the unverified-systems and the
  orphan-briefs tasks). The policy:
  - **Primary:** a record carries **at most one primary** Cabinet ID. The
    primary is the work area its evidence anchors it to.
  - **Secondary:** a record whose evidence genuinely spans further work
    areas MAY carry secondary Cabinet references. A secondary reference
    is a typed, non-identity grouping relation asserting only "also
    concerns this work area" — it is not a second membership of the
    primary kind, confers nothing, and is recorded as its own registry
    event (§4), never as a silent extra stamp.
  - **Pending:** a record whose primary area cannot be decided on
    evidence stays **pending** — recorded as a pending exhibit in the
    registry index, NOT stamped. A pending exhibit is not an admitted
    LINK and carries no Cabinet ID.
  - Records are never split, never force-merged to satisfy the primary
    cap, and never assigned a primary by default or by order of
    encounter. Coverage is reported at the policy's actual level:
    primary coverage and secondary coverage are counted separately
    (backfill plan, Step 5).
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
  object's content; the sequence is assigned at mint time only). The same
  opacity binds grouping values throughout registry history: `cab-NNNN`
  is the only grouping value a history line carries — no descriptive
  work-area label appears there (§6 history rule).

## 3. Minting authority — the Cabinet Registrar

- The single minting authority is the **Cabinet Registrar**: the append-only
  registry kept in this repo at `docs/cabinet-registry/` (machine ledger
  `REGISTRY.jsonl` + human index `INDEX.md`), operated by the PAI Repo
  program under Tân's ownership.
- The Registrar is deliberately **not** a running service. It is,
  honestly, a **central allocator of grouping keys** for the Cabinet
  namespace — a registry-keeping function, not a runtime minting service;
  owning systems still mint all native IDs. The identity contract's
  non-goal ("No global ID-minting service in this phase") is addressed by
  the draft clarification in §7, which names this exception instead of
  claiming an exemption by wordplay.
- Minting is a registry append performed by one designated lane at a time
  (single-writer discipline). Discipline alone is **not** exclusion, so
  acceptance is mechanical, not social (fix-round response to review
  finding F02):
  - There is exactly **one authoritative accepted history**: the registry
    as accepted on this repo's accepted branch. Proposals on any other
    branch or in any staging copy are unaccepted until merged there.
  - The next Cabinet sequence is allocated from the **greatest MINT
    sequence in the accepted history** — never from the registry tail
    event (the tail may be a LINK to an older Cabinet).
  - An append is accepted only against the **expected accepted head**:
    the writer states the head hash it built on; if the accepted head
    has moved, the append is stale and is **rejected**, not merged.
  - Before acceptance, the complete candidate fold is **validated**:
    event schemas (§4), unique and monotonically increasing MINT
    sequences, no duplicate Cabinet ID, every referenced Cabinet exists,
    allowed system/kind values, and at most one active primary
    membership per member after folding. Any violation rejects the
    append.
  - **No projection is built from an unaccepted proposal.** A losing
    proposal stays unaccepted and, if resubmitted, receives a fresh
    sequence allocation against the then-current head.
  - If a conflict nevertheless escapes into accepted or projected state:
    stamping **stops**, and reconciliation is by recorded correction
    events (§4 UNLINK / correction) — an already published Cabinet ID is
    never silently reassigned.
- What `prev_hash` does and does not do (qualified claim): each append
  records the previous line's hash (§4 byte rules), so within a presented
  history a broken predecessor reference is mechanically detectable, and
  with the exact byte rules plus a **trusted accepted head**, many edits,
  removals, and reorderings are detectable. `prev_hash` alone does **not**
  prevent forks (two successors of one predecessor can each validate
  locally), double allocation, unauthorized actors, forged evidence,
  duplicate membership, or a semantically wrong link. Fork/double-mint
  safety comes from the accepted-head + fold-validation discipline above,
  not from the hash chain by itself.
- No other system mints Cabinet IDs. Owning systems keep minting their
  native IDs exactly as today (identity contract rule 1, read per the
  draft clarification in §7).

## 4. The registry (source of truth for all stamping)

Stamping never happens *inside* a foreign store first. The registry is the
source of truth; every stamp elsewhere is a projection of a registry event.

Event shapes (one JSON object per line, append-only):

```
{"type":"MINT","cabinet_id":"cab-0001","at":"<iso8601>","actor":"<lane/program>",
 "reason":"new-work-area","prev_hash":"<sha256 of previous line>"}

{"type":"LINK","cabinet_id":"cab-0001","at":"<iso8601>","actor":"<lane/program>",
 "member":{"system":"claim-register","id":"C-0071","kind":"epistemic-claim"},
 "relation":"primary",
 "evidence":"sha256:<digest of anchored segment>@<iso8601 capture time>",
 "reason":"shared-artifact",
 "prev_hash":"<sha256 of previous line>"}

{"type":"UNLINK","cabinet_id":"cab-0001","at":"<iso8601>","actor":"<lane/program>",
 "member":{"system":"claim-register","id":"C-0071","kind":"epistemic-claim"},
 "relation":"primary",
 "corrects":"<registry line number of the LINK event it reverses>",
 "evidence":"sha256:<digest of anchored segment>@<iso8601 capture time>",
 "reason":"evidence-refuted","prev_hash":"<sha256 of previous line>"}
```

Event rules (normative):

- **Mandatory fields.** `reason` is mandatory on MINT, LINK, and UNLINK;
  `evidence` is mandatory on LINK and UNLINK. An event missing a
  mandatory field fails validation and is never accepted. (The first
  draft's examples omitted LINK's `reason` and UNLINK's `evidence`
  although §7 required both — corrected here.) Field *values* in
  history lines obey §6's history rule — a closed, tombstone-grade
  inventory (no titles or member-derived free text; `reason` as a code
  below; `evidence` digest-bound) — and an event that cannot be
  expressed within that inventory fails validation like a missing
  field.
- **Reason codes.** In history lines `reason` is a code, not free text
  (§6 history rule): MINT — `new-work-area`; LINK — `shared-artifact`,
  `dispatch-record`, `admitted-claim-describes`, `title-citation`,
  `owner-decision`, `merge-movement`, `secondary-relation`; UNLINK —
  `evidence-refuted`, `merge-movement`, `wrong-member`,
  `forget-consequence`, `owner-decision`. A fuller rationale may be
  retained in the owning namespace under the inherited privacy level
  and referenced by digest (the code suffixed with `@<sha256>`). The
  vocabulary extends only by spec amendment.
- **`relation`** is `primary` (default) or `secondary` (§1 policy). An
  UNLINK reverses exactly one LINK of the same relation, named by
  `corrects` (registry line number of that LINK event) — corrections are
  targeted, never bulk or implicit.
- **Fold semantics.** Registry state is the fold of the accepted history
  in order: MINT creates a Cabinet; LINK adds an active membership of the
  stated relation; UNLINK deactivates the LINK it corrects. Folding is
  idempotent — re-folding the same accepted history yields the same
  state, and re-applying an already-folded event changes nothing.
  Validation runs over the complete fold before acceptance (§3): schema,
  sequence uniqueness/monotonicity, referenced Cabinets exist, at most
  one active **primary** membership per member.
- **Projections and readback.** The registry fold is authoritative.
  Every projection (claim-ledger LINK/UNLINK events per §5.1, `INDEX.md`,
  spine-side display per §5.2) is owned by the Registrar, is built ONLY
  from the accepted fold (§3), and is verified by **readback against the
  accepted fold** after every build — including after UNLINK and after
  retry/crash recovery, since a projection that applied a LINK but lost
  its UNLINK is a live defect, not a cosmetic one. Projection writes are
  append-only and retry-safe: re-projecting an event that is already
  present is a no-op, detected by the event's registry line number.
- **Hash byte rules.** Lines are UTF-8 JSON, one object per line,
  terminated by a single LF. `prev_hash` is the lowercase hex SHA-256 of
  the previous line's exact bytes **excluding** its trailing LF. The
  first line's `prev_hash` is the SHA-256 of the empty string (genesis).
  Cabinet sequences are compared **numerically**, not lexically (the
  §2 widening past 9999 depends on this). A trailing partial line (no LF
  terminator, or invalid JSON) is not an event: the fold MUST refuse the
  registry until the partial tail — a crash artifact containing no
  complete event — is removed and the removal recorded in `INDEX.md`.
- **Evidence anchors bind an immutable source segment** (identity
  contract rule 6), not a mutable line number alone: a commit hash +
  path + line/heading anchor, or a bounded probe artifact named with its
  digest and capture time. An anchor whose target has moved or vanished
  fails verification (backfill plan, Step 5) until re-anchored by a
  correction event. In registry history lines the anchor is recorded
  only in the digest-bound form of §6's history rule (segment SHA-256 +
  capture time); the literal coordinates are resolved inside the owning
  namespace, under its access rules, when verification re-reads the
  segment.

- `system` is one of: `vm-spine`, `claim-register`, `home-runloop`,
  `claim-service` (the four namespaces of Phase 0 §2). New systems join by
  spec amendment, not by improvisation.
- `kind` records the member's own object kind (e.g. `planning-task`,
  `epistemic-claim`, `execution-claim`, `dispatch`, `work-unit`) and is
  never rewritten to a common kind — grouping is not merging.
- A work area's `domain` classification uses the plan's controlled tag
  vocabulary (`domain:` axis, plan §5) — no free tags — and, like its
  name/slug and title, is recorded **only in `INDEX.md` and
  projections**, never in a registry history line (§6 history rule:
  grouping values in history are opaque).
- Every LINK carries resolvable, immutable-segment evidence and a reason
  (identity contract rule 6 applied to links: a link without a resolvable
  anchor is an orphan and MUST NOT be recorded). Every UNLINK carries
  evidence and a reason too, and names the LINK it corrects.

## 5. Where the ID gets stamped, per namespace

Design only — the write path each owning system would use in the
implementation slice. Until then, membership lives in the registry alone.

### 5.1 VM claim register (`C-NNNN`) — LINK events in the claim ledger

- The register is an append-only event ledger (ADMIT / INVALIDATE).
  Stamping is a **new append-only event pair** in the same ledger flow:
  `{"entity":"C-0071","type":"LINK","cabinet_id":"cab-0001", …}` and its
  reversal `{"entity":"C-0071","type":"UNLINK","cabinet_id":"cab-0001", …}`,
  admitted through the register's normal inbox path. **Precondition:** the
  register's owning inbox/admission path must be qualified to accept and
  fold LINK/UNLINK before any such event is appended — no event is
  written into a path that cannot fold it back out.
- The original ADMIT record is never edited (lifecycle contract rules 3, 5:
  no silent edits; the ledger is the only write path for governed changes).
- Consumers (Phase 2 retrieval) resolve a claim's Cabinet ID by folding
  its LINK/UNLINK sequence (the registry fold is mirrored here; on any
  disagreement the accepted registry fold wins and the projection is
  rebuilt). An ordinary INVALIDATE of the claim does not delete its
  links — lifecycle state and linkage are separate axes — but linkage
  confers no retrievability: an invalidated claim stays out of default
  results (admission contract rule 2), links notwithstanding.
- **Forget is not an ordinary INVALIDATE.** An INVALIDATE with reason
  `forget` triggers the §6 forget procedure for the claim's derived
  entries — this projection included — in the same operation (admission
  contract rule 6(c)).

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
| 1 — one ID, assigned by owning system, never reused/reassigned/content-derived | **Conforms under the clarified reading drafted in §7** (clarification, not amendment-by-exemption). Read in isolation, "carries exactly one ID" is ambiguous about foreign references; read with the contract's purpose and its own rules 2, 5, and 7 — which *require* records to carry references to other objects' IDs — rule 1 fixes **native identity**, and a Cabinet ID carried as a typed foreign reference to a separately identified work-area grouping is not a second identity. The existing contract does not unambiguously ban such a reference, so no amendment is logically required merely because a linkage key is present. This program nevertheless **chooses** a recorded human clarification of rule 1 before implementing (§7, Step 0 gate in the backfill plan) — a ratification decision, not a logical necessity, and nothing is self-authorized by this reading. |
| 2 — IDs namespaced by owning system; cross-system reference = (system, ID) pair | **Conforms.** One formulation, used everywhere in this spec: a record citation is **always the native (system, ID) pair**; a citation MAY be **annotated** with the record's Cabinet ID, and the annotation never substitutes for the pair — parsers, lookups, and interfaces must address a member by its native pair. A bare Cabinet ID cites a **work area only**, and only inside the explicit Cabinet namespace; it is never a record citation and does not waive rule 2 for any object. |
| 3 — content_hash detects change only; hash is never an ID | **Conforms.** Cabinet IDs are sequential, assigned at mint; registry `prev_hash` is a chain-integrity device, never an identifier. |
| 4 — one execution authority (HOME); mirrors carry the authority's (system, ID) pair and never mint a second identity | **Conforms.** The Cabinet ID is not a task identity and confers no execution authority; HOME's authority is unchanged; the VM spine remains a read-model (§5.2). **Explicit prohibition:** no admission, dispatch, lease/fence, closure, or ownership decision may be **inferred** from a Cabinet match. For an actual task mirror, a Cabinet link never substitutes for the HOME authority's (system, ID) pair; a VM planning registration grouped with HOME records remains a planning record — grouping does not certify task equivalence or cure an absent authority reference. |
| 5 — attempt/result reference (task ID, ordinal) | **Conforms / unaffected.** Run-loop attempts and results inherit work-area membership through their work unit (§5.3); their native references are unchanged. |
| 6 — fact/record carries a `path#line` provenance anchor; orphans are not admitted | **Conforms, extended to links.** Every LINK event must carry resolvable evidence (§4); an unanchored link MUST NOT be recorded. |
| 7 — epistemic claims and execution claims are different kinds; never merge semantics | **Conforms.** `kind` is recorded per member and never rewritten (§4). A shared Cabinet ID asserts only **"concerns this work area"** — never "same object", never "same kind of claim", never "proves this claim", and never "same execution state". No member's PASS, admission state, or lifecycle state transfers to another member through shared membership. |

Lifecycle contract: LINK/UNLINK are append-only registry events with
evidence, actor, timestamp, and reason (§4), matching rule 5's event
shape; nothing in this spec edits or deletes an existing record in any
store (rules 3, 8).

Admission/privacy/forget contract — **registry entries are NOT exempt**
(corrected in fix round 1; the first draft's exemption contradicted
contract rules 4 and 6):

- Membership is itself a **derived fact / index relation**. Under rule 4,
  a registry entry (MINT / LINK / UNLINK), the registry index, and every
  projection generated from them **inherit the privacy level of each
  record they are derived from**. An entry derived from several members
  is exposed whole only at the strictest member level involved; retrieval
  surfaces additionally filter per member, so a query entitled to member
  A but not member B never sees the entry insofar as it derives from B.
  Namespace access to the registry itself is scoped accordingly — the
  registry is not a house-readable side channel around a `private` or
  `secret-pointer` member.
- Metadata fields are content-bearing and constrained accordingly.
  The history-line fields `reason` / `evidence` carry no record content
  and no secrets (rule 4's `secret-pointer` discipline: pointers, never
  the secret), and are themselves subject to the inherited privacy
  level — an association or evidence path can disclose sensitive
  information even when no source body is present. In registry history
  lines these fields are bound further by the history rule below —
  tombstone-grade by construction. A work area's **name/slug, title,
  and `domain` label are not registry fields at all**: they exist only
  in `INDEX.md` and projections, inherit the privacy level there, and
  are purged from those surfaces by the forget operation below.
- **Forget (rule 6) applies to linkage in the same operation.** When a
  member is forgotten (lifecycle INVALIDATE, reason `forget`): (a) the
  invalidation is recorded; (b) the member's derived entries are **purged
  or invalidated in the same operation** — its memberships disappear from
  the registry fold, `INDEX.md`, and every projection (§5.1 included);
  the name/slug, title, and `domain` entries under which it appeared in
  `INDEX.md` and projections are purged in the same operation (registry
  history lines carry no such labels at all — history rule below); and
  LINK/UNLINK `evidence`/`reason` values derived from the forgotten
  record do not remain readable in the operative fold. What remains on
  operative surfaces is tombstone-grade only — (system, ID), forget
  timestamp, actor — per rule 6(b); (c) post-forget verification (§5,
  Step 5 of the backfill plan): a default query returns the tombstone,
  not the membership — **and retained history is verified too**: every
  retained Git object of every registry file (`REGISTRY.jsonl`,
  `INDEX.md`, any projection committed to this repo) is checked for the
  forgotten member, and any beyond-tombstone payload found there is an
  exposure under the history rule below, not a pass.
  Append-only Git history alone does **not** make retained sensitive
  metadata compliant: the operative fold, index, and projections must
  not expose it — and the audit history itself is bound by the same
  rule, per the history rule below. Metadata minimization is therefore
  not a best effort: what may enter history at all is fixed by
  construction, and any exposure that nevertheless exists blocks its
  path until treated. There is no "named gap" state.

### History rule — tombstone-grade by construction; exposure blocks until treated

Rule 6(b) governs what may *remain* of a forgotten record: a tombstone
carrying (system, ID), forget timestamp and actor — content does not
remain. The Registrar's append-only Git history is audit history for
every member it names, so the same rule binds what that history may
ever contain. Rule 6(c) invalidation of a derived entry does not make
a sensitive payload retained in a Git object harmless, and rule 7
supplies no exception for retained sensitive content.

**Content rule (closed inventory).** A registry history line may
contain only:

- structural fields: `type`, `cabinet_id`, `at`, `actor`, `prev_hash`,
  and, for LINK/UNLINK, `relation` / `corrects`;
- the member's (system, ID) pair and `kind` — exactly the identifiers
  a rule 6(b) tombstone itself carries;
- `reason` as a **reason code** from the controlled vocabulary in §4,
  optionally followed by `@<sha256>` — the digest of a fuller rationale
  note retained in the owning namespace under the inherited privacy
  level (above). Free-text reasons are not written to history;
- `evidence` as a **digest-bound reference**: the SHA-256 of the
  anchored source segment plus its capture time (for probe artifacts,
  the artifact digest). Literal evidence coordinates — file paths,
  line numbers — never appear in history lines; they are resolved
  inside the owning namespace, under its access rules, when
  verification re-reads the segment and checks the digest (backfill
  plan Step 5, check 2, is satisfied by this binding).

**Grouping values in history are opaque.** The only grouping value a
history line carries is `cabinet_id` itself. No history line — MINT
included — carries a work-area slug, name, title, or `domain` label.
The reason is the content, not the authorship: a descriptive label the
Registrar coins itself (say, for the SimLab paid-test area) is still
readable association text sitting in immutable history; that the
Registrar chose the words rather than copying or paraphrasing a member
record does not make it tombstone-grade, and independent origination
does not prevent it from disclosing a sensitive association once a
member is linked under it. A descriptive grouping value in a history
line therefore fails validation like any other out-of-inventory field.
Human-readable names/slugs and the `domain` classification live only
on the purgeable surfaces — `INDEX.md` and projections — where the
forget operation purges them in the same operation.

An event whose fields cannot be expressed within this inventory
fails validation and is not appended (§4): registry history is made
tombstone-grade at write time, not redacted after the fact — no
member content, descriptive association text, or raw evidence path
ever enters a registry line. `INDEX.md` and committed projections
stand differently: forget purges their **current** surfaces in the
same operation, but their **historical Git blobs are retained
history**, and they are inside the exposure scope below — a title or
slug surviving in an old `INDEX.md` blob is an exposure to be blocked
and treated, never a compliant remainder. With the inventory and
that scope both in force, a completed forget leaves nothing in
retained history — registry lines or registry-file blobs — beyond
what rule 6(b) permits a tombstone to carry.

**Exposure: block, then treatment.** If non-tombstone-grade metadata
deriving from a member is nevertheless present in retained history
when a forget lands — legacy lines predating this rule, or a
validation escape — the forget is not complete, and the exposure is
handled as a block, never as a note:

- **Scope: every retained Git object of every registry file** (fix
  round 3). "Retained history" in this subsection means the
  `REGISTRY.jsonl` accepted history **and** every historical Git blob
  of `INDEX.md` **and** of any projection file committed to this
  repo. The exposure scan, the block, the rule-7-authorized
  treatment, and the post-treatment re-scan all cover those objects
  exactly as they cover accepted-history lines: purging `INDEX.md`'s
  current entries does not reach a title in an earlier committed
  version of it, so that blob is scanned, blocked on, treated, and
  re-scanned like any offending registry line.
- The **affected path is BLOCKED** from the moment the exposure is
  identified: no new events for the affected Cabinet, no projection
  builds or stamps derived from it, no join depending on it proceeds,
  and default retrieval for the affected Cabinet returns tombstone-only.
  The block stands indefinitely while the exposure stands; an
  unresolved exposure is a stopped path, not a documented gap.
- The only exit is an executed **and verified history treatment**: a
  recorded owner decision under contract rule 7 authorizing the
  specific treatment of the affected objects (history rewrite
  replacing the offending lines or blobs with tombstone-grade content,
  or removal of the affected objects — an owner decision may authorize
  the deletion this requires). The Registrar executes the treatment; the
  treated history is re-folded and re-accepted under §3, with the
  decision and the treatment recorded alongside the new accepted head;
  and verification re-scans the treated history end to end — every
  retained Git object of every registry file in the scope above — so
  no payload beyond tombstone-grade for the forgotten member may
  remain before the block lifts. This spec **requires** the treatment as the
  sole compliant path; naming a future owner decision does not
  substitute for it, and absent that decision the block — not silent
  non-conformance — is the state of the path.
- Retirement under the backfill plan (Step 4) stands under this rule:
  a non-survivor's history is retained **subject to rule 6** — where a
  forget applies to any of its members, this treatment governs, and
  "stands forever" is never a promise above the forget obligations.

## 7. Clarification of identity rule 1 (RATIFIED 2026-11-05 — applied to contracts/identity.md)

> **RATIFIED by Tân, main chat, 2026-11-05 12:16 PT (option 1, as drafted)** and applied to
> `contracts/identity.md` (clarification note under rule 1 + footnote [*] on the non-goals).
> Decision record: `docs/decisions/DECISION_2026-11-05_RULE1_CLARIFICATION_RATIFIED.md`.
> The text below is the ratified text, preserved as ratified.

Fix round 1 replaced the first draft's proposed new "rule 8" with this
narrower instrument, per review Part B: the contract does not
categorically ban a typed foreign reference, so what is needed is a
**clarification of rule 1**, not an exemption-granting amendment. The
following text was the **DRAFT for Tân's ratification**; it is now in
force as ratified (see the banner above) and **has** been written into
`contracts/identity.md` by the ratification commit. If ratified, it is
recorded as a clarification note under rule 1 in `contracts/identity.md`
by a recorded decision, and the non-goal "No global ID-minting service in
this phase" gains the footnote marked [*].

> **Clarification of rule 1 (draft).** "Carries exactly one ID" in rule 1
> means exactly one **native identity**: the ID assigned once by the
> object's owning system. Typed references to other objects' IDs are
> references, not identities — the contract itself requires them (rules
> 2, 5, 7) — and rule 1 does not prohibit them. A Cabinet ID (`cab-NNNN`)
> carried by a record is such a reference: a foreign key to a separately
> identified **work-area grouping**, never an identifier of the record
> itself. It never renames, re-keys, or supersedes the native ID; a
> record is addressed and cited only by its native (owning-system, ID)
> pair, which MAY be annotated with its Cabinet ID — the annotation never
> substitutes for the pair. A bare Cabinet ID identifies a work area
> only, within the Cabinet namespace. Primary/secondary/pending
> membership follows the Cabinet spec's policy; shared membership asserts
> only "concerns this work area" and merges no kinds, lifecycles, or
> semantics (rule 7). **No admission, dispatch, lease/fence, closure,
> ownership, or execution-authority decision may be inferred from a
> Cabinet match** (rule 4 is unaffected). Cabinet IDs are allocated only
> by the Cabinet Registrar, sequentially, never reused, and without
> reference to any record's content; membership changes are append-only
> registry events (LINK / UNLINK, each with evidence, actor, timestamp,
> and reason).
>
> [*] The Cabinet Registrar **is** the central allocator of grouping keys
> for the Cabinet namespace — a registry-keeping function of the PAI Repo
> program, deliberately not a runtime service. Owning systems still mint
> all native IDs. This footnote records that scope honestly: the
> non-goal bars a global runtime ID-minting service; the Registrar's
> central grouping-key allocation is the recorded exception, and it
> stands or falls with the ratification decision itself.

## 8. What this spec deliberately does not do

- No minting, no stamping, no registry creation — design only (slice 1).
- No changes to any live store, endpoint, or config on HOME/MSI/VM.
- No resolution of ambiguous memberships: where evidence supports two
  work areas (e.g. the M8 / Store overlap flagged in Phase 0), the backfill
  plan flags the pair for a human decision — the Registrar never guesses
  (plan §3 rule 7 pattern).
- No new namespaces, tag axes, or object kinds.
