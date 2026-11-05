# Fix round 3 addendum — Phase 2 retrieval (P0 of targeted re-review 2)

Contract: `CODEX_REREVIEW_PHASE2_FIX2_2026-11-05.md` — verdict **FAIL on
exactly one ground (P0)**; probes P1–P4 all PASS and were not disturbed.
Base commit `b891da9`. Suite: **36/36 green on the VM**, before and after.
End state: **fixed, awaiting targeted Codex re-review 3 — not DONE.**

| # | Item (re-review 2) | Fix | Evidence |
|---|---|---|---|
| P0 | **Suite 35/36 on Windows:** `test_source_root_maps_canonical_workspace_path` (`test_retrieval.py:758`) asserted a forward-slash path string. `resolve_old_path()` re-roots the canonical string's post-`/workspace/` tail verbatim, so on Windows its result mixes separators (`mirror\some-domain/STATUS.md`) while the test's `os.path.join`-built expectation is fully OS-native (`mirror\some-domain\STATUS.md`). Codex ruled the `--source-root` **behavior** correct (probe P2, with and without `--source-root`); only the assertion was separator-dependent | Test-only change: the assertion now compares `os.path.normpath(...)` of both sides. normpath folds both to the host separator — identity on POSIX for these clean paths, `/` → `\` on Windows — so the assertion passes identically on both, and still fails if the mapping points at a wrong root or drops the relative tail (the real mapping is still what is asserted). No production code touched: `run_eval.py` / `retrieval_query.py` logic unchanged | VM suite 36/36 after the change. Windows-semantics check (ntpath simulation of the exact strings in Codex's P0 evidence): raw equality `False` (reproduces P0), normpath equality `True`; wrong-root and dropped-tail variants still compare unequal |

## Separator audit (rest of the suite)

The whole suite (`packages/retrieval/tests/test_retrieval.py`, the only
file P0's discover command runs) was audited for other
separator-sensitive string assertions on paths. **None found.** Every
other path assertion compares values of the same lineage — both sides
derived from the fixture's own `os.path.join`-built strings, the
indexer's monkeypatched globals, glob/os.walk on the host running the
test, or same-code/same-host record contents — so both sides are
OS-native together on any host:

- `test_status_dedup_by_content_hash` (status/goal `source_path`
  membership), `test_kinds_and_counts` (manifest source path),
  stale-source assertions (`stale_sources` vs fixture paths),
  freshness-state dict keys — expected and actual share the fixture
  path strings.
- `test_determinism_modulo_timestamp` and `directory_inventory` —
  both sides produced by the same code on the same host in one run.
- `test_source_root_maps_canonical_workspace_path`'s sibling assertions
  and `test_unresolved_source_named_not_raised` — `resolve_old_path`
  returns the input literal unchanged there; the literal is compared
  to itself.
- Remaining slash-containing literals are data, never compared against
  OS-built paths: `"/nonexistent/p"` (orphan-rule input),
  `"vault:widget/master-key"` (a URN pointer, not a filesystem path).

## Deliberately unchanged

- All production behavior — the P0 defect was in the test, not the code.
- Probes P1–P4's surface: blocker 6 tombstone, eval portability /
  UNRESOLVED-SOURCE accounting, token gate rev2, regression spot-checks.
