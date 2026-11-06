#!/usr/bin/env python3
"""Tests for the Phase 4 Slice 2 pack assembler (pack.py).

Everything runs on FIXTURE-LOCAL state built in temp directories,
following the test_read_api.py Fixture pattern: a scratch registry
written through the production Registrar's append path, a fixture
claims.jsonl read through a staged copy of the canonical claimreg
module, and a fixture spine SQLite DB opened read-only. Pack room
manifests live in a temp room directory. No test touches the live
registry, claims, spine, or any production store.

Covers dossier §5 Slice 2 acceptance, as expanded for this build:
  Fixture A (unknown member + forgotten member + ordinary members):
    whole serve DENIED on the unknown member, the denial names the
    exclusion, the forgotten member is tombstone-only and its
    former level string appears NOWHERE in the serialized output.
  Fixture B (private member above the consumer + forgotten member
    + entitled members + a home-runloop pointer member): entitled
    sections served, exclusions named, pointer carries structure +
    level with NO body, forgotten member tombstone-only.
  (iii) cursor resume after a source hash change fails STALE.
  (iv)  oversize section is bounded, marked, cursored, in-budget.
  (v)   serve-time recomputation: a privacy edit after assembly
        governs the next serve WITHOUT reassembly.
  (vi)  budgets are counted before assembly completes: the version
        plan already records the section as bounded/truncated.

Run: python3 -m unittest test_pack -v   (from this directory)
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
import registrar as R  # noqa: E402
import read_api as A  # noqa: E402
import pack as P  # noqa: E402
import ledger as L  # noqa: E402

AT = "2026-11-06T09:00:00-08:00"
EV = "sha256:" + "c" * 64 + "@2026-11-06T08:59:00-08:00"
ACTOR = "pack-test"
FORGET_AT = "2026-11-06T08:30:00+00:00"

HOUSE_CONSUMER = {"identity": "lane:test-house", "max_level": "house"}
TOP_CONSUMER = {"identity": "lane:test-top",
                "max_level": "secret-pointer"}


def mint(cab="cab-0001"):
    return {"type": "MINT", "cabinet_id": cab, "at": AT,
            "actor": ACTOR, "reason": "new-work-area"}


def link(cab, system, mid, kind, relation="primary"):
    return {"type": "LINK", "cabinet_id": cab, "at": AT, "actor": ACTOR,
            "member": {"system": system, "id": mid, "kind": kind},
            "relation": relation, "evidence": EV,
            "reason": "title-citation"}


def claim(cid, text=None, **kw):
    d = {"id": cid, "claim": text or f"fixture claim {cid}",
         "entity": "Fixture", "source": "fixture:1",
         "status": "current", "type": "STATUS"}
    d.update(kw)
    return d


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reg = os.path.join(self.tmp.name, "REGISTRY.jsonl")
        self.head = R.GENESIS_HASH
        self.claims_log = os.path.join(self.tmp.name, "claims.jsonl")
        self.spine_db = os.path.join(self.tmp.name, "spine.db")
        self.room = os.path.join(self.tmp.name, "room")
        self.claimreg_copy = os.path.join(self.tmp.name,
                                          "claimreg_copy.py")
        canonical = A._resolve_claimreg_path()
        if not os.path.isfile(canonical):
            self.skipTest(
                f"canonical claimreg module unavailable at {canonical}")
        shutil.copyfile(canonical, self.claimreg_copy)

    # ------------------------------------------------ fixture stores

    def append(self, cands):
        out = R.append_events(self.reg, cands, self.head)
        self.head = out["head"]
        return out

    def write_claims(self, claims, extra_events=()):
        with open(self.claims_log, "w", encoding="utf-8", newline="") as f:
            for c in claims:
                f.write(json.dumps(
                    {"event": "ADMIT", "at": "2026-11-06T08:00:00+00:00",
                     "writer": ACTOR, "claim": c}) + "\n")
            for ev in extra_events:
                f.write(json.dumps(ev) + "\n")

    def write_spine(self, rows):
        if os.path.exists(self.spine_db):
            os.unlink(self.spine_db)
        conn = sqlite3.connect(self.spine_db)
        conn.execute(
            "CREATE TABLE tasks (task_id TEXT, title TEXT, state TEXT,"
            " program TEXT, owner_surface TEXT, registration_class TEXT,"
            " created_at TEXT, closed_at TEXT, deadline_at TEXT)")
        conn.executemany(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()

    def api_factory(self):
        """A FRESH ReadAPI per call — the live-semantics wiring
        (pack.py flag F-4: one cached instance cannot observe
        later edits to the fixture stores)."""
        def make():
            return A.ReadAPI(registry_path=self.reg,
                             claims_log_path=self.claims_log,
                             spine_db_path=self.spine_db,
                             claimreg_path=self.claimreg_copy)
        return make

    def assembler(self, **kw):
        kw.setdefault("api_factory", self.api_factory())
        return P.PackAssembler(self.room, **kw)

    # ------------------------------------------------ shared cabinets

    def build_fixture_a(self):
        """cab-0001: C-A001 house (ordinary) · C-A002 forgotten
        (former level secret-pointer) · C-A003 unknown (present but
        invalid explicit privacy field)."""
        self.write_claims(
            [claim("C-A001"),
             claim("C-A002", privacy="secret-pointer"),
             claim("C-A003", privacy="not-a-level")],
            extra_events=[{"event": "INVALIDATE", "id": "C-A002",
                           "reason": "forget", "at": FORGET_AT,
                           "actor": ACTOR}])
        self.write_spine([])
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-A001",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-A002",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-A003",
                          "epistemic-claim")])

    def build_fixture_b(self):
        """cab-0002: C-B001 house · C-B002 private · C-B003
        forgotten (former secret-pointer) · home-runloop pointer ·
        vm-spine task (house)."""
        self.write_claims(
            [claim("C-B001"),
             claim("C-B002", privacy="private"),
             claim("C-B003", privacy="secret-pointer")],
            extra_events=[{"event": "INVALIDATE", "id": "C-B003",
                           "reason": "forget", "at": FORGET_AT,
                           "actor": ACTOR}])
        self.write_spine([("sp-b-001", "Fixture B task", "QUEUED",
                           "prog", "surface", "proxy",
                           "2026-11-02T00:00:00Z", None, None)])
        self.append([mint("cab-0002"),
                     link("cab-0002", "claim-register", "C-B001",
                          "epistemic-claim"),
                     link("cab-0002", "claim-register", "C-B002",
                          "epistemic-claim"),
                     link("cab-0002", "claim-register", "C-B003",
                          "epistemic-claim"),
                     link("cab-0002", "home-runloop", "wu-b-001",
                          "work-unit"),
                     link("cab-0002", "vm-spine", "sp-b-001",
                          "planning-task")])


# --------------------------------------------------------- Fixture A

class TestFixtureA(Fixture):
    def test_unknown_denies_whole_serve_forgotten_tombstone_only(self):
        self.build_fixture_a()
        asm = self.assembler()
        desc = asm.assemble("pack-a", cabinet_id="cab-0001",
                            purpose="fixture A pack", domain="system",
                            task_type="review", author=ACTOR,
                            created_at=AT)
        self.assertEqual(desc["version"], 1)
        # Even the most entitled consumer is denied: unknown means
        # NO read entitlement for the combined read (§1.2).
        out = asm.serve("pack-a", TOP_CONSUMER)
        self.assertEqual(out["status"], "denied")
        self.assertEqual(out["entitlement_result"], "denied")
        self.assertEqual(out["derived_level"], "unknown")
        self.assertEqual(out["sections"], [])
        named = {(e["system"], e["id"]) for e in out["exclusions"]}
        self.assertIn(("claim-register", "C-A003"), named)
        # The forgotten member appears tombstone-only: closed set,
        # no content, and its former level string NOWHERE.
        self.assertEqual(len(out["tombstones"]), 1)
        tomb = out["tombstones"][0]
        self.assertEqual(tomb["id"], "C-A002")
        self.assertTrue(tomb["forgotten"])
        self.assertLessEqual(set(tomb["tombstone"]),
                             {"system", "id", "forget_at", "actor"})
        blob = json.dumps(out, sort_keys=True)
        self.assertNotIn("secret-pointer", blob)
        self.assertNotIn("fixture claim C-A002", blob)
        self.assertNotIn("fixture claim C-A001", blob)  # denied: no body


# --------------------------------------------------------- Fixture B

class TestFixtureB(Fixture):
    def test_partial_serve_pointer_and_tombstone(self):
        self.build_fixture_b()
        asm = self.assembler()
        asm.assemble("pack-b", cabinet_id="cab-0002",
                     purpose="fixture B pack", domain="system",
                     task_type="review", author=ACTOR, created_at=AT)
        out = asm.serve("pack-b", HOUSE_CONSUMER)
        self.assertEqual(out["entitlement_result"],
                         "served_with_exclusions")
        # Derived level at serve time: strictest LIVE member
        # (private) — the forgotten secret-pointer never counts.
        self.assertEqual(out["derived_level"], "private")
        by_id = {s["id"]: s for s in out["sections"]}
        # Entitled content sections served with bodies.
        self.assertIn("fixture claim C-B001", by_id["C-B001"]["body"])
        self.assertEqual(by_id["sp-b-001"]["section_type"], "content")
        self.assertIn("Fixture B task", by_id["sp-b-001"]["body"])
        # The private member is excluded BY NAME, with no section.
        self.assertNotIn("C-B002", by_id)
        named = {(e["system"], e["id"]): e["reason"]
                 for e in out["exclusions"]}
        self.assertEqual(named[("claim-register", "C-B002")],
                         "above-consumer-entitlement")
        self.assertNotIn("fixture claim C-B002",
                         json.dumps(out, sort_keys=True))
        # Pointer section: structure + level, NO body content.
        ptr = by_id["wu-b-001"]
        self.assertEqual(ptr["section_type"], "pointer")
        self.assertEqual(ptr["level"], "house")
        self.assertIsNone(ptr["body"])
        self.assertEqual(ptr["structure"]["kind"], "work-unit")
        self.assertIn("cab-0002", ptr["structure"]["cabinets"])
        # Forgotten member: tombstone only, former level nowhere.
        self.assertEqual([t["id"] for t in out["tombstones"]],
                         ["C-B003"])
        blob = json.dumps(out, sort_keys=True)
        self.assertNotIn("secret-pointer", blob)
        self.assertNotIn("fixture claim C-B003", blob)
        # Freshness recorded per source, all FRESH.
        self.assertTrue(out["freshness"])
        self.assertTrue(all(f["status"] == "FRESH"
                            for f in out["freshness"]))
        # A top consumer is served in full (pointer stays a pointer).
        full = asm.serve("pack-b", TOP_CONSUMER)
        self.assertEqual(full["entitlement_result"], "served_full")
        self.assertIn("fixture claim C-B002",
                      {s["id"]: s for s in full["sections"]}
                      ["C-B002"]["body"])


# ------------------------------------------- oversize, cursor, budgets

class TestOversizeAndCursor(Fixture):
    BIG_TEXT = "BIGRECORD " + "x" * 5000

    def setUp(self):
        super().setUp()
        self.write_claims([claim("C-BIG", text=self.BIG_TEXT)])
        self.write_spine([])
        self.append([mint(), link("cab-0001", "claim-register",
                                   "C-BIG", "epistemic-claim")])
        self.asm = self.assembler()
        self.desc = self.asm.assemble(
            "pack-big", members=[("claim-register", "C-BIG")],
            purpose="oversize pack", domain="system",
            task_type="review", author=ACTOR, created_at=AT,
            budgets={"default": {"char_budget": 200,
                                 "token_budget": 50}})

    def test_vi_budget_counted_and_bounded_at_assembly(self):
        # (vi) The version plan — written before any serve — already
        # records the full counted size and the bounded verdict.
        plan = self.desc["sections"][0]
        self.assertGreater(plan["counted_chars"], 200)
        self.assertEqual(plan["counted_tokens"],
                         P.est_tokens("x" * plan["counted_chars"]))
        self.assertTrue(plan["truncated"])
        self.assertEqual(plan["char_budget"], 200)
        self.assertEqual(plan["token_budget"], 50)

    def test_iv_oversize_serve_is_bounded_marked_and_cursored(self):
        out = self.asm.serve("pack-big", HOUSE_CONSUMER)
        sec = out["sections"][0]
        self.assertTrue(sec["truncated"])
        self.assertIn("TRUNCATED", sec["body"])
        self.assertLessEqual(sec["served"]["chars"], 200)
        self.assertLessEqual(sec["served"]["bytes"], 200)
        self.assertLessEqual(sec["served"]["tokens"], 50)
        self.assertGreater(sec["counted"]["chars"], 200)
        self.assertIsNotNone(out["footer"]["continuation_cursor"])
        # Footer accounting keeps the two token fields separate.
        usage = out["footer"]["usage"]
        self.assertIsNone(usage["reported_tokens"])
        self.assertEqual(usage["estimated_tokens"]["estimator"],
                         "char/4")

    def test_resume_reconstructs_and_completes(self):
        out = self.asm.serve("pack-big", HOUSE_CONSUMER)
        cursor = out["footer"]["continuation_cursor"]
        parts = [out["sections"][0]["body"]]
        seen_cursors = set()
        while cursor is not None:
            self.assertNotIn(cursor, seen_cursors)
            seen_cursors.add(cursor)
            step = self.asm.resume(cursor, HOUSE_CONSUMER)
            parts.append(step["sections"][0]["body"])
            cursor = step["footer"]["continuation_cursor"]
        joined = "".join(p.replace(P.TRUNCATION_MARKER, "")
                         for p in parts)
        api = self.api_factory()()
        try:
            full = P.content_text_of(
                api.resolve("claim-register", "C-BIG")["content"])
        finally:
            api.close()
        self.assertEqual(joined, full)

    def test_iii_resume_after_source_hash_change_fails_stale(self):
        out = self.asm.serve("pack-big", HOUSE_CONSUMER)
        cursor = out["footer"]["continuation_cursor"]
        self.assertIsNotNone(cursor)
        # The source record changes after the cursor was issued.
        self.write_claims([claim("C-BIG",
                                 text="CHANGED " + "y" * 5000)])
        with self.assertRaises(P.StaleCursorError) as ctx:
            self.asm.resume(cursor, HOUSE_CONSUMER)
        self.assertIn("STALE", str(ctx.exception))
        self.assertIn("C-BIG", str(ctx.exception))

    def test_stale_source_is_named_not_served_as_current(self):
        self.asm.serve("pack-big", HOUSE_CONSUMER)
        self.write_claims([claim("C-BIG",
                                 text="CHANGED " + "y" * 5000)])
        out = self.asm.serve("pack-big", HOUSE_CONSUMER)
        self.assertEqual(out["sections"], [])
        fresh = {f["id"]: f["status"] for f in out["freshness"]}
        self.assertEqual(fresh["C-BIG"], "STALE")
        reasons = " ".join(e["reason"] for e in out["exclusions"])
        self.assertIn("STALE", reasons)
        self.assertNotIn("CHANGED", json.dumps(out, sort_keys=True))


# ------------------------------------------- serve-time recomputation

class TestServeTimeRecomputation(Fixture):
    def setUp(self):
        super().setUp()
        self.write_claims([claim("C-V001")])
        self.write_spine([])
        self.append([mint(), link("cab-0001", "claim-register",
                                   "C-V001", "epistemic-claim")])
        self.asm = self.assembler()
        self.asm.assemble("pack-v",
                          members=[("claim-register", "C-V001")],
                          purpose="recomputation pack", domain="system",
                          task_type="review", author=ACTOR,
                          created_at=AT)

    def _rewrite_privacy(self, value):
        kw = {} if value is ... else {"privacy": value}
        self.write_claims([claim("C-V001", **kw)])

    def test_v_privacy_edit_governs_without_reassembly(self):
        out1 = self.asm.serve("pack-v", HOUSE_CONSUMER)
        self.assertEqual(out1["entitlement_result"], "served_full")
        self.assertEqual(len(out1["sections"]), 1)
        # Edit the explicit privacy field in the fixture store.
        # NO reassembly happens after this line.
        self._rewrite_privacy("private")
        out2 = self.asm.serve("pack-v", HOUSE_CONSUMER)
        self.assertEqual(out2["derived_level"], "private")
        self.assertEqual(out2["entitlement_result"],
                         "served_with_exclusions")
        self.assertEqual(out2["sections"], [])
        self.assertEqual(out2["exclusions"][0]["reason"],
                         "above-consumer-entitlement")
        # The serve came from the assembly cache (same source-hash
        # set: privacy is not content) yet the re-check still ran —
        # a cached serve never skips entitlement (§1.4).
        self.assertEqual(out2["footer"]["cache"], "hit")
        # Escalate to an invalid field: level becomes unknown and
        # the whole serve flips to DENIED, still without reassembly.
        self._rewrite_privacy("not-a-level")
        out3 = self.asm.serve("pack-v", HOUSE_CONSUMER)
        self.assertEqual(out3["entitlement_result"], "denied")
        self.assertEqual(out3["derived_level"], "unknown")


# ------------------------------------------------------- versioning

class TestVersioning(Fixture):
    def setUp(self):
        super().setUp()
        self.write_claims([claim("C-V001"), claim("C-V002")])
        self.write_spine([])
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-V001",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-V002",
                          "epistemic-claim")])
        self.asm = self.assembler()

    def test_manifest_change_mints_new_version_and_supersedes(self):
        d1 = self.asm.assemble("pack-m",
                               members=[("claim-register", "C-V001")],
                               purpose="v-pack", domain="system",
                               task_type="review", author=ACTOR,
                               created_at=AT)
        self.assertEqual(d1["version"], 1)
        # Identical re-assembly mints nothing.
        again = self.asm.assemble("pack-m",
                                  members=[("claim-register", "C-V001")],
                                  purpose="v-pack", domain="system",
                                  task_type="review", author=ACTOR,
                                  created_at=AT)
        self.assertEqual(again["version"], 1)
        # A manifest change (member added) mints version 2 and
        # supersedes version 1 with invalid_at set.
        d2 = self.asm.assemble(
            "pack-m",
            members=[("claim-register", "C-V001"),
                     ("claim-register", "C-V002")],
            purpose="v-pack", domain="system", task_type="review",
            author=ACTOR, created_at=AT)
        self.assertEqual(d2["version"], 2)
        packs = self.asm._fold_manifest()
        v1 = packs["pack-m"]["versions"][1]
        self.assertIsNotNone(v1["invalid_at"])
        self.assertEqual(v1["superseded_by"], 2)
        # The manifest on disk is append-only JSONL events.
        with open(os.path.join(self.room, "manifest.jsonl"),
                  encoding="utf-8") as f:
            events = [json.loads(ln) for ln in f if ln.strip()]
        self.assertEqual([e["event"] for e in events],
                         ["assemble", "supersede", "assemble"])

    def test_retired_pack_stops_serving(self):
        self.asm.assemble("pack-m",
                          members=[("claim-register", "C-V001")],
                          purpose="v-pack", domain="system",
                          task_type="review", author=ACTOR,
                          created_at=AT)
        self.asm.retire("pack-m", at=AT)
        out = self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertEqual(out["entitlement_result"], "denied")
        self.assertEqual(out["denial_reason"], "pack-retired")


# ------------------------------------------------- Fix-1 round (review)

class TestFix1HashPublication(Fixture):
    def test_excluded_and_pointer_hashes_not_published(self):
        self.build_fixture_b()
        asm = self.assembler()
        desc = asm.assemble("pack-b", cabinet_id="cab-0002",
                            purpose="fixture B pack", domain="system",
                            task_type="review", author=ACTOR,
                            created_at=AT)
        hashes = {(s["system"], s["id"]): s["content_hash"]
                  for s in desc["sources"]}
        out = asm.serve("pack-b", HOUSE_CONSUMER)
        blob = json.dumps(out, sort_keys=True)
        # Excluded private member: its exact hash appears NOWHERE.
        self.assertNotIn(hashes[("claim-register", "C-B002")], blob)
        # Pointer-only member: no hash either.
        self.assertNotIn(hashes[("home-runloop", "wu-b-001")], blob)
        # Forgotten member: no hash either.
        self.assertNotIn(hashes[("claim-register", "C-B003")], blob)
        # Served members keep their hashes (contract rule 1).
        self.assertIn(hashes[("claim-register", "C-B001")], blob)
        # Header + freshness carry no hash fields for the excluded.
        hdr = {(s["system"], s["id"]): s
               for s in out["header"]["source_manifest"]}
        self.assertNotIn("content_hash", hdr[("claim-register", "C-B002")])
        self.assertIn("content_hash", hdr[("claim-register", "C-B001")])
        fresh = {(f["system"], f["id"]): f for f in out["freshness"]}
        self.assertNotIn("content_hash_current",
                         fresh[("claim-register", "C-B002")])
        self.assertNotIn("content_hash_at_assembly",
                         fresh[("claim-register", "C-B002")])
        # The internal room manifest FILE keeps every hash.
        with open(os.path.join(self.room, "manifest.jsonl"),
                  encoding="utf-8") as fh:
            self.assertIn(hashes[("claim-register", "C-B002")],
                          fh.read())


class TestFix1ResumeLifecycle(Fixture):
    def setUp(self):
        super().setUp()
        self.write_claims(
            [claim("C-BIG", text="BIGRECORD " + "x" * 5000),
             claim("C-S002")])
        self.write_spine([])
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-BIG",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-S002",
                          "epistemic-claim")])
        self.asm = self.assembler()
        self.asm.assemble(
            "pack-big", members=[("claim-register", "C-BIG")],
            purpose="oversize pack", domain="system",
            task_type="review", author=ACTOR, created_at=AT,
            budgets={"default": {"char_budget": 200,
                                 "token_budget": 50}})

    def _cursor(self):
        out = self.asm.serve("pack-big", HOUSE_CONSUMER)
        cursor = out["footer"]["continuation_cursor"]
        self.assertIsNotNone(cursor)
        return cursor

    def test_retire_then_resume_refused_no_content(self):
        cursor = self._cursor()
        self.asm.retire("pack-big", at=AT)
        with self.assertRaises(P.PackError) as ctx:
            self.asm.resume(cursor, HOUSE_CONSUMER)
        self.assertIn("RETIRED", str(ctx.exception))

    def test_supersede_then_resume_with_old_cursor_fails_stale(self):
        cursor = self._cursor()
        d2 = self.asm.assemble(
            "pack-big",
            members=[("claim-register", "C-BIG"),
                     ("claim-register", "C-S002")],
            purpose="oversize pack", domain="system",
            task_type="review", author=ACTOR, created_at=AT,
            budgets={"default": {"char_budget": 200,
                                 "token_budget": 50}})
        self.assertEqual(d2["version"], 2)
        with self.assertRaises(P.StaleCursorError) as ctx:
            self.asm.resume(cursor, HOUSE_CONSUMER)
        self.assertIn("STALE", str(ctx.exception))


class TestFix1DegenerateBudgets(Fixture):
    def setUp(self):
        super().setUp()
        self.write_claims(
            [claim("C-BIG", text="BIGRECORD " + "x" * 600)])
        self.write_spine([])
        self.append([mint(), link("cab-0001", "claim-register",
                                   "C-BIG", "epistemic-claim")])
        self.asm = self.assembler()

    def test_budget_10_fails_loudly_at_assembly_nothing_served(self):
        with self.assertRaises(P.PackBudgetError) as ctx:
            self.asm.assemble(
                "pack-tiny", members=[("claim-register", "C-BIG")],
                purpose="tiny budget pack", domain="system",
                task_type="review", author=ACTOR, created_at=AT,
                budgets={"default": {"char_budget": 10,
                                     "token_budget": 3}})
        self.assertIn("PackBudgetError", str(ctx.exception))
        with self.assertRaises(P.PackNotFoundError):
            self.asm.serve("pack-tiny", HOUSE_CONSUMER)

    def test_multi_resume_walk_advances_and_terminates(self):
        self.asm.assemble(
            "pack-walk", members=[("claim-register", "C-BIG")],
            purpose="walk pack", domain="system", task_type="review",
            author=ACTOR, created_at=AT,
            budgets={"default": {"char_budget": 60,
                                 "token_budget": 15}})
        out = self.asm.serve("pack-walk", HOUSE_CONSUMER)
        cursor = out["footer"]["continuation_cursor"]
        last_offset = P._decode_cursor(cursor)["offsets"][
            "claim-register:C-BIG"]
        steps = 0
        while cursor is not None:
            steps += 1
            self.assertLess(steps, 500, "resume walk did not terminate")
            step = self.asm.resume(cursor, HOUSE_CONSUMER)
            new_cursor = step["footer"]["continuation_cursor"]
            if new_cursor is not None:
                self.assertNotEqual(new_cursor, cursor)
                new_offset = P._decode_cursor(new_cursor)["offsets"][
                    "claim-register:C-BIG"]
                self.assertGreater(new_offset, last_offset)
                last_offset = new_offset
            cursor = new_cursor
        self.assertGreater(steps, 1)


class TestFix1SnapshotWiring(Fixture):
    def setUp(self):
        super().setUp()
        self.write_claims([claim("C-S001")])
        self.write_spine([])
        self.append([mint(), link("cab-0001", "claim-register",
                                   "C-S001", "epistemic-claim")])

    def test_instance_without_optin_raises(self):
        api = self.api_factory()()
        try:
            with self.assertRaises(P.PackError):
                P.PackAssembler(self.room, read_api=api)
        finally:
            api.close()

    def test_instance_with_optin_serves_labelled_snapshot_mode(self):
        api = self.api_factory()()
        try:
            asm = P.PackAssembler(self.room, read_api=api,
                                  snapshot_ok=True)
            asm.assemble("pack-s",
                         members=[("claim-register", "C-S001")],
                         purpose="snapshot pack", domain="system",
                         task_type="review", author=ACTOR,
                         created_at=AT)
            out = asm.serve("pack-s", HOUSE_CONSUMER)
            self.assertIs(out["snapshot_mode"], True)
            self.assertEqual(out["entitlement_result"], "served_full")
        finally:
            api.close()

    def test_factory_serve_is_not_snapshot_mode(self):
        asm = self.assembler()
        asm.assemble("pack-s", members=[("claim-register", "C-S001")],
                     purpose="factory pack", domain="system",
                     task_type="review", author=ACTOR, created_at=AT)
        out = asm.serve("pack-s", HOUSE_CONSUMER)
        self.assertIs(out["snapshot_mode"], False)


class TestFix1CacheFreshBody(Fixture):
    def test_cache_hit_body_and_labels_from_serve_time_recheck(self):
        self.write_claims([claim("C-C001", privacy="house")])
        self.write_spine([])
        self.append([mint(), link("cab-0001", "claim-register",
                                   "C-C001", "epistemic-claim")])
        asm = self.assembler()
        asm.assemble("pack-c", members=[("claim-register", "C-C001")],
                     purpose="cache pack", domain="system",
                     task_type="review", author=ACTOR, created_at=AT)
        out1 = asm.serve("pack-c", TOP_CONSUMER)
        self.assertIn('"privacy": "house"',
                      out1["sections"][0]["body"])
        # Privacy-only edit: content hash unchanged, so this serve
        # is a cache HIT — yet level, freshness and body must all
        # come from the serve-time re-check, not the cached body.
        self.write_claims([claim("C-C001", privacy="private")])
        out2 = asm.serve("pack-c", TOP_CONSUMER)
        self.assertEqual(out2["footer"]["cache"], "hit")
        sec = out2["sections"][0]
        self.assertEqual(sec["level"], "private")
        self.assertEqual(sec["freshness"], "FRESH")
        self.assertIn('"privacy": "private"', sec["body"])
        self.assertNotIn('"privacy": "house"', sec["body"])


class TestFix1AllForgotten(Fixture):
    def test_all_forgotten_serve_is_tombstone_posture_never_full(self):
        self.write_claims([claim("C-F001")])
        self.write_spine([])
        self.append([mint(), link("cab-0001", "claim-register",
                                   "C-F001", "epistemic-claim")])
        asm = self.assembler()
        asm.assemble("pack-f", members=[("claim-register", "C-F001")],
                     purpose="forget pack", domain="system",
                     task_type="review", author=ACTOR, created_at=AT)
        self.write_claims(
            [claim("C-F001")],
            extra_events=[{"event": "INVALIDATE", "id": "C-F001",
                           "reason": "forget", "at": FORGET_AT,
                           "actor": ACTOR}])
        out = asm.serve("pack-f", TOP_CONSUMER)
        self.assertEqual(out["status"], "denied")
        self.assertEqual(out["entitlement_result"], "denied")
        self.assertNotEqual(out["entitlement_result"], "served_full")
        self.assertEqual(out["derived_level"], "unknown")
        self.assertEqual(out["sections"], [])
        self.assertEqual([t["id"] for t in out["tombstones"]],
                         ["C-F001"])
        self.assertNotIn("fixture claim C-F001",
                         json.dumps(out, sort_keys=True))


class TestFix1AliasPointer(Fixture):
    def test_alias_member_serves_as_pointer_not_exclusion(self):
        self.write_claims([])
        self.write_spine([])
        asm = self.assembler()
        desc = asm.assemble(
            "pack-alias",
            members=[("home-claim-service", "svc-001")],
            purpose="alias pack", domain="system", task_type="review",
            author=ACTOR, created_at=AT)
        self.assertEqual(desc["sources"][0]["system"], "claim-service")
        out = asm.serve("pack-alias", HOUSE_CONSUMER)
        self.assertEqual(out["exclusions"], [])
        self.assertEqual(len(out["sections"]), 1)
        sec = out["sections"][0]
        self.assertEqual(sec["section_type"], "pointer")
        self.assertEqual(sec["system"], "claim-service")
        self.assertIsNone(sec["body"])
        self.assertEqual(sec["level"], "house")


class TestFix1ManifestChain(Fixture):
    def setUp(self):
        super().setUp()
        self.write_claims([claim("C-M001"), claim("C-M002")])
        self.write_spine([])
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-M001",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-M002",
                          "epistemic-claim")])
        self.asm = self.assembler()

    def _manifest_bytes(self):
        with open(os.path.join(self.room, "manifest.jsonl"),
                  "rb") as fh:
            return fh.read()

    def test_manifest_lines_carry_running_prev_hash_chain(self):
        self.asm.assemble("pack-m",
                          members=[("claim-register", "C-M001")],
                          purpose="chain-pack", domain="system",
                          task_type="review", author=ACTOR,
                          created_at=AT)
        self.asm.assemble(
            "pack-m",
            members=[("claim-register", "C-M001"),
                     ("claim-register", "C-M002")],
            purpose="chain-pack", domain="system",
            task_type="review", author=ACTOR, created_at=AT)
        lines = [ln for ln in self._manifest_bytes().split(b"\n") if ln]
        self.assertEqual(len(lines), 3)
        import hashlib as _hl
        events = [json.loads(ln) for ln in lines]
        self.assertEqual(events[0]["prev_hash"], P.GENESIS_HASH)
        for i in (1, 2):
            self.assertEqual(
                events[i]["prev_hash"],
                _hl.sha256(lines[i - 1]).hexdigest())

    def test_tampered_manifest_line_fails_loudly_naming_line(self):
        self.asm.assemble("pack-m",
                          members=[("claim-register", "C-M001")],
                          purpose="chain-pack", domain="system",
                          task_type="review", author=ACTOR,
                          created_at=AT)
        self.asm.assemble(
            "pack-m",
            members=[("claim-register", "C-M001"),
                     ("claim-register", "C-M002")],
            purpose="chain-pack", domain="system",
            task_type="review", author=ACTOR, created_at=AT)
        data = self._manifest_bytes()
        self.assertIn(b"chain-pack", data)
        tampered = data.replace(b"chain-pack", b"xhain-pack", 1)
        with open(os.path.join(self.room, "manifest.jsonl"),
                  "wb") as fh:
            fh.write(tampered)
        with self.assertRaises(P.PackError) as ctx:
            self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertIn("line 2", str(ctx.exception))


class TestSidecarHeadCommitment(Fixture):
    """Manifest head-commitment sidecar (Slice 2 sidecar fix,
    re-review probe P-J shapes): the prev_hash chain cannot
    authenticate the LAST line, so `manifest.jsonl.head.json`
    commits to {head_hash, line_count, last_event}, maintained by
    every append and verified on every load (ledger parity)."""

    def setUp(self):
        super().setUp()
        self.write_claims([claim("C-M001"), claim("C-M002")])
        self.write_spine([])
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-M001",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-M002",
                          "epistemic-claim")])
        self.asm = self.assembler()

    # ------------------------------------------------------------ helpers

    def _manifest_path(self):
        return os.path.join(self.room, "manifest.jsonl")

    def _sidecar_path(self):
        return os.path.join(self.room, "manifest.jsonl.head.json")

    def _raw_lines(self):
        with open(self._manifest_path(), "rb") as fh:
            return [ln for ln in fh.read().split(b"\n") if ln]

    def _write_lines(self, lines):
        with open(self._manifest_path(), "wb") as fh:
            for ln in lines:
                fh.write(ln + b"\n")

    def _sidecar(self):
        with open(self._sidecar_path(), encoding="utf-8") as fh:
            return json.load(fh)

    def _assemble_v1(self):
        return self.asm.assemble(
            "pack-m", members=[("claim-register", "C-M001")],
            purpose="sidecar-pack", domain="system",
            task_type="review", author=ACTOR, created_at=AT)

    def _edit_last_line(self, **changes):
        lines = self._raw_lines()
        ev = json.loads(lines[-1])
        ev.update(changes)
        lines[-1] = json.dumps(ev, ensure_ascii=False,
                               sort_keys=True).encode("utf-8")
        self._write_lines(lines)

    # -------------------------------------------------------------- tests

    def test_consistent_sidecar_matches_after_every_append(self):
        import hashlib as _hl
        self._assemble_v1()
        sc = self._sidecar()
        lines = self._raw_lines()
        self.assertEqual(sc["line_count"], 1)
        self.assertEqual(sc["head_hash"],
                         _hl.sha256(lines[-1]).hexdigest())
        self.assertEqual(sc["last_event"],
                         {"event": "assemble", "pack_id": "pack-m",
                          "version": 1})
        # Supersede + assemble appends advance the sidecar too.
        self.asm.assemble(
            "pack-m",
            members=[("claim-register", "C-M001"),
                     ("claim-register", "C-M002")],
            purpose="sidecar-pack", domain="system",
            task_type="review", author=ACTOR, created_at=AT)
        sc = self._sidecar()
        lines = self._raw_lines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(sc["line_count"], 3)
        self.assertEqual(sc["head_hash"],
                         _hl.sha256(lines[-1]).hexdigest())
        self.assertEqual(sc["last_event"]["event"], "assemble")
        self.assertEqual(sc["last_event"]["version"], 2)
        # Normal flows untouched under a consistent sidecar.
        out = self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertEqual(out["entitlement_result"], "served_full")
        # Retire appends advance the sidecar as well.
        self.asm.retire("pack-m", at=AT)
        sc = self._sidecar()
        lines = self._raw_lines()
        self.assertEqual(sc["line_count"], 4)
        self.assertEqual(sc["head_hash"],
                         _hl.sha256(lines[-1]).hexdigest())
        self.assertEqual(sc["last_event"]["event"], "retire")

    def test_tail_retire_pack_id_edit_fails_loudly(self):
        # P-J shape 1: [assemble, retire]; rewriting ONLY the last
        # line's pack_id used to void the retire silently and the
        # pack served content. Now the head commitment refuses.
        self._assemble_v1()
        self.asm.retire("pack-m", at=AT)
        control = self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertEqual(control["entitlement_result"], "denied")
        self._edit_last_line(pack_id="pack-other")
        with self.assertRaises(P.PackError) as ctx:
            self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertIn("head commitment", str(ctx.exception))

    def test_tail_assemble_purpose_edit_detected(self):
        # P-J shape 2: single assemble line; editing its purpose
        # used to be served back on the header undetected.
        self._assemble_v1()
        self._edit_last_line(purpose="TAMPERED-PURPOSE")
        with self.assertRaises(P.PackError) as ctx:
            self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertIn("head commitment", str(ctx.exception))

    def test_truncated_last_line_detected(self):
        self._assemble_v1()
        self.asm.assemble(
            "pack-m",
            members=[("claim-register", "C-M001"),
                     ("claim-register", "C-M002")],
            purpose="sidecar-pack", domain="system",
            task_type="review", author=ACTOR, created_at=AT)
        lines = self._raw_lines()
        self.assertEqual(len(lines), 3)
        self._write_lines(lines[:-1])  # truncate the last line away
        with self.assertRaises(P.PackError) as ctx:
            self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertIn("head commitment", str(ctx.exception))

    def test_missing_sidecar_on_nonempty_manifest_refused(self):
        self._assemble_v1()
        os.unlink(self._sidecar_path())
        with self.assertRaises(P.PackError) as ctx:
            self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertIn("head commitment missing",
                      str(ctx.exception))

    def test_corrupt_sidecar_refused(self):
        self._assemble_v1()
        with open(self._sidecar_path(), "w", encoding="utf-8", newline="") as fh:
            fh.write("{not json")
        with self.assertRaises(P.PackError) as ctx:
            self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertIn("head commitment", str(ctx.exception))

    def test_count_ahead_sidecar_refused(self):
        self._assemble_v1()
        sc = self._sidecar()
        sc["line_count"] += 1
        with open(self._sidecar_path(), "w", encoding="utf-8", newline="") as fh:
            json.dump(sc, fh)
        with self.assertRaises(P.PackError) as ctx:
            self.asm.serve("pack-m", HOUSE_CONSUMER)
        msg = str(ctx.exception)
        self.assertIn("head commitment mismatch", msg)
        self.assertIn("line_count 2", msg)  # expected (sidecar)
        self.assertIn("line_count 1", msg)  # actual (manifest)

    def test_crash_window_stale_prefix_sidecar_heals_and_serves(self):
        import hashlib as _hl
        self._assemble_v1()
        # Hand-append a VALID chained retire event, leaving the
        # sidecar at its exact prefix state (count 1) — the crash
        # window between manifest fsync and sidecar replace.
        lines = self._raw_lines()
        retire = {"event": "retire", "pack_id": "pack-m", "at": AT,
                  "prev_hash": _hl.sha256(lines[-1]).hexdigest()}
        with open(self._manifest_path(), "ab") as fh:
            fh.write((json.dumps(retire, ensure_ascii=False,
                                 sort_keys=True) + "\n").encode())
        self.assertEqual(self._sidecar()["line_count"], 1)
        # Load heals the sidecar and proceeds: the retire folds, so
        # serve returns its normal retired denial (not an error).
        out = self.asm.serve("pack-m", HOUSE_CONSUMER)
        self.assertEqual(out["entitlement_result"], "denied")
        self.assertEqual(out["denial_reason"], "pack-retired")
        sc = self._sidecar()
        lines = self._raw_lines()
        self.assertEqual(sc["line_count"], 2)
        self.assertEqual(sc["head_hash"],
                         _hl.sha256(lines[-1]).hexdigest())
        self.assertEqual(sc["last_event"]["event"], "retire")


# --------------------------------------------------------- ledger sink

class TestLedgerSink(Fixture):
    def test_serve_accounting_flows_through_optional_sink(self):
        self.build_fixture_b()
        sink_path = os.path.join(self.tmp.name, "usage-ledger.jsonl")
        sink = L.LedgerWriter(sink_path, "vm")
        asm = self.assembler(
            ledger_sink=sink,
            ledger_context={"host": "vm", "lane_id": "pack-test",
                            "run_id": "run-pack-test"})
        asm.assemble("pack-b", cabinet_id="cab-0002",
                     purpose="fixture B pack", domain="system",
                     task_type="review", author=ACTOR, created_at=AT)
        asm.serve("pack-b", HOUSE_CONSUMER)
        stream = L.read_stream(sink_path)
        self.assertEqual(stream["parse_errors"], {})
        self.assertEqual(L.verify_chain(stream["lines"],
                                        stream["events"]), [])
        types = [ev["event_type"] for ev in stream["events"]]
        self.assertEqual(types, ["assemble", "serve"])
        serve_ev = stream["events"][1]
        self.assertEqual(L.validate_event(serve_ev, stored=True), [])
        self.assertEqual(serve_ev["entitlement_result"],
                         "served_with_exclusions")
        self.assertEqual(serve_ev["derived_level"], "private")
        self.assertEqual(serve_ev["excluded"],
                         [{"system": "claim-register", "id": "C-B002"}])
        self.assertIsNone(serve_ev["brief_id"])
        self.assertTrue(serve_ev["unjoined_reason"])

    def test_no_sink_is_the_default_and_needs_no_ledger(self):
        self.build_fixture_b()
        asm = self.assembler()  # ledger_sink defaults to None
        asm.assemble("pack-b", cabinet_id="cab-0002",
                     purpose="fixture B pack", domain="system",
                     task_type="review", author=ACTOR, created_at=AT)
        out = asm.serve("pack-b", HOUSE_CONSUMER)
        self.assertEqual(out["status"], "partial")


if __name__ == "__main__":
    unittest.main()
