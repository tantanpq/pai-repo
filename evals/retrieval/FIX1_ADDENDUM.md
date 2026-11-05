# FIX1 ADDENDUM — Phase 2 fix round 1 (2026-11-05)

Response to `~/workspace/pai-repo-program/CODEX_REVIEW_PHASE2_2026-11-05.md`
(verdict FAIL, 8 blockers + 2 extras). F2 snippet design and F4
disclosure passed the review and were NOT changed. Every blocker below
was reproduced first in the reviewer's own probe shape, then fixed,
then pinned by a regression test in
`packages/retrieval/tests/test_retrieval.py` (class `TestFixRound1`,
plus the rewritten `test_orphan_rule`). Suite: **22 → 33 tests, all
green.** Eval rerun: correctness **31/32 snippet · 32/32 full**
(unchanged); token wins **26/32** (was 32/32 — see RESULTS.md gate
note: the mandatory labels from blockers 1+5 cost ≈17 tokens/result
and honestly flip six tiny-file questions; reported as measured).
End state: **fixed, awaiting targeted Codex re-review — not DONE.**

| # | Blocker (review) | Fix | Reproducing test |
|---|---|---|---|
| 1 | Admission non-uniform: inbox record with `superseded_by` got lifecycle "superseded" at index time and passed the claim-ID filter, which tested only `lifecycle == "unadmitted"`; snippet JSON carried no lifecycle/admission labels | Admission is decided by SOURCE: the indexer sets `admitted = admitted_source` (orthogonal to lifecycle), and BOTH query paths exclude `admitted is False` unless `--include-unadmitted` — on every lifecycle (the `--history` waiver can no longer surface inbox material either). Snippet JSON entries now always carry `lc` (lifecycle), `adm` (admitted), `p` (privacy), `ns` (namespace) | `test_blocker1_inbox_superseded_id_lookup` (Codex's `C-PROBE-INBOX-SUPERSEDED` fixture verbatim) · `test_blocker1_snippet_json_labels` |
| 2 | `--include-unadmitted` bypassed applicability, freshness and counterevidence | `validity.gate(..., waive_state=True)`: the opt-ins (`--include-unadmitted`, `--history`) waive ONLY the state stage; a waived record is re-gated through applicability → freshness → counterevidence and excluded with that stage's reason if it fails. README row 2's promise is now the code's behavior | `test_blocker2_opt_in_waives_only_state` (counterevidence → `COUNTEREVIDENCE_PRESENT`; wrong `--domain` → `DOMAIN_MISMATCH`; source edited after indexing → `STALE` — the reviewer's three-part `opt_bypass` probe) |
| 3 | KR evidence equivalence false: nonexistent path + `line 999999` admitted, orphan list empty | `admit()` now enforces KR's ACTIVE-evidence conditions as an actual resolution check (`anchor_resolves`): source file must EXIST and the anchor must resolve inside it — `line N` within the file's (size/mtime-keyed) line count; spine `tasks.task_id=` locators resolve from the snapshot read. The anchor is both the evidence pointer and the reopen path (KR: sourceRefs + evidenceFor + reopenPath) | `test_orphan_rule` (rewritten: nonexistent path → orphan; `line 999999` → orphan; `line 1` of a real file → admitted — the pre-fix version of this test accepted `/p`, encoding the hole) |
| 4 | KR fidelity gaps: salience tie-break dropped; `validity_domains` populated but never read; zero-BM25 records silently omitted | (a) Records carry `salience` (source-declared numeric, clamped [0,1], else 0.0); result sort is KR's order — score desc → **salience desc** → id asc. (b) `validity.applicability()` now reads `validity_domains`: a context domain outside the declared scope → `DOMAIN_MISMATCH`. (c) Every gated record under a tokenized query is relevance-scored; below-threshold INCLUDING zero-overlap → excluded `LOW_RELEVANCE`, never silent. Also fixed in this row's scope: an unknown lifecycle maps to `STATE_UNKNOWN` exclusion instead of silently ACTIVE (KR validates its enum), and non-SQLite fingerprint failures now become `INVALID_FRESHNESS` like SQLite ones (review row-4 caveat) | `test_blocker4_salience_tie_break` (identical texts; id-asc alone would invert the pair) · `test_blocker4_validity_domains_gate` (the reviewer's GLOBAL + [RESTRICTED] vs OTHER case) · `test_blocker4_zero_overlap_reported` (`xyzzynotpresentanywhere`) · `test_blocker4_unknown_lifecycle_excluded` |
| 5 | Privacy did not propagate: source claims with `privacy="private"`/`"secret-pointer"` indexed as "house"; JSON snippets dropped privacy/namespace/lifecycle | `index_claims` passes source `privacy` through verbatim into the record (contract rule 4); snippet JSON shows `p`/`ns`/`lc` on every result (see blocker 1); full JSON already carried the fields. A `secret-pointer` record indexes ONLY its pointer (`pointer` field when the source declares one, else the provenance anchor) — body content never enters the index | `test_blocker5_privacy_and_secret_pointer` (sentinel text provably absent from index + all output modes; pointer preserved) |
| 6 | Forget not implemented: INVALIDATE reason=forget left content retrievable, no tombstone | The indexer recognizes forget events (`INVALIDATE` + `reason: "forget"`): the record becomes a **tombstone** — text purged to `""` at index time, carrying `forgotten`, `forget_at` (event timestamp), `forget_actor` (contract rule 6b/6c). Claim-ID inspection returns the tombstone; free-text paths cannot surface the content; text mode annotates `☠ FORGOTTEN at … by …` | `test_blocker6_forget_tombstone` (the reviewer's `C-PROBE-FORGET` shape: content gone from the index bytes themselves, tombstone returned by ID) |
| 7 | Markdown record IDs were physical `path#L<line>` offsets — one prepended blank line re-keyed a record while its content hash stayed constant (identity rules 1+3) | File-derived IDs are now **stable anchor identities**: `<file>#<heading/bullet-slug>` with a same-file ordinal for repeated slugs (`_IdMinter`, scheme `anchor-slug-v2` in the manifest). Identity follows the source segment, not its line offset; `content_hash` still detects content change; the `path#line` anchor remains as the (movable) provenance pointer. No-ID register records mint append-stable ordinals (`reg:n<i>` / `inbox:n<i>`) instead of line numbers. **Migration note:** existing `#L<line>` IDs were re-minted once under this scheme; old citations map via the unchanged (source_path, source_anchor) pair | `test_blocker7_stable_id_blank_line` (the reviewer's probe: prepend one blank line → same content hash, anchor line +1, **ID unchanged**) |
| 8 | Lifecycle timestamps lost: the indexer read only `date`/`ts`, dropping the real INVALIDATE `at` — C-0253 showed `invalid_at: null` | Event timestamps resolve `at` → `date` → `ts`. Source-declared `lifecycle` / `valid_at` / `invalid_at` are honored; supersession sets `invalid_at` from the superseding record's date (lifecycle rule 2). Verified on live data: **C-0253 now shows `invalid_at = 2026-11-04T12:21:27+00:00`, invalidated_by C-0257** | `test_blocker8_lifecycle_timestamps` (C-0253's exact event shape + an arrived-expired claim: lifecycle/invalid_at preserved, gate excludes it as `STATE_ARCHIVED`) |

## Extras

- **(a) `run_eval.py` portability:** `questions.json` old-path entries
  are re-rooted at the current machine's home (`resolve_old_path` —
  a foreign `/home/<user>` or `/Users/<user>` prefix is swapped for
  `~`, existing paths untouched), so the stock eval runs off-VM
  instead of dying on `/home/hatch/...`. The `.db` old-path baseline
  now reads from a snapshot copy (package read-only discipline)
  instead of an in-place `mode=ro` open. Unreadable baselines fail
  with the question ID named.
- **(b) RESULTS.md count honesty:** the pre-fix headline said 628
  records while its kind counts summed to 629 (reviewer's count: 629).
  RESULTS.md is regenerated from `last_run.json` + the rebuilt
  manifest: **630 records (claim 284 · goal 124 · status 116 ·
  task 63 · memory 43 = 630)**, 89 sources. Its F2/Q21 framing was
  also corrected to the byte-based cap the code actually uses.

## Deliberately unchanged

- F2 snippet design and F4 disclosure (review PASS) — no tuning,
  no retargeting.
- Exact-ID (`--claim`) inspection semantics from the pilot: an
  ADMITTED invalidated/superseded claim remains viewable by ID,
  annotated — only the admission decision moved to the source flag.
- The golden questions and gold strings: untouched.
