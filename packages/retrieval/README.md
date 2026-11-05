# packages/retrieval — PAI retrieval, the front door (Phase 2)

Status: **built + measured; Codex review 2026-11-05 = FAIL (8 blockers) → fix round 1 applied, awaiting targeted Codex re-review.** Not DONE.

Deterministic, stdlib-only, no LLM anywhere on the read or write path.
Retrieval is advisory: sources are the truth; every result carries its
source path + line anchor, and any source that changed after indexing is
gated STALE instead of being answered from silently.

## What is here

| File | Role |
|---|---|
| `retrieval_index.py` | Indexer: claims register + inbox, spine DB (tracked tasks), STATUS.md set, MEMORY.md, goal workspaces → `index/retrieval_index.jsonl` + `index/manifest.json` (runtime artifacts, gitignored) |
| `retrieval_query.py` | Query CLI: validity gate → BM25 (+ query-coverage factor) → F2 snippet assembly |
| `validity.py` | The Knowledge Room validity gate layer (see import table below) |
| `tests/test_retrieval.py` | 33 tests: the pilot's 12 ported + Phase 2 tests (snippets, F4, gate, orphan rule) + fix-round-1 regressions for the 8 Codex Phase 2 blockers |

## Lineage — the pilot port

Ported from `~/workspace/pai-query-layer/` (pilot SPEC_V1, Codex PASS
2026-11-05 after 3 blockers). The pilot directory is untouched historical
evidence. All pilot fixes are intact and regression-tested here:

- **WAL-aware freshness** — SQLite sources are fingerprinted by CONTENT
  (schema + all `tasks` rows of a snapshot copy of main file + `-wal`),
  so WAL-only changes trip the gate (pilot blocker 1).
- **Snapshot reads only** — source DBs are never opened in place; no
  `-wal`/`-shm` or any file is ever created in a source directory
  (pilot blocker 2; directory-inventory test).
- **Uniform admission filter** — admission is decided by SOURCE (the
  record's `admitted` flag), on EVERY path and EVERY lifecycle: an
  unadmitted (inbox) record requires `--include-unadmitted` even when
  its lifecycle is terminal (superseded/invalidated), including on
  exact claim-ID lookup (pilot blocker 3; Phase 2 fix round 1
  blocker 1). The one documented exception is lifecycle inspection: an
  explicitly named invalidated/superseded ADMITTED claim can be viewed
  via `--claim`, annotated as such.

Contract conformance (repo `contracts/`): namespaced IDs
(`claim-register:` · `vm-spine:` · `vm-workspace:` · `muse-memory:` ·
`goal-workspaces:`); `content_hash` is a change detector, never an ID.
File-derived IDs are **stable anchor identities**
(`<file>#<heading/bullet-slug>`, scheme `anchor-slug-v2`): inserting
lines elsewhere in a file does not re-key a record — the pilot's
`#L<line>` IDs were re-minted once under this scheme, mapped by the
unchanged (source path, anchor) pair. Every record carries exactly one
`namespace`, a `lifecycle`, a `privacy` level that travels with it
(source-declared privacy is preserved verbatim into the index and shown
in every JSON mode), plan-§5 tags (`domain:`/`kind:`/`src:`), and a
`path#line` anchor that must actually **resolve** — the source file
exists and the line lies within it — or the record is an orphan,
dropped + counted in the manifest (identity contract rule 6).
Epistemic claims (claim register) and operational data are never
merged; the register's INVALIDATE lifecycle is applied at index time
(`invalidated` + `invalid_at` from the event's `at` timestamp).
An INVALIDATE with `reason: forget` produces a **tombstone**: the
(system, ID), forget timestamp and actor remain, the content is purged
from the index and unretrievable on every path
(admission-privacy-forget rule 6). A `secret-pointer` record indexes
only its pointer, never body content (rule 4).

## F2 — snippet mode

Default output is bounded snippets, not whole records:

- The record text is split into units (lines; over-long lines are split
  into sentences by a **lossless slicing splitter** — terminal
  punctuation splits only before whitespace/end, so `25.0%`, `v2.6.1`,
  `base_rag.json` stay intact; a findall-based splitter silently ate
  such segments and was removed after the golden set caught it).
- Each unit contributes its best window, scored by unit-document-
  frequency weights (a term concentrated in one unit is more locative
  than one spread across title/slug/body) plus a small capped **factoid
  digit bonus** (house questions usually ask for a number/date/price;
  documented heuristic, breaks near-ties only). Best units are kept in
  original order until the cap fills.
- **Proportional cap** (JSON snippet mode): per-result cap =
  `min(max(260, file_bytes/6), max(120, file_bytes/3), 900)` — measured
  in file **bytes** (`os.path.getsize`), the budget scales with the
  source file the snippet replaces. This is the direct answer to Codex's
  standing F2 note on the pilot: a fixed cap loses at both ends
  (envelope + cap exceed a small file; a 260-char window cannot hold
  evidence sitting deep in a claim). Plain-text output uses the flat
  `--snippet-chars` cap instead. `--full` returns whole records
  (pilot mode).
- Ranking: BM25 × query-coverage factor (a record covering more of the
  question's distinct terms outranks a short record repeating fewer).
- Corpus-IDF snippet weights were tried and **measured worse** on the
  golden set (24/32 vs 31/32 in the same harness) and were reverted;
  the experiment is recorded in `../../evals/retrieval/RESULTS.md`.

## F4 — goal / tracked-item sources

`index_goals()` indexes `~/workspace/goals/<slug>/GOAL.md` and
`STATUS.md` as a first-class kind (`goal`, system `goal-workspaces`),
parsing `Goal ID:` where present and carrying `goal_slug` on every
record, under the same freshness/admission discipline as every other
source. The generic STATUS glob excludes `~/workspace/goals/**` (the
goal indexer owns those files; no double-indexing). Files ≤600 chars
index as a single record (splitting a tiny file creates a title-chunk
ranking trap).

**Stated limitation (verified 2026-11-05):** some tracked-item facts
exist ONLY in the Muse tracked-item store (PostgreSQL-backed), not in
any file — e.g. the Olympus Facebook Marketplace listing IDs
(`1483712927027392` etc.) and the eBay item number `407340766947` for
the 45mm listing. No file indexer can retrieve them. The golden set's
eBay question was retargeted to facts that live in `GOAL.md`; closing
this gap needs a tracked-item export adapter (future phase work), and
until then those facts are simply not retrievable — said plainly, per
the plan's no-invention rule.

## Knowledge Room validity gate — imported rules

Gate layer: `validity.py`, applied in `retrieval_query.py` BEFORE
lexical ranking, in the Knowledge Room's own compile order. Exclusions
are always reported with KR reason strings (count + reason histogram in
snippet mode; the capped list in `--full` mode / `--show-excluded`) —
nothing is silently dropped.

HOME sources (read-only, read 2026-11-05):
`C:\temp\pai-run-loop-external-deps\knowledge_room_v1\README.md` and
`...\src\knowledge-room.js` (the Chief-generation copy under
`C:\ProgramData\PAI_CHIEF\generations\...\knowledge_room_v1\` is
byte-identical except one whitespace byte; inventory row H042: the
catalog has NO authority of its own — it is a derived view, which is
why it fits as a gate layer over sources that remain the truth).

| # | Knowledge Room rule (source) | Implementation here | Faithful / adapted |
|---|---|---|---|
| 1 | Retrieval order: state → project/domain validity → freshness → counterevidence → lexical/task relevance → budget (README, verbatim) | `validity.gate()` stage order + query pipeline order | Faithful |
| 2 | Default compile returns only ACTIVE items; CANDIDATE / CHALLENGED / SUPERSEDED / ARCHIVED / REVOKED / stale / counterevidenced are excluded (README) | Lifecycle→state map: admitted→ACTIVE, unadmitted→CANDIDATE, invalidated→REVOKED, superseded→SUPERSEDED, expired→ARCHIVED; non-ACTIVE excluded by default. Opt-ins (`--include-unadmitted`, `--history`) waive ONLY the state reason they name: the record is re-gated through applicability → freshness → counterevidence before it may return (fix round 1, Codex blocker 2) | Faithful in semantics; state names mapped to the repo lifecycle contract (contracts/lifecycle.md) |
| 3 | Exclusions are reported with reason strings: `STATE_<status>`, `PROJECT_MISMATCH`, `DOMAIN_MISMATCH`, `ENVIRONMENT_REQUIRED`, `ENVIRONMENT_MISMATCH`, `RELEASE_REQUIRED`, `RELEASE_MISMATCH`, `STALE`, `INVALID_FRESHNESS`, `COUNTEREVIDENCE_PRESENT`, `LOW_RELEVANCE` (knowledge-room.js) | Same strings, emitted by the same stages (`validity.py`). Below-threshold relevance — including zero-overlap records under a tokenized query — is reported as `LOW_RELEVANCE`, never silently omitted (fix round 1, Codex blocker 4) | Faithful (verbatim strings) |
| 4 | Freshness: `review.freshUntil` — absent → CURRENT_BY_TRIGGER (pass), past → STALE, unparseable → INVALID_FRESHNESS (knowledge-room.js) | Mapped onto this package's stronger signal: content fingerprint (hash / WAL-aware SQLite fingerprint) differs → STALE; fingerprint computation fails → INVALID_FRESHNESS; source missing → STALE (freshness unverifiable). No `freshUntil` field exists in PAI records, so the timestamp branch cannot be imported literally | **Adapted** — same reason vocabulary and stage position, stronger evidence signal; the `freshUntil` rule itself is NOT present and is not claimed to be |
| 5 | ACTIVE items must carry source + evidence + reopen path (`ACTIVE_KNOWLEDGE_EVIDENCE_REQUIRED`) | Indexer-side orphan rule, enforced as an actual resolution check (fix round 1, Codex blocker 3): a record is admitted only if its source file EXISTS and its anchor RESOLVES inside it (`line N` within the file's line count; spine `tasks.task_id=` locators resolve from the snapshot read) — the package mapping of KR's sourceRefs + evidenceFor + reopenPath, where the anchor is both the evidence pointer and the reopen path. Failures are dropped at index time and counted in the manifest (`orphans_dropped`) | Faithful in effect, enforced at admission instead of compile (stronger) |
| 6 | Relevance threshold: score < 0.16 → LOW_RELEVANCE (knowledge-room.js) | BM25 normalized as s/(s+1); below 0.16 → excluded LOW_RELEVANCE, zero-overlap included | **Adapted** — KR's 0.16 is applied to its own salience/temperature-weighted score; PAI records carry no temperature field, so the threshold is applied to normalized BM25 instead. The 0.16 constant and the reason string are KR's; the score it gates is not |
| 7 | Budget: integer in [1, 32], default 8, else `KNOWLEDGE_BUDGET_INVALID`; applied after relevance sort; deterministic tie-break: **score desc → salience desc → knowledgeId asc** (knowledge-room.js compile sort) | `validity.check_budget()` + CLI `--limit` validation (exit 2 with the KR message); result sort is (score desc, salience desc, id asc). Salience is a record field: carried from the source when it declares a numeric value, else 0.0 — house sources rarely declare it today, so the salience step usually falls through to id; the ORDER is KR's, the field population is the adaptation (fix round 1, Codex blocker 4) | Faithful (this package's default limit is 5, KR's is 8 — a caller default, not a rule) |
| 8 | Applicability: item validity scopes (projectId / domain / environments / releases) checked against the compile context; an item scoped to environments/releases with no context value → `*_REQUIRED`, with a different value → `*_MISMATCH`; project/domain compare only when the context supplies them (knowledge-room.js) | `validity.applicability()` over record fields `validity_project` / `validity_domains` (genuinely read by the gate — fix round 1, Codex blocker 4) / `validity_environments` / `validity_releases`, context from `--project/--domain/--environment/--release` | Faithful in semantics; **one documented adaptation**: domain comparison is slug-normalized containment, because house domains are free text ("Widget Domain") where KR's are exact IDs |
| 9 | Counterevidence: an item with counterevidence is excluded (`COUNTEREVIDENCE_PRESENT`) | Checked over the record's `evidence_against` field. In the claim register, counterevidence is realized as INVALIDATE events, which already land in the state stage; the explicit-field check is implemented for any source that populates it | Faithful (mechanism present; register data exercises it via the state stage) |

**Not imported, said plainly:** KR's candidate routing
(`routeCandidate` — admission-side scoring on write) is out of Phase 2
scope and was not imported. KR's relevance formula weights
(salience/temperature/recency fields) cannot be imported — PAI records
do not carry those fields; rule 6 above is the honest substitute. No
rule in this table was invented: every row traces to the README or the
JS source named above; where the source had no equivalent (rule 4's
timestamp branch), the table says so instead of paraphrasing one into
existence.

## Usage

```
python3 retrieval_index.py                 # (re)build index/
python3 retrieval_query.py "câu hỏi" --json [--limit N] [--kind goal]
python3 retrieval_query.py --claim C-0128 [--include-unadmitted] [--history]
python3 retrieval_query.py "question" --full          # whole records
python3 -m unittest discover -s tests                 # 33 tests
```

Measurement: `../../evals/retrieval/` (golden set + runner + RESULTS).
