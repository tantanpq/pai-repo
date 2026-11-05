#!/usr/bin/env python3
"""Test suite for the pai-repo retrieval package (Phase 2).

Ports the pai-query-layer pilot's 12 tests (SPEC_V1 S6.1 + the 3 Codex
blocker regressions) to the ported code, adapted where Phase 2 semantics
intentionally differ (the Knowledge Room gate EXCLUDES stale/superseded
records from default results and reports them in `excluded`, where the
pilot only flagged them), and adds Phase 2 tests: F2 snippet mode, F4 goal
sources, the Knowledge Room validity gate, and the orphan rule.

Fixture-based: builds a miniature source tree in a temp dir (claims, inbox,
spine sqlite, STATUS.md set with one exact duplicate, MEMORY.md, and two
goal workspaces), indexes it, and verifies behavior end to end.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "..")
sys.path.insert(0, PKG)
import retrieval_index  # noqa: E402
import retrieval_query  # noqa: E402
import validity  # noqa: E402

QUERY = os.path.join(PKG, "retrieval_query.py")


def make_fixtures(root):
    ws = os.path.join(root, "ws")
    for d in ("dom-a", "dom-b", "dom-c",
              os.path.join("goals", "goal-alpha"), os.path.join("goals", "goal-beta")):
        os.makedirs(os.path.join(ws, d))
    claims = os.path.join(root, "claims.jsonl")
    with open(claims, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "ADMIT", "claim": {
            "id": "C-9001", "entity": "Widget Domain", "type": "STATUS", "status": "current",
            "date": "2026-11-01",
            "claim": "Widget throughput is 42 units per week exactly."}}) + "\n")
        f.write(json.dumps({"event": "ADMIT", "claim": {
            "id": "C-9002", "entity": "Other Domain", "type": "STATUS", "status": "current",
            "claim": "The other domain uses a purple anodized flange."}}) + "\n")
        f.write(json.dumps({"event": "ADMIT", "claim": {
            "id": "C-9003", "entity": "Widget Domain", "type": "STATUS", "status": "superseded",
            "superseded_by": "C-9001",
            "claim": "Old widget throughput was 40 units per week."}}) + "\n")
        f.write(json.dumps({"event": "INVALIDATE", "id": "C-9002", "by": "C-9001",
                            "note": "fixture: killed by a later register event"}) + "\n")
    inbox = os.path.join(root, "inbox.jsonl")
    with open(inbox, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "C-REVIEW-UNADMITTED", "entity": "Widget Domain",
                            "type": "STATE", "status": "current",
                            "claim": "Unadmitted widget rumor says throughput might double."}) + "\n")
    spine = os.path.join(root, "spine.db")
    con = sqlite3.connect(spine)
    con.execute("CREATE TABLE tasks (task_id TEXT, title TEXT, state TEXT, program TEXT, owner_surface TEXT)")
    con.executemany("INSERT INTO tasks VALUES (?,?,?,?,?)", [
        ("t-1", "Receipt noise one", "UNTRACKED", None, "tap"),
        ("t-2", "Receipt noise two", "UNTRACKED", None, "tap"),
        ("t-3", "Real queued widget task", "QUEUED", "widget-program", "op"),
    ])
    con.commit()
    con.close()
    status_a = "# STATUS — Widget Domain\n\n- **Throughput locked:** widget line runs 42 units weekly, verified on disk.\n- **Blocker:** waiting on a flange shipment.\n"
    with open(os.path.join(ws, "dom-a", "STATUS.md"), "w", encoding="utf-8") as f:
        f.write(status_a)
    with open(os.path.join(ws, "dom-b", "STATUS.md"), "w", encoding="utf-8") as f:
        f.write("# STATUS — Other Domain\n\n- **Flange note:** the purple anodized flange is load bearing.\n")
    with open(os.path.join(ws, "dom-c", "STATUS.md"), "w", encoding="utf-8") as f:
        f.write(status_a)  # exact duplicate of dom-a -> must be deduped
    memory = os.path.join(root, "MEMORY.md")
    with open(memory, "w", encoding="utf-8") as f:
        f.write("# MEMORY\n\n## People\n\n- **WIDGET FACT:** the user prefers widget reports in teal.\n")
    goals = os.path.join(ws, "goals")
    with open(os.path.join(goals, "goal-alpha", "GOAL.md"), "w", encoding="utf-8") as f:
        f.write("# Sell Widgets\n\nGoal ID: goal_9999\n\n## Description\nSell the widget kit locally. "
                "Price for the widget kit is $77 exactly.\n")
    with open(os.path.join(goals, "goal-alpha", "STATUS.md"), "w", encoding="utf-8") as f:
        f.write("# STATUS — Widget Goal\n\n- **State:** widget goal is at 7 of 9 steps done.\n")
    with open(os.path.join(goals, "goal-beta", "GOAL.md"), "w", encoding="utf-8") as f:
        f.write("# Beta Goal\n\nBeta goal tracks the purple flange inventory weekly.\n")
    return {"claims": claims, "inbox": inbox, "spine": spine, "memory": memory,
            "ws": ws, "goals": goals}


def build_index(root, fx):
    retrieval_index.CLAIMS = fx["claims"]
    retrieval_index.INBOX = fx["inbox"]
    retrieval_index.SPINE_DB = fx["spine"]
    retrieval_index.MEMORY = fx["memory"]
    retrieval_index.WORKSPACE = fx["ws"]
    retrieval_index.GOALS_DIR = fx["goals"]
    out = os.path.join(root, "index")
    return retrieval_index.build(out), out


def run_query(index_dir, *args):
    r = subprocess.run([sys.executable, QUERY, *args, "--index-dir", index_dir],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def directory_inventory(root, excluded_dirs=()):
    excluded = {os.path.abspath(p) for p in excluded_dirs}
    inventory = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if os.path.abspath(os.path.join(dirpath, d)) not in excluded]
        for name in filenames:
            path = os.path.join(dirpath, name)
            inventory[os.path.relpath(path, root)] = sha(path)
    return inventory


class TestPortedPilot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pai-retrieval-test-")
        self.fx = make_fixtures(self.tmp)
        self.manifest, self.out = build_index(self.tmp, self.fx)
        with open(os.path.join(self.out, "retrieval_index.jsonl"), encoding="utf-8") as f:
            self.records = [json.loads(l) for l in f if l.strip()]

    # ---- pilot test 1: kinds/counts (+ contract fields, + F4 counts)
    def test_kinds_and_counts(self):
        by = self.manifest["by_kind"]
        self.assertEqual(by["claim"], 4)          # 3 admitted-file + 1 inbox
        self.assertEqual(by["task"], 1)           # UNTRACKED excluded
        self.assertEqual(by["goal"], 3)           # tiny files index as ONE record each (<=600 chars)
        self.assertGreaterEqual(by["status"], 2)
        self.assertGreaterEqual(by["memory"], 1)
        src = [s for s in self.manifest["sources"] if s["path"] == self.fx["spine"]][0]
        self.assertEqual(src["excluded_untracked"], 2)
        for r in self.records:
            self.assertIn(":", r["id"])                       # namespaced ID
            self.assertTrue(r["source_anchor"])               # provenance anchor
            self.assertIn(r["lifecycle"],
                          ("unadmitted", "admitted", "invalidated", "superseded", "expired"))
            self.assertIn(r["privacy"], ("house", "private", "secret-pointer"))
            self.assertTrue(r["namespace"])

    # ---- pilot test 2: inbox flagged unadmitted, hidden by default
    def test_inbox_flagged_unadmitted(self):
        inbox_recs = [r for r in self.records if r["kind"] == "claim" and r["lifecycle"] == "unadmitted"]
        self.assertEqual(len(inbox_recs), 1)
        out = run_query(self.out, "unadmitted widget rumor", "--include-unadmitted")
        self.assertIn("rumor", out)
        out_default = run_query(self.out, "unadmitted widget rumor")
        self.assertNotIn("rumor", out_default)
        payload = json.loads(run_query(self.out, "unadmitted widget rumor", "--json", "--full"))
        reasons = {e["id"]: e["reason"] for e in payload["excluded"]}
        self.assertEqual(reasons.get("claim-register:C-REVIEW-UNADMITTED"), "STATE_CANDIDATE")

    # ---- pilot blocker-3 regression: unadmitted claim-ID lookup needs opt-in
    def test_unadmitted_claim_id_lookup_requires_opt_in(self):
        out = run_query(self.out, "--claim", "C-REVIEW-UNADMITTED", "--json")
        self.assertEqual(json.loads(out)["results"], [])
        out = run_query(self.out, "--claim", "C-REVIEW-UNADMITTED", "--json",
                        "--include-unadmitted")
        results = json.loads(out)["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["i"], "claim-register:C-REVIEW-UNADMITTED")

    # ---- pilot test 4: invalidated excluded unless asked (now via the gate)
    def test_invalidated_claim_excluded_unless_asked(self):
        payload = json.loads(run_query(self.out, "purple anodized flange", "--json", "--full"))
        ids = [r.get("claim_id") for r in payload["results"]]
        self.assertNotIn("C-9002", ids)
        reasons = {e["id"]: e["reason"] for e in payload["excluded"]}
        self.assertEqual(reasons.get("claim-register:C-9002"), "STATE_REVOKED")
        payload = json.loads(run_query(self.out, "purple anodized flange", "--json", "--full",
                                       "--history"))
        ids = [r.get("claim_id") for r in payload["results"]]
        self.assertIn("C-9002", ids)
        out = run_query(self.out, "--claim", "C-9002")
        self.assertIn("INVALIDATED", out)

    # ---- new (KR state gate): superseded excluded by default
    def test_superseded_claim_excluded_unless_history(self):
        payload = json.loads(run_query(self.out, "widget throughput", "--json", "--full"))
        ids = [r.get("claim_id") for r in payload["results"]]
        self.assertNotIn("C-9003", ids)
        reasons = {e["id"]: e["reason"] for e in payload["excluded"]}
        self.assertEqual(reasons.get("claim-register:C-9003"), "STATE_SUPERSEDED")
        payload = json.loads(run_query(self.out, "widget throughput", "--json", "--full",
                                       "--history"))
        ids = [r.get("claim_id") for r in payload["results"]]
        self.assertIn("C-9003", ids)

    # ---- pilot test 5: STATUS dedup by content hash (+ goals own their STATUS)
    def test_status_dedup_by_content_hash(self):
        self.assertEqual(self.manifest["status_dedup"]["files_seen"], 3)
        self.assertEqual(self.manifest["status_dedup"]["unique_contents"], 2)
        self.assertEqual(len(self.manifest["status_dedup"]["duplicates"]), 1)
        status_paths = {r["source_path"] for r in self.records if r["kind"] == "status"}
        self.assertNotIn(os.path.join(self.fx["ws"], "dom-c", "STATUS.md"), status_paths)
        alpha_status = os.path.join(self.fx["goals"], "goal-alpha", "STATUS.md")
        self.assertNotIn(alpha_status, status_paths)  # owned by the goal indexer
        goal_paths = {r["source_path"] for r in self.records if r["kind"] == "goal"}
        self.assertIn(alpha_status, goal_paths)

    # ---- pilot test 6: determinism modulo timestamp
    def test_determinism_modulo_timestamp(self):
        out2 = os.path.join(self.tmp, "index2")
        retrieval_index.build(out2)

        def norm(p):
            recs = []
            with open(p, encoding="utf-8") as f:
                for l in f:
                    d = json.loads(l)
                    d.pop("indexed_at")
                    recs.append(json.dumps(d, sort_keys=True, ensure_ascii=False))
            return recs
        self.assertEqual(norm(os.path.join(self.out, "retrieval_index.jsonl")),
                         norm(os.path.join(out2, "retrieval_index.jsonl")))

    # ---- pilot test 7: BM25 ranks relevant first
    def test_bm25_ranks_relevant_first(self):
        payload = json.loads(run_query(self.out, "purple anodized flange", "--json", "--full"))
        res = payload["results"]
        self.assertTrue(res)
        self.assertIn("purple anodized flange", res[0]["text"])

    # ---- pilot test 8: exact claim lookup (namespaced ID, valid_at from register)
    def test_claim_lookup_exact(self):
        payload = json.loads(run_query(self.out, "--claim", "C-9001", "--json", "--full"))
        res = payload["results"]
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id"], "claim-register:C-9001")
        self.assertIn("42 units per week", res[0]["text"])
        self.assertEqual(res[0]["freshness"], "FRESH")
        self.assertEqual(res[0]["valid_at"], "2026-11-01")
        self.assertEqual(res[0]["source_system"], "claim-register")

    # ---- pilot test 9: STALE gate flags exactly the modified source
    def test_stale_gate_flags_exactly_the_modified_source(self):
        with open(self.fx["claims"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "ADMIT", "claim": {
                "id": "C-9004", "entity": "Widget Domain", "type": "STATUS", "status": "current",
                "claim": "Late edit after indexing."}}) + "\n")
        payload = json.loads(run_query(self.out, "--claim", "C-9001", "--json", "--full"))
        self.assertEqual(payload["stale_sources"], [self.fx["claims"]])
        self.assertEqual(payload["results"][0]["freshness"], "STALE")
        # free-text path: claims records are gated out as STALE; memory stays FRESH
        payload2 = json.loads(run_query(self.out, "teal", "--json", "--full"))
        self.assertEqual(payload2["stale_sources"], [self.fx["claims"]])
        mem = [r for r in payload2["results"] if r["kind"] == "memory"]
        self.assertTrue(mem and all(r["freshness"] == "FRESH" for r in mem))
        claim_excl = [e for e in payload2["excluded"] if e["reason"] == "STALE"]
        self.assertTrue(claim_excl)

    # ---- pilot blocker-1 regression: WAL-only change trips the gate
    def test_spine_wal_only_change_trips_stale_gate(self):
        root = os.path.join(self.tmp, "wal-case")
        fx = make_fixtures(root)
        con = sqlite3.connect(fx["spine"])
        self.assertEqual(con.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        con.close()
        _manifest, out = build_index(root, fx)
        main_before = sha(fx["spine"])

        writer = sqlite3.connect(fx["spine"])
        try:
            self.assertEqual(writer.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            writer.execute("UPDATE tasks SET title=? WHERE task_id=?",
                           ("WAL-only updated widget task", "t-3"))
            writer.commit()
            self.assertTrue(os.path.exists(fx["spine"] + "-wal"))
            self.assertEqual(sha(fx["spine"]), main_before)
            payload = json.loads(run_query(out, "--kind", "task", "--json", "--full"))
        finally:
            writer.close()
        self.assertIn(fx["spine"], payload["stale_sources"])
        task_excl = [e for e in payload["excluded"] if e["id"] == "vm-spine:t-3"]
        self.assertEqual(len(task_excl), 1)
        self.assertEqual(task_excl[0]["reason"], "STALE")
        self.assertEqual([r for r in payload["results"] if r["kind"] == "task"], [])

    # ---- pilot blocker-2 regression: no files created in source directories
    def test_index_and_query_create_no_files_in_source_directories(self):
        root = os.path.join(self.tmp, "confinement-case")
        fx = make_fixtures(root)
        out = os.path.join(root, "index")
        before = directory_inventory(root, excluded_dirs=(out,))
        _manifest, built_out = build_index(root, fx)
        self.assertEqual(built_out, out)
        after_index = directory_inventory(root, excluded_dirs=(out,))
        self.assertEqual(before, after_index)
        run_query(out, "widget throughput", "--json")
        run_query(out, "--kind", "task", "--json")
        run_query(out, "--kind", "goal", "--json")
        after_query = directory_inventory(root, excluded_dirs=(out,))
        self.assertEqual(before, after_query)

    # ---- pilot test 12: querying never modifies a source
    def test_query_never_modifies_sources(self):
        before = {k: sha(v) for k, v in self.fx.items() if k not in ("ws", "goals")}
        run_query(self.out, "widget throughput")
        run_query(self.out, "--claim", "C-9002")
        after = {k: sha(v) for k, v in self.fx.items() if k not in ("ws", "goals")}
        self.assertEqual(before, after)


class TestPhase2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pai-retrieval-p2-")
        self.fx = make_fixtures(self.tmp)
        self.manifest, self.out = build_index(self.tmp, self.fx)
        with open(os.path.join(self.out, "retrieval_index.jsonl"), encoding="utf-8") as f:
            self.records = [json.loads(l) for l in f if l.strip()]

    # ---- F4: goal records carry goal identity and are retrievable
    def test_goal_sources_first_class(self):
        goal_recs = [r for r in self.records if r["kind"] == "goal"]
        self.assertTrue(goal_recs)
        self.assertTrue(all(r["goal_slug"] in ("goal-alpha", "goal-beta") for r in goal_recs))
        alpha = [r for r in goal_recs if r["goal_slug"] == "goal-alpha"]
        self.assertTrue(all(r["goal_id"] == "goal_9999" for r in alpha))
        self.assertTrue(all(r["source_system"] == "goal-workspaces" for r in goal_recs))
        payload = json.loads(run_query(self.out, "widget kit $77", "--json"))
        kinds = {r["k"] for r in payload["results"]}
        self.assertIn("goal", kinds)
        self.assertTrue(any("$77" in r["s"] for r in payload["results"]))

    # ---- F2: snippet mode is bounded, keeps the evidence, beats full mode
    def test_snippet_mode_bounded_and_evidential(self):
        long_status = os.path.join(self.fx["ws"], "dom-a", "STATUS.md")
        filler = ("Routine calibration note for the widget line with ordinary words "
                  "about schedules and staffing and maintenance windows. ") * 6
        with open(long_status, "w", encoding="utf-8") as f:
            f.write("# STATUS — Widget Domain\n\n- **Long note:** " + filler +
                    "The secret gold phrase is ZIRCON-42 for the widget line. " + filler + "\n")
        _m, out = build_index(self.tmp, self.fx)
        snip = run_query(out, "ZIRCON-42 widget", "--json", "--limit", "3")
        payload = json.loads(snip)
        self.assertTrue(payload["results"])
        self.assertTrue(any("ZIRCON-42" in r["s"] for r in payload["results"]))
        for r in payload["results"]:
            self.assertLessEqual(len(r["s"]), 900)  # F2 hard cap
        full = run_query(out, "ZIRCON-42 widget", "--json", "--full", "--limit", "2")
        self.assertLess(retrieval_query.est_tokens(snip), retrieval_query.est_tokens(full))

    # ---- F2: snippet path beats reading the whole small file (Codex F2 note)
    def test_snippet_beats_small_file_old_path(self):
        small = os.path.join(self.fx["ws"], "dom-b", "STATUS.md")
        content = ("# STATUS — Other Domain\n\n"
                   "- **Flange note:** the purple anodized flange is load bearing.\n"
                   "- **Torque:** the quixotic flange torque is 14 Nm exactly, set with a calibrated wrench.\n"
                   "- **Schedule:** flange inspections run every second Tuesday of the month.\n"
                   "- **Stock:** twelve spare flanges sit in bin seven of the north warehouse rack.\n"
                   "- **History:** the flange design dates from the original 2019 widget prototype run.\n"
                   "- **Owner:** the flange paperwork lives with the operations lead in building two.\n"
                   "- **Vendor:** replacement flanges ship from the Dayton foundry with a two week lead.\n"
                   "- **Finish:** the anodized coat is rated for outdoor exposure in coastal climates.\n"
                   "- **Testing:** every flange batch passes a dye penetrant check before it is shelved.\n"
                   "- **Docs:** the flange torque sheet is pinned above the assembly bench in bay three.\n")
        with open(small, "w", encoding="utf-8") as f:
            f.write(content)
        _m, out = build_index(self.tmp, self.fx)
        old_tokens = retrieval_query.est_tokens(content)
        payload_text = run_query(out, "quixotic flange torque", "--json", "--limit", "1")
        new_tokens = retrieval_query.est_tokens(payload_text)
        self.assertLess(new_tokens, old_tokens)
        self.assertIn("14 Nm", json.loads(payload_text)["results"][0]["s"])

    # ---- validity gate: domain applicability (KR PROJECT/DOMAIN order)
    def test_gate_domain_mismatch(self):
        payload = json.loads(run_query(self.out, "throughput", "--json", "--full",
                                       "--domain", "Other Domain"))
        ids = [r.get("claim_id") for r in payload["results"]]
        self.assertNotIn("C-9001", ids)  # Widget Domain record
        reasons = {e["id"]: e["reason"] for e in payload["excluded"]}
        self.assertEqual(reasons.get("claim-register:C-9001"), "DOMAIN_MISMATCH")

    def test_gate_project_mismatch(self):
        payload = json.loads(run_query(self.out, "throughput", "--json", "--full",
                                       "--project", "OTHER"))
        self.assertEqual(payload["results"], [])
        self.assertTrue(any(e["reason"] == "PROJECT_MISMATCH" for e in payload["excluded"]))

    # ---- validity unit-level: KR applicability + counterevidence + budget
    def test_validity_unit_rules(self):
        ctx = {"project_id": "PAI", "domain": None, "environment": None, "release": None}
        rec = {"lifecycle": "admitted", "domain": "GLOBAL", "validity_project": "PAI",
               "validity_environments": ["HOME"], "evidence_against": []}
        self.assertEqual(validity.gate(rec, ctx, "FRESH"), "ENVIRONMENT_REQUIRED")
        ctx2 = dict(ctx, environment="MSI")
        self.assertEqual(validity.gate(rec, ctx2, "FRESH"), "ENVIRONMENT_MISMATCH")
        ctx3 = dict(ctx, environment="HOME")
        self.assertIsNone(validity.gate(rec, ctx3, "FRESH"))
        rec_ce = dict(rec, evidence_against=["counterexample:1"])
        self.assertEqual(validity.gate(rec_ce, ctx3, "FRESH"), "COUNTEREVIDENCE_PRESENT")
        rec_rel = {"lifecycle": "admitted", "domain": "GLOBAL", "validity_project": "PAI",
                   "validity_releases": ["R2"], "evidence_against": []}
        self.assertEqual(validity.gate(rec_rel, ctx, "FRESH"), "RELEASE_REQUIRED")
        # gate order: state before freshness before counterevidence
        dead = dict(rec, lifecycle="invalidated")
        self.assertEqual(validity.gate(dead, ctx, "STALE"), "STATE_REVOKED")
        self.assertEqual(validity.gate(rec, ctx3, "INVALID_FRESHNESS"), "INVALID_FRESHNESS")
        with self.assertRaises(validity.BudgetInvalid):
            validity.check_budget(0)
        with self.assertRaises(validity.BudgetInvalid):
            validity.check_budget(33)
        self.assertEqual(validity.check_budget(32), 32)

    def test_budget_cli_rejects_out_of_range(self):
        r = subprocess.run([sys.executable, QUERY, "x", "--limit", "40",
                            "--index-dir", self.out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("KNOWLEDGE_BUDGET_INVALID", r.stderr)

    # ---- freshness INVALID_FRESHNESS branch (fingerprint failure)
    def test_freshness_invalid_on_fingerprint_error(self):
        manifest = {"sources": [{"path": self.fx["spine"], "kind": "task",
                                 "freshness_mode": "sqlite-content-v1",
                                 "content_sha256": "0" * 64, "sha256": "0" * 64}]}
        orig = retrieval_query._sqlite_content_fingerprint
        retrieval_query._sqlite_content_fingerprint = lambda p, d: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            states = retrieval_query.freshness(manifest, self.out)
        finally:
            retrieval_query._sqlite_content_fingerprint = orig
        self.assertEqual(states[self.fx["spine"]], "INVALID_FRESHNESS")

    # ---- identity contract rule 6 + KR ACTIVE-evidence rule: orphan
    # records are dropped + counted. Fix round 1 (Codex Phase 2 review
    # blocker 3): the anchor must actually RESOLVE — the pre-fix version
    # of this test accepted a nonexistent path, encoding the hole.
    def test_orphan_rule(self):
        records, orphans = [], []
        retrieval_index.admit(records, {"id": "x:1", "source_path": "", "source_anchor": ""}, orphans)
        self.assertEqual(records, [])
        self.assertEqual(orphans, ["x:1"])
        retrieval_index.admit(records, {"id": "x:2", "source_path": "/nonexistent/p",
                                        "source_anchor": "line 1"}, orphans)
        self.assertEqual(records, [])
        self.assertEqual(orphans, ["x:1", "x:2"])
        real = self.fx["claims"]  # exists, a handful of lines
        retrieval_index.admit(records, {"id": "x:3", "source_path": real,
                                        "source_anchor": "line 999999"}, orphans)
        self.assertEqual(records, [])
        self.assertEqual(orphans, ["x:1", "x:2", "x:3"])
        retrieval_index.admit(records, {"id": "x:4", "source_path": real,
                                        "source_anchor": "line 1"}, orphans)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], "x:4")


class TestFixRound1(unittest.TestCase):
    """Regressions for the 8 blockers in CODEX_REVIEW_PHASE2_2026-11-05.
    Each test reproduces the reviewer's own probe shape."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pai-retrieval-fix1-")
        self.fx = make_fixtures(self.tmp)

    def build(self):
        manifest, out = build_index(self.tmp, self.fx)
        with open(os.path.join(out, "retrieval_index.jsonl"), encoding="utf-8") as f:
            records = [json.loads(l) for l in f if l.strip()]
        return manifest, out, records

    def rewrite(self, path, lines):
        with open(path, "w", encoding="utf-8") as f:
            for obj in lines:
                f.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")

    # ---- blocker 1: terminal-state inbox record stays unadmitted
    def test_blocker1_inbox_superseded_id_lookup(self):
        with open(self.fx["inbox"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "C-PROBE-INBOX-SUPERSEDED", "entity": "Widget Domain",
                                "claim": "inbox secret candidate content",
                                "superseded_by": "C-9001"}) + "\n")
        _m, out, records = self.build()
        rec = [r for r in records if r.get("claim_id") == "C-PROBE-INBOX-SUPERSEDED"][0]
        self.assertEqual(rec["lifecycle"], "superseded")
        self.assertIs(rec["admitted"], False)
        payload = json.loads(run_query(out, "--claim", "C-PROBE-INBOX-SUPERSEDED", "--json"))
        self.assertEqual(payload["results"], [])
        payload = json.loads(run_query(out, "--claim", "C-PROBE-INBOX-SUPERSEDED",
                                       "--json", "--include-unadmitted"))
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["lc"], "superseded")
        self.assertIs(payload["results"][0]["adm"], False)
        # --history alone must NOT surface unadmitted material either
        out_text = run_query(out, "inbox secret candidate", "--history")
        self.assertNotIn("inbox secret candidate content", out_text)

    # ---- blocker 1/5: snippet JSON carries lifecycle/admission/privacy/namespace
    def test_blocker1_snippet_json_labels(self):
        _m, out, _r = self.build()
        payload = json.loads(run_query(out, "widget throughput", "--json"))
        claim_entries = [r for r in payload["results"] if r["k"] == "claim"]
        self.assertTrue(claim_entries)
        for e in claim_entries:
            self.assertEqual(e["lc"], "admitted")
            self.assertIs(e["adm"], True)
            self.assertEqual(e["p"], "house")
            self.assertEqual(e["ns"], "room:decisions")
        payload = json.loads(run_query(out, "unadmitted widget rumor", "--json",
                                       "--include-unadmitted"))
        inbox_entries = [r for r in payload["results"]
                         if r["i"] == "claim-register:C-REVIEW-UNADMITTED"]
        self.assertEqual(len(inbox_entries), 1)
        self.assertEqual(inbox_entries[0]["lc"], "unadmitted")
        self.assertIs(inbox_entries[0]["adm"], False)

    # ---- blocker 2: --include-unadmitted waives ONLY the state stage
    def test_blocker2_opt_in_waives_only_state(self):
        with open(self.fx["inbox"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "C-PROBE-BYPASS", "entity": "Widget Domain",
                                "claim": "bypass probe needle content",
                                "evidence_against": ["counterexample:1"]}) + "\n")
        _m, out, _r = self.build()
        # counterevidence still excludes it, opt-in notwithstanding
        payload = json.loads(run_query(out, "bypass probe needle", "--json", "--full",
                                       "--include-unadmitted"))
        self.assertNotIn("C-PROBE-BYPASS", [r.get("claim_id") for r in payload["results"]])
        reasons = {e["id"]: e["reason"] for e in payload["excluded"]}
        self.assertEqual(reasons.get("claim-register:C-PROBE-BYPASS"),
                         "COUNTEREVIDENCE_PRESENT")
        # applicability still excludes it under a mismatching domain
        payload = json.loads(run_query(out, "bypass probe needle", "--json", "--full",
                                       "--include-unadmitted", "--domain", "Other Domain"))
        self.assertNotIn("C-PROBE-BYPASS", [r.get("claim_id") for r in payload["results"]])
        reasons = {e["id"]: e["reason"] for e in payload["excluded"]}
        self.assertEqual(reasons.get("claim-register:C-PROBE-BYPASS"), "DOMAIN_MISMATCH")
        # freshness still excludes it once its source changes after indexing
        with open(self.fx["inbox"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "C-PROBE-LATE", "entity": "Widget Domain",
                                "claim": "late inbox line"}) + "\n")
        payload = json.loads(run_query(out, "bypass probe needle", "--json", "--full",
                                       "--include-unadmitted"))
        self.assertNotIn("C-PROBE-BYPASS", [r.get("claim_id") for r in payload["results"]])
        reasons = {e["id"]: e["reason"] for e in payload["excluded"]}
        self.assertEqual(reasons.get("claim-register:C-PROBE-BYPASS"), "STALE")

    # ---- blocker 4: salience tie-break (KR sort: score, salience, id)
    def test_blocker4_salience_tie_break(self):
        self.rewrite(self.fx["claims"], [
            {"event": "ADMIT", "claim": {
                "id": "C-AAA-LOW", "entity": "Widget Domain", "type": "STATUS",
                "status": "current", "salience": 0.1,
                "claim": "Identical salience probe statement for tie break."}},
            {"event": "ADMIT", "claim": {
                "id": "C-ZZZ-HIGH", "entity": "Widget Domain", "type": "STATUS",
                "status": "current", "salience": 0.9,
                "claim": "Identical salience probe statement for tie break."}},
        ])
        _m, out, _r = self.build()
        payload = json.loads(run_query(out, "identical salience probe statement",
                                       "--json", "--full"))
        ids = [r.get("claim_id") for r in payload["results"]]
        self.assertEqual(ids[:2], ["C-ZZZ-HIGH", "C-AAA-LOW"])

    # ---- blocker 4: the gate reads validity_domains
    def test_blocker4_validity_domains_gate(self):
        rec = {"lifecycle": "admitted", "domain": "GLOBAL", "validity_project": "PAI",
               "validity_domains": ["RESTRICTED"], "validity_environments": [],
               "validity_releases": [], "evidence_against": []}
        ctx = {"project_id": "PAI", "domain": "OTHER", "environment": None, "release": None}
        self.assertEqual(validity.gate(rec, ctx, "FRESH"), "DOMAIN_MISMATCH")
        ctx_ok = dict(ctx, domain="RESTRICTED")
        self.assertIsNone(validity.gate(rec, ctx_ok, "FRESH"))

    # ---- blocker 4: zero-overlap records are reported LOW_RELEVANCE
    def test_blocker4_zero_overlap_reported(self):
        _m, out, _r = self.build()
        payload = json.loads(run_query(out, "xyzzynotpresentanywhere", "--json"))
        self.assertEqual(payload["results"], [])
        self.assertGreaterEqual(payload["excluded_reasons"].get("LOW_RELEVANCE", 0), 5)
        self.assertGreaterEqual(payload["excluded_reasons"].get("STATE_CANDIDATE", 0), 1)

    # ---- blocker 4 boundary: unknown lifecycle is not silently ACTIVE
    def test_blocker4_unknown_lifecycle_excluded(self):
        rec = {"lifecycle": "half-baked", "domain": "GLOBAL", "validity_project": "PAI",
               "evidence_against": []}
        ctx = {"project_id": "PAI", "domain": None, "environment": None, "release": None}
        self.assertEqual(validity.gate(rec, ctx, "FRESH"), "STATE_UNKNOWN")

    # ---- blocker 5: privacy propagates; secret-pointer content never surfaces
    def test_blocker5_privacy_and_secret_pointer(self):
        with open(self.fx["claims"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "ADMIT", "claim": {
                "id": "C-PRIV", "entity": "Widget Domain", "type": "STATUS",
                "status": "current", "privacy": "private",
                "claim": "Private sentinel plum content for the widget domain."}}) + "\n")
            f.write(json.dumps({"event": "ADMIT", "claim": {
                "id": "C-SECR", "entity": "Widget Domain", "type": "STATUS",
                "status": "current", "privacy": "secret-pointer",
                "pointer": "vault:widget/master-key",
                "claim": "SECRET-SENTINEL-TEXT-xyz must never surface"}}) + "\n")
        _m, out, records = self.build()
        priv = [r for r in records if r.get("claim_id") == "C-PRIV"][0]
        self.assertEqual(priv["privacy"], "private")
        secr = [r for r in records if r.get("claim_id") == "C-SECR"][0]
        self.assertEqual(secr["privacy"], "secret-pointer")
        self.assertEqual(secr["text"], "vault:widget/master-key")
        self.assertNotIn("SECRET-SENTINEL-TEXT-xyz", json.dumps(records))
        payload = json.loads(run_query(out, "private sentinel plum", "--json"))
        entries = [r for r in payload["results"] if r["i"] == "claim-register:C-PRIV"]
        self.assertEqual(entries[0]["p"], "private")
        for args in (("--claim", "C-SECR", "--json", "--full"),
                     ("--claim", "C-SECR"),
                     ("widget", "--json", "--full")):
            self.assertNotIn("SECRET-SENTINEL-TEXT-xyz", run_query(out, *args))
        payload = json.loads(run_query(out, "--claim", "C-SECR", "--json", "--full"))
        self.assertEqual(payload["results"][0]["secret_pointer"], "vault:widget/master-key")

    # ---- blocker 6: forget leaves a tombstone, content unretrievable
    def test_blocker6_forget_tombstone(self):
        self.rewrite(self.fx["claims"], [
            {"event": "ADMIT", "claim": {
                "id": "C-FORGET", "entity": "Widget Domain", "type": "STATUS",
                "status": "current",
                "claim": "FORGET-PROBE-OLD-CONTENT with unique forgettable words."}},
            {"event": "INVALIDATE", "id": "C-FORGET", "reason": "forget",
             "actor": "review-probe", "at": "2026-11-05T00:00:00+00:00"},
        ])
        _m, out, records = self.build()
        rec = [r for r in records if r.get("claim_id") == "C-FORGET"][0]
        self.assertEqual(rec["text"], "")
        self.assertIs(rec["forgotten"], True)
        self.assertEqual(rec["forget_actor"], "review-probe")
        self.assertEqual(rec["forget_at"], "2026-11-05T00:00:00+00:00")
        self.assertEqual(rec["invalid_at"], "2026-11-05T00:00:00+00:00")
        self.assertNotIn("FORGET-PROBE-OLD-CONTENT", json.dumps(records))
        payload = json.loads(run_query(out, "--claim", "C-FORGET", "--json", "--full"))
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["text"], "")
        self.assertIs(payload["results"][0]["forgotten"], True)
        out_text = run_query(out, "forgettable words")
        self.assertNotIn("FORGET-PROBE-OLD-CONTENT", out_text)

    # ---- blocker 6 residual (fix round 2): the DEFAULT snippet JSON
    # representation must carry the tombstone fields too — round 1
    # emitted them in text and --full JSON only, so `--claim --json`
    # returned an empty invalidated entry that could not communicate
    # the forget (re-review probe B6: b6-id-json vs b6-id-json-full).
    def test_blocker6_forget_tombstone_snippet_json(self):
        self.rewrite(self.fx["claims"], [
            {"event": "ADMIT", "claim": {
                "id": "C-FORGET", "entity": "Widget Domain", "type": "STATUS",
                "status": "current",
                "claim": "FORGET-PROBE-OLD-CONTENT with unique forgettable words."}},
            {"event": "INVALIDATE", "id": "C-FORGET", "reason": "forget",
             "actor": "review-probe", "at": "2026-11-05T00:00:00+00:00"},
        ])
        _m, out, _records = self.build()
        raw = run_query(out, "--claim", "C-FORGET", "--json")
        self.assertNotIn("FORGET-PROBE-OLD-CONTENT", raw)
        payload = json.loads(raw)
        entries = [r for r in payload["results"]
                   if r["i"] == "claim-register:C-FORGET"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["s"], "")
        self.assertIs(entry["forgotten"], True)
        self.assertEqual(entry["forget_at"], "2026-11-05T00:00:00+00:00")
        self.assertEqual(entry["forget_actor"], "review-probe")

    # ---- blocker 7: a blank line must not re-key a markdown record
    def test_blocker7_stable_id_blank_line(self):
        status_path = os.path.join(self.fx["ws"], "dom-a", "STATUS.md")
        filler = ("- **Filler note:** routine widget line bookkeeping entry "
                  "with ordinary operational words and no signal. \n") * 8
        with open(status_path, "w", encoding="utf-8") as f:
            f.write("# STATUS — Widget Domain\n\n" + filler +
                    "- **Throughput locked:** widget line runs 42 units weekly, verified on disk.\n")
        _m, out, records = self.build()
        target = [r for r in records if r["kind"] == "status"
                  and "Throughput locked" in r["text"]][0]
        with open(status_path, encoding="utf-8") as f:
            body = f.read()
        with open(status_path, "w", encoding="utf-8") as f:
            f.write("\n" + body)
        out2 = os.path.join(self.tmp, "index2")
        retrieval_index.build(out2)
        with open(os.path.join(out2, "retrieval_index.jsonl"), encoding="utf-8") as f:
            records2 = [json.loads(l) for l in f if l.strip()]
        target2 = [r for r in records2 if r["content_hash"] == target["content_hash"]
                   and r["kind"] == "status"][0]
        self.assertEqual(target2["id"], target["id"])
        self.assertNotEqual(target2["source_anchor"], target["source_anchor"])

    # ---- blocker 8: INVALIDATE `at` lands in invalid_at; declared
    # lifecycle/invalid_at are honored
    def test_blocker8_lifecycle_timestamps(self):
        self.rewrite(self.fx["claims"], [
            {"event": "ADMIT", "claim": {
                "id": "C-0253", "entity": "Probe", "type": "STATE", "status": "current",
                "claim": "Probe claim invalidated by a later event."}},
            {"event": "INVALIDATE", "id": "C-0253", "by": "C-0257",
             "at": "2026-11-04T12:21:27+00:00"},
            {"event": "ADMIT", "claim": {
                "id": "C-EXP", "entity": "Probe", "type": "STATE", "status": "current",
                "lifecycle": "expired", "invalid_at": "2026-11-01T00:00:00+00:00",
                "claim": "Probe claim that arrived already expired."}},
        ])
        _m, out, records = self.build()
        c253 = [r for r in records if r.get("claim_id") == "C-0253"][0]
        self.assertEqual(c253["lifecycle"], "invalidated")
        self.assertEqual(c253["invalid_at"], "2026-11-04T12:21:27+00:00")
        self.assertEqual(c253["invalidated_by"], "C-0257")
        cexp = [r for r in records if r.get("claim_id") == "C-EXP"][0]
        self.assertEqual(cexp["lifecycle"], "expired")
        self.assertEqual(cexp["invalid_at"], "2026-11-01T00:00:00+00:00")
        payload = json.loads(run_query(out, "arrived already expired", "--json", "--full"))
        self.assertNotIn("C-EXP", [r.get("claim_id") for r in payload["results"]])
        reasons = {e["id"]: e["reason"] for e in payload["excluded"]}
        self.assertEqual(reasons.get("claim-register:C-EXP"), "STATE_ARCHIVED")


class TestFixRound2EvalRunner(unittest.TestCase):
    """Fix round 2, extra (a) discharged: the stock eval runner must
    complete on a mirrored/partial workspace — a question whose old-path
    baseline exists nowhere is UNRESOLVED-SOURCE (excluded from token
    accounting, named), never a crash; --source-root maps the canonical
    workspace root onto a local mirror. These tests pin the runner's
    resolution helpers directly (the re-review's stock run died at Q10
    on exactly this)."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = os.path.join(HERE, "..", "..", "..",
                            "evals", "retrieval", "run_eval.py")
        spec = importlib.util.spec_from_file_location("run_eval", path)
        cls.run_eval = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.run_eval)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pai-eval-runner-")

    def test_source_root_maps_canonical_workspace_path(self):
        re_ = self.run_eval
        mirror = os.path.join(self.tmp, "mirror")
        target = os.path.join(mirror, "some-domain", "STATUS.md")
        os.makedirs(os.path.dirname(target))
        with open(target, "w", encoding="utf-8") as f:
            f.write("mirror copy\n")
        canonical = "/home/hatch/workspace/some-domain/STATUS.md"
        if os.path.exists(canonical):
            self.skipTest("canonical fixture path unexpectedly exists")
        self.assertEqual(re_.resolve_old_path(canonical, mirror), target)
        self.assertEqual(re_.unresolved_files([canonical], mirror), [])
        self.assertEqual(
            re_.old_path_tokens([canonical], mirror),
            re_.est_tokens("mirror copy\n"))

    def test_unresolved_source_named_not_raised(self):
        re_ = self.run_eval
        ghost = "/home/hatch/workspace/no-such-domain-xyz/STATUS.md"
        if os.path.exists(ghost):
            self.skipTest("ghost fixture path unexpectedly exists")
        # No mirror: unresolvable, returned unchanged, and reported by
        # unresolved_files — the exact signal main() turns into a
        # per-question UNRESOLVED-SOURCE row instead of RuntimeError.
        self.assertEqual(re_.resolve_old_path(ghost), ghost)
        self.assertEqual(re_.resolve_old_path(ghost, self.tmp), ghost)
        self.assertEqual(re_.unresolved_files([ghost]), [ghost])
        self.assertEqual(re_.unresolved_files([ghost], self.tmp), [ghost])


if __name__ == "__main__":
    unittest.main(verbosity=2)
