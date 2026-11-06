#!/usr/bin/env python3
"""Tests for the Phase 4 Slice 4 shadow instrumentation (shadow.py).

Everything is FIXTURE-LOCAL: temp codex-cp job dirs with synthetic
receipt.json + stdout.log, a temp pack room served through a
fixture cabinet (the test_pack.py pattern: scratch Registrar
registry + fixture claims + fixture spine, read via the production
read API), and temp ledger streams. No test touches MSI, the live
registry, receipts, or any production store.

Covers Slice 4 acceptance:
  - extraction parity with gate.py on the same fixture (identical
    figures, incl. cached input counted in full);
  - emitter events pass ledger.validate_event and fold in rollup;
  - hit path: fixture pack assembled in a temp room -> serve event
    joined to the brief;
  - miss path: fallback event with requested_key; a run with no
    brief carries brief_id null + a named unjoined_reason;
  - late accounting: the correction references the serve event_id
    and the raw serve row is BYTE-UNCHANGED after the join;
  - a brief with a receipt but no usage is named unjoined in the
    replay report, never zero-filled;
  - replay reconciliation: coverage, exact token reconciliation,
    rollup totals, and the gate.py correction-fold cross-check.

Run: python3 -m unittest test_shadow -v   (from this directory)
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
CTX = os.path.abspath(os.path.join(HERE, ".."))
CAB = os.path.abspath(os.path.join(HERE, "..", "..", "cabinet"))
for p in (CTX, CAB):
    if p not in sys.path:
        sys.path.insert(0, p)
import gate  # noqa: E402
import ledger as L  # noqa: E402
import rollup as R  # noqa: E402
import shadow as S  # noqa: E402

TS = "2026-11-06T12:00:00+00:00"


def write_job(jobs_dir, job_key, brief_id="drive-id-1", status="done",
              usage_events=(), started="2026-11-02T00:00:00Z",
              ended="2026-11-02T01:00:00Z"):
    job = os.path.join(jobs_dir, job_key)
    os.makedirs(job)
    with open(os.path.join(job, "receipt.json"), "w",
              encoding="utf-8") as f:
        json.dump({"job_key": job_key, "brief_id": brief_id,
                   "status": status, "started_at": started,
                   "ended_at": ended}, f)
    with open(os.path.join(job, "stdout.log"), "w",
              encoding="utf-8") as f:
        for u in usage_events:
            f.write(json.dumps({"type": "turn.completed",
                                "usage": u}) + "\n")
        f.write("not json at all\n")
        f.write(json.dumps({"type": "item.completed",
                            "usage": {"input_tokens": 999}}) + "\n")
    return job


def stored_events(path):
    stream = L.read_stream(path)
    assert not stream["parse_errors"], stream["parse_errors"]
    return stream["events"]


class TestExtractionParity(unittest.TestCase):
    def test_parity_with_gate_on_same_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = os.path.join(td, "jobs")
            write_job(jobs, "job-a-11111111", usage_events=[
                {"input_tokens": 1000, "output_tokens": 50,
                 "cached_input_tokens": 800},
                {"input_tokens": 500, "output_tokens": 25,
                 "cached_input_tokens": 500}])
            write_job(jobs, "job-b-22222222", usage_events=[
                {"input_tokens": 10, "output_tokens": 1,
                 "cached_input_tokens": 0}])
            write_job(jobs, "job-c-33333333", status="error",
                      usage_events=[{"input_tokens": 7,
                                     "output_tokens": 7,
                                     "cached_input_tokens": 0}])
            mine = {r["job_key"]: r
                    for r in S.records_from_source(jobs)}
            theirs = {r.job_key: r
                      for r in gate.load_receipt_dir(jobs)}
            self.assertEqual(set(mine), set(theirs))
            for key, rec in theirs.items():
                m = mine[key]
                self.assertEqual(m["status"], rec.status)
                self.assertEqual(m["reported_tokens"],
                                 rec.reported_tokens)
                self.assertEqual(m["input_tokens"], rec.input_tokens)
                self.assertEqual(m["output_tokens"], rec.output_tokens)
                self.assertEqual(m["cached_input_tokens"],
                                 rec.cached_input_tokens)
                self.assertEqual(m["turns"], rec.turns)
            # cached counted in full: total = input + output.
            self.assertEqual(mine["job-a-11111111"]["reported_tokens"],
                             1575)
            self.assertEqual(
                [r["job_key"] for r in S.finished_briefs(jobs)],
                ["job-a-11111111", "job-b-22222222"])

    def test_join_key_is_job_identity_not_receipt_brief_id(self):
        # Two re-runs of ONE Drive brief: same receipt brief_id,
        # distinct job_keys -> two distinct finished briefs/joins.
        with tempfile.TemporaryDirectory() as td:
            jobs = os.path.join(td, "jobs")
            for suffix in ("aaaaaaaa", "bbbbbbbb"):
                write_job(jobs, f"drive-doc-{suffix}",
                          brief_id="drive-doc",
                          usage_events=[{"input_tokens": 100,
                                         "output_tokens": 5,
                                         "cached_input_tokens": 0}])
            fin = S.finished_briefs(jobs)
            self.assertEqual(len(fin), 2)
            self.assertEqual({r["brief_id"] for r in fin},
                             {"drive-doc-aaaaaaaa",
                              "drive-doc-bbbbbbbb"})
            self.assertTrue(all(
                r["receipt_brief_id"] == "drive-doc" for r in fin))


class EmitterFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger_path = os.path.join(self.tmp.name, "usage.jsonl")

    def emitter(self, **kw):
        kw.setdefault("host", "msi")
        kw.setdefault("lane_id", "shadow-test-lane")
        return S.ShadowEmitter(self.ledger_path, **kw)


class TestEmitter(EmitterFixture):
    def test_miss_path_fallback_with_requested_key(self):
        em = self.emitter()
        out = em.emit_run("system", "review", brief_id="job-x-1",
                          run_id="run-1", ts=TS)
        self.assertEqual(out["event"]["event_type"], "fallback")
        self.assertEqual(out["event"]["outcome"], "miss")
        self.assertEqual(out["event"]["requested_key"],
                         {"domain": "system", "task_type": "review"})
        self.assertEqual(out["event"]["brief_id"], "job-x-1")
        self.assertEqual(L.validate_event(out["event"], stored=True),
                         [])
        # F3 summary shape on the miss path too.
        self.assertNotIn("serve_result", out)
        self.assertEqual(out["summary"]["outcome"], "miss")
        self.assertEqual(out["summary"]["event_id"],
                         out["event"]["event_id"])
        self.assertTrue(out["summary"]["brief_joined"])

    def test_run_without_brief_carries_named_unjoined_reason(self):
        em = self.emitter()
        out = em.emit_run("system", "review", run_id="run-2", ts=TS)
        self.assertIsNone(out["event"]["brief_id"])
        self.assertTrue(out["event"]["unjoined_reason"])
        self.assertEqual(L.validate_event(out["event"], stored=True),
                         [])

    def test_events_validate_and_rollup_folds(self):
        em = self.emitter()
        em.emit_run("system", "review", brief_id="job-x-1", ts=TS)
        em.emit_run("cmm", "fix", brief_id="job-x-2", ts=TS)
        for ev in stored_events(self.ledger_path):
            self.assertEqual(L.validate_event(ev, stored=True), [],
                             ev)
            # reported/estimated never mixed (contract rule 4)
            self.assertFalse("reported_tokens" in ev
                             and "estimated_tokens" in ev)
        summary = R.rollup([self.ledger_path])
        self.assertEqual(summary["streams"][0]["invalid_rows"], [])
        self.assertTrue(summary["streams"][0]["chain_ok"])
        self.assertEqual(summary["excluded_streams"], [])
        self.assertEqual(
            summary["gate_valid_totals"]["events"], 2)
        self.assertEqual(
            summary["gate_valid_totals"]["by_outcome"], {"miss": 2})


class TestLateAccounting(EmitterFixture):
    RECEIPT = {"brief_id": "job-late-1", "job_key": "job-late-1",
               "input_tokens": 2000, "output_tokens": 100,
               "cached_input_tokens": 300, "turns": 1}

    def test_correction_references_serve_and_row_bytes_unchanged(self):
        em = self.emitter()
        out = em.emit_run("system", "review", brief_id="job-late-1",
                          run_id="run-late", ts=TS)
        serve_id = out["event"]["event_id"]
        with open(self.ledger_path, "rb") as f:
            before = f.read()
        acc = em.join_receipt(serve_id, self.RECEIPT, ts=TS)
        self.assertIsNotNone(acc)
        self.assertEqual(acc["event_type"], "correction")
        self.assertEqual(acc["corrects_event_id"], serve_id)
        self.assertEqual(acc["corrects"]["target_event_id"], serve_id)
        # F2: the join correction carries the structured
        # discriminator kind="late_accounting".
        self.assertEqual(acc["corrects"]["kind"],
                         "late_accounting")
        self.assertEqual(
            acc["corrects"]["set"]["reported_tokens"],
            {"provider": "codex", "input": 2000, "output": 100,
             "cached_input": 300})
        with open(self.ledger_path, "rb") as f:
            after = f.read()
        # The raw serve row is byte-unchanged; the join is a new line.
        self.assertTrue(after.startswith(before))
        self.assertEqual(after.count(b"\n"), before.count(b"\n") + 1)
        # Both folds see the reported tokens on the serve event.
        summary = R.rollup([self.ledger_path])
        # F2: rollup surfaces the kind on the correction entry.
        self.assertEqual(summary["corrections"][0]["kind"],
                         "late_accounting")
        slot = summary["per_brief"]["job-late-1"]
        self.assertEqual(slot["reported"]["input"], 2000)
        self.assertEqual(slot["reported"]["output"], 100)
        folded, _ = gate.apply_corrections(
            gate.load_ledger_stream(self.ledger_path))
        rep = [s for s in folded if s.brief_id == "job-late-1"]
        self.assertEqual(len(rep), 1)
        self.assertEqual(rep[0].reported_tokens, 2100)

    def test_receipt_at_emit_time_accounts_immediately(self):
        em = self.emitter()
        out = em.emit_run("system", "review", brief_id="job-late-1",
                          receipt=self.RECEIPT, ts=TS)
        self.assertIsNotNone(out["accounting"])
        self.assertEqual(out["accounting"]["corrects_event_id"],
                         out["event"]["event_id"])
        # F2 + F3: emitted join carries kind, summary reflects it,
        # and the correction still applies (totals join as before).
        self.assertEqual(
            out["accounting"]["corrects"]["kind"],
            "late_accounting")
        self.assertNotIn("serve_result", out)
        self.assertTrue(out["summary"]["accounting_joined"])
        self.assertEqual(out["summary"]["accounting_event_id"],
                         out["accounting"]["event_id"])
        summary = R.rollup([self.ledger_path])
        self.assertEqual(summary["corrections"][0]["kind"],
                         "late_accounting")
        self.assertTrue(summary["corrections"][0]["applied"])
        self.assertEqual(
            summary["per_brief"]["job-late-1"]["reported"]
            ["input"], 2000)
        folded, _ = gate.apply_corrections(
            gate.load_ledger_stream(self.ledger_path))
        rep = [s for s in folded if s.brief_id == "job-late-1"]
        self.assertEqual(rep[0].reported_tokens, 2100)

    def test_join_pass_and_already_accounted(self):
        em = self.emitter()
        em.emit_run("system", "review", brief_id="job-late-1", ts=TS)
        first = em.join_pass([self.RECEIPT])
        self.assertEqual(first[0]["brief_id"], "job-late-1")
        self.assertIsNotNone(first[0]["accounting_event_id"])
        second = em.join_pass([self.RECEIPT])
        self.assertEqual(second[0]["accounting_event_id"],
                         "already_accounted")

    def test_no_usage_receipt_joins_nothing(self):
        em = self.emitter()
        out = em.emit_run("system", "review", brief_id="job-nousage",
                          receipt={"brief_id": "job-nousage",
                                   "input_tokens": 0, "output_tokens": 0,
                                   "cached_input_tokens": 0, "turns": 0},
                          ts=TS)
        self.assertIsNone(out["accounting"])
        self.assertEqual(out["unjoined_reason"], S.REASON_NO_USAGE)
        # Not zero-filled: the stream holds ONLY the fallback row.
        self.assertEqual(len(stored_events(self.ledger_path)), 1)


# ------------------------------------------------------- pack hit path

import pack as P  # noqa: E402
import registrar as Rg  # noqa: E402
import read_api as A  # noqa: E402

AT = "2026-11-06T09:00:00-08:00"
EV = "sha256:" + "c" * 64 + "@2026-11-06T08:59:00-08:00"
ACTOR = "shadow-test"


def _claim(cid, **kw):
    d = {"id": cid, "claim": f"fixture claim {cid}", "entity": "Fixture",
         "source": "fixture:1", "status": "current", "type": "STATUS"}
    d.update(kw)
    return d


class TestHitPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reg = os.path.join(self.tmp.name, "REGISTRY.jsonl")
        self.head = Rg.GENESIS_HASH
        self.claims_log = os.path.join(self.tmp.name, "claims.jsonl")
        self.spine_db = os.path.join(self.tmp.name, "spine.db")
        self.room = os.path.join(self.tmp.name, "room")
        self.claimreg_copy = os.path.join(self.tmp.name, "claimreg.py")
        canonical = A._resolve_claimreg_path()
        if not os.path.isfile(canonical):
            self.skipTest("canonical claimreg module unavailable")
        shutil.copyfile(canonical, self.claimreg_copy)
        with open(self.claims_log, "w", encoding="utf-8") as f:
            for c in (_claim("C-S001"), _claim("C-S002")):
                f.write(json.dumps(
                    {"event": "ADMIT", "at": "2026-11-06T08:00:00+00:00",
                     "writer": ACTOR, "claim": c}) + "\n")
        conn = sqlite3.connect(self.spine_db)
        conn.execute(
            "CREATE TABLE tasks (task_id TEXT, title TEXT, state TEXT,"
            " program TEXT, owner_surface TEXT, registration_class TEXT,"
            " created_at TEXT, closed_at TEXT, deadline_at TEXT)")
        conn.commit()
        conn.close()
        out = Rg.append_events(self.reg, [
            {"type": "MINT", "cabinet_id": "cab-9001", "at": AT,
             "actor": ACTOR, "reason": "new-work-area"},
            {"type": "LINK", "cabinet_id": "cab-9001", "at": AT,
             "actor": ACTOR,
             "member": {"system": "claim-register", "id": "C-S001",
                        "kind": "epistemic-claim"},
             "relation": "primary", "evidence": EV,
             "reason": "title-citation"},
            {"type": "LINK", "cabinet_id": "cab-9001", "at": AT,
             "actor": ACTOR,
             "member": {"system": "claim-register", "id": "C-S002",
                        "kind": "epistemic-claim"},
             "relation": "primary", "evidence": EV,
             "reason": "title-citation"}], self.head)
        self.head = out["head"]

    def api_factory(self):
        def make():
            return A.ReadAPI(registry_path=self.reg,
                             claims_log_path=self.claims_log,
                             spine_db_path=self.spine_db,
                             claimreg_path=self.claimreg_copy)
        return make

    def test_hit_path_serve_event_with_brief_join(self):
        asm = P.PackAssembler(self.room, api_factory=self.api_factory())
        asm.assemble("pack-shadow", cabinet_id="cab-9001",
                     purpose="shadow fixture", domain="system",
                     task_type="review", author=ACTOR, created_at=AT)
        ledger_path = os.path.join(self.tmp.name, "usage.jsonl")
        em = S.ShadowEmitter(
            ledger_path, "msi", "shadow-test-lane",
            pack_provider=S.PackAssemblerProvider(asm),
            consumer={"identity": "shadow-test-lane",
                      "max_level": "house"})
        # Capture a real body string from the fixture pack via a
        # direct serve (test-only) so the F3 scan below checks an
        # actual served body, not a guessed string.
        direct = asm.serve("pack-shadow",
                           {"identity": "shadow-test-lane",
                            "max_level": "house"})
        self.assertEqual(direct["status"], "served")
        bodies = [s["body"] for s in direct["sections"]
                  if s.get("body")]
        self.assertTrue(bodies)
        out = em.emit_run("system", "review", brief_id="job-hit-1",
                          run_id="run-hit", ts=TS)
        ev = out["event"]
        self.assertEqual(ev["event_type"], "serve")
        self.assertIn(ev["outcome"], ("hit", "cache_hit", "partial"))
        self.assertEqual(ev["brief_id"], "job-hit-1")
        self.assertEqual(ev["pack_id"], "pack-shadow")
        self.assertGreater(ev["context_tokens_served"], 0)
        self.assertEqual(ev["token_counter"], "char/4")
        self.assertNotIn("estimated_tokens", ev)
        self.assertEqual(L.validate_event(ev, stored=True), [])
        # F3: emit_run returns an ACCOUNTING SUMMARY only — no
        # serve_result, no section bodies anywhere in the return.
        self.assertNotIn("serve_result", out)
        summary = out["summary"]
        self.assertEqual(summary["event_id"], ev["event_id"])
        self.assertEqual(out["event_id"], ev["event_id"])
        self.assertEqual(summary["outcome"], ev["outcome"])
        self.assertEqual(out["outcome"], ev["outcome"])
        self.assertEqual(summary["entitlement_result"],
                         ev.get("entitlement_result"))
        self.assertEqual(summary["derived_level"],
                         ev.get("derived_level"))
        self.assertEqual(summary["context_tokens_served"],
                         ev["context_tokens_served"])
        self.assertEqual(
            out["context_tokens_served"],
            ev["context_tokens_served"])
        self.assertEqual(summary["brief_id"], "job-hit-1")
        self.assertTrue(summary["brief_joined"])
        self.assertTrue(out["brief_joined"])
        blob = json.dumps(out, ensure_ascii=False)
        for body in bodies:
            self.assertNotIn(body, blob)
        self.assertNotIn("fixture claim C-S001", blob)
        # A different key still misses honestly through the provider.
        miss = em.emit_run("system", "census", brief_id="job-hit-2",
                           run_id="run-miss", ts=TS)
        self.assertEqual(miss["event"]["event_type"], "fallback")


# ---------------------------------------------------------------- replay

def snapshot_job(name, status="done", started="2026-11-02T00:00:00Z",
                 ended="2026-11-02T01:00:00Z", inp=1000, out=50,
                 cached=800, turns=1):
    return {"name": name, "job_key": name,
            "brief_id": name.rsplit("-", 1)[0], "status": status,
            "started_at": started, "ended_at": ended,
            "input_tokens": inp, "output_tokens": out,
            "cached_input_tokens": cached, "turns": turns}


class TestReplay(unittest.TestCase):
    def test_replay_reconciles_and_names_no_usage_brief(self):
        with tempfile.TemporaryDirectory() as td:
            snap = os.path.join(td, "snap.json")
            jobs = [
                snapshot_job("lane-a-11111111"),
                snapshot_job("lane-b-22222222", inp=2000, out=100,
                             cached=0),
                snapshot_job("lane-c-33333333", inp=0, out=0, cached=0,
                             turns=0),  # done, receipt, NO usage
                snapshot_job("lane-d-44444444", status="error"),
            ]
            with open(snap, "w", encoding="utf-8") as f:
                json.dump({"source": "fixture", "jobs": jobs}, f)
            ledger_path = os.path.join(td, "replay.jsonl")
            report = S.replay(
                snap, ledger_path,
                windows=[("test", "2026-11-01T00:00:00Z",
                          "2026-11-03T00:00:00Z")])
            w = report["windows"][0]
            self.assertEqual(w["finished_briefs"], 3)
            self.assertEqual(w["joined"], 2)
            self.assertAlmostEqual(w["coverage"], 2 / 3, places=4)
            self.assertEqual(w["receipt_totals"]["total"], 3150)
            self.assertEqual(
                w["ledger_joined_reported_totals"]["total"], 3150)
            self.assertEqual(w["deltas_named"], [])
            self.assertTrue(report["overall"]["reconciliation_exact"])
            self.assertTrue(
                report["gate_fold_cross_check"]["matches_rollup"])
            # The no-usage brief is NAMED, with its reason — and the
            # stream carries no reported figure for it (not zeroed).
            self.assertEqual(len(w["unjoined_named"]), 1)
            self.assertEqual(w["unjoined_named"][0]["brief_id"],
                             "lane-c-33333333")
            self.assertIn("no_usage_events",
                          w["unjoined_named"][0]["reason"])
            summary = R.rollup([ledger_path])
            self.assertNotIn("lane-c-33333333",
                             {b for b, s in
                              summary["per_brief"].items()
                              if s["reported"]["events"]})
            for ev in stored_events(ledger_path):
                self.assertEqual(L.validate_event(ev, stored=True), [])

    def test_replay_refuses_existing_stream(self):
        with tempfile.TemporaryDirectory() as td:
            ledger_path = os.path.join(td, "replay.jsonl")
            with open(ledger_path, "w", encoding="utf-8") as f:
                f.write("{}\n")
            with self.assertRaises(ValueError):
                S.replay(os.path.join(td, "nope.json"), ledger_path)


if __name__ == "__main__":
    unittest.main()
