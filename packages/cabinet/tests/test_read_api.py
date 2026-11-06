#!/usr/bin/env python3
"""Tests for the Phase 3 Cabinet read API (read_api.py).

Everything runs on FIXTURE-LOCAL state built in temp directories: a
scratch registry (via the production Registrar's append path), a
fixture claims.jsonl (read through the live claimreg module with its
LOG pointed at the fixture), and a fixture spine SQLite DB opened
read-only. No test touches live store state, and no expectation is a
hardcoded live-registry constant (gap G8 discipline).

Run: python3 -m unittest test_read_api -v   (from this directory)
"""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)
import registrar as R  # noqa: E402
import read_api as A  # noqa: E402

AT = "2026-11-05T13:00:00-08:00"
EV = "sha256:" + "b" * 64 + "@2026-11-05T12:59:00-08:00"
ACTOR = "read-api-test"


def mint():
    return {"type": "MINT", "at": AT, "actor": ACTOR,
            "reason": "new-work-area"}


def link(cab, system, mid, kind, relation="primary"):
    return {"type": "LINK", "cabinet_id": cab, "at": AT, "actor": ACTOR,
            "member": {"system": system, "id": mid, "kind": kind},
            "relation": relation, "evidence": EV,
            "reason": "title-citation"}


def unlink(cab, system, mid, kind, corrects, reason="evidence-refuted",
           relation="primary"):
    return {"type": "UNLINK", "cabinet_id": cab, "at": AT, "actor": ACTOR,
            "member": {"system": system, "id": mid, "kind": kind},
            "relation": relation, "evidence": EV, "reason": reason,
            "corrects": str(corrects)}


def claim(cid, **kw):
    d = {"id": cid, "claim": f"fixture claim {cid}", "entity": "Fixture",
         "source": "fixture:1", "status": "current", "type": "STATUS"}
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

    def append(self, cands):
        out = R.append_events(self.reg, cands, self.head)
        self.head = out["head"]
        return out

    def write_claims(self, claims, extra_events=()):
        with open(self.claims_log, "w", encoding="utf-8") as f:
            for c in claims:
                f.write(json.dumps(
                    {"event": "ADMIT", "at": "2026-11-05T12:00:00+00:00",
                     "writer": ACTOR, "claim": c}) + "\n")
            for ev in extra_events:
                f.write(json.dumps(ev) + "\n")

    def write_spine(self, rows):
        conn = sqlite3.connect(self.spine_db)
        conn.execute(
            "CREATE TABLE tasks (task_id TEXT, title TEXT, state TEXT,"
            " program TEXT, owner_surface TEXT, registration_class TEXT,"
            " created_at TEXT, closed_at TEXT, deadline_at TEXT)")
        conn.executemany(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()

    def api(self, **kw):
        kw.setdefault("registry_path", self.reg)
        kw.setdefault("claims_log_path", self.claims_log)
        kw.setdefault("spine_db_path", self.spine_db)
        return A.ReadAPI(**kw)


class TestDefaultsAndContent(Fixture):
    def test_a_defaults_per_namespace(self):
        self.write_claims([claim("C-9001")])
        self.write_spine([("sp-fixture-1", "Fixture task", "QUEUED",
                           "prog", "surface", "proxy",
                           "2026-11-02T00:00:00Z", None, None)])
        self.append([mint(), link("cab-0001", "claim-register", "C-9001",
                                   "epistemic-claim")])
        self.append([mint(), link("cab-0002", "vm-spine", "sp-fixture-1",
                                   "planning-task")])
        self.append([mint(), link("cab-0003", "home-runloop", "wu-fixture:1",
                                   "work-unit")])
        self.append([mint(), link("cab-0004", "claim-service",
                                   "claim_fixture-0001", "execution-claim")])
        api = self.api()
        for system, mid in (("claim-register", "C-9001"),
                            ("vm-spine", "sp-fixture-1"),
                            ("home-runloop", "wu-fixture:1"),
                            ("claim-service", "claim_fixture-0001")):
            out = api.resolve(system, mid)
            self.assertEqual(out["effective_privacy"], "house", system)
            self.assertEqual(out["privacy_basis"], "namespace-default",
                             system)
            self.assertTrue(out["member"], system)
            self.assertEqual(
                out["cabinets"][0]["cabinet_derived_privacy"], "house",
                system)
        # Contract alias resolves to the same member.
        out = api.resolve("home-claim-service", "claim_fixture-0001")
        self.assertEqual(out["system"], "claim-service")
        self.assertEqual(out["namespace"], "home-claim-service")
        # Content: claims and spine tasks are served natively...
        self.assertEqual(api.resolve("claim-register", "C-9001")
                         ["content"]["id"], "C-9001")
        self.assertEqual(api.resolve("vm-spine", "sp-fixture-1")
                         ["content"]["title"], "Fixture task")
        # ...HOME members are registry-only, with the note saying so.
        out = api.resolve("home-runloop", "wu-fixture:1")
        self.assertIsNone(out["content"])
        self.assertIn("registry-only", out["content_note"])

    def test_b_explicit_stricter_wins(self):
        self.write_claims([claim("C-9002", privacy="private"),
                           claim("C-9005", privacy="secret-pointer"),
                           claim("C-9006")])
        self.append([mint(), link("cab-0001", "claim-register", "C-9002",
                                   "epistemic-claim")])
        self.append([mint(),
                     link("cab-0002", "claim-register", "C-9005",
                          "epistemic-claim"),
                     link("cab-0002", "claim-register", "C-9006",
                          "epistemic-claim")])
        api = self.api()
        out = api.resolve("claim-register", "C-9002")
        self.assertEqual(out["effective_privacy"], "private")
        self.assertEqual(out["privacy_basis"], "explicit")
        self.assertEqual(out["cabinets"][0]["cabinet_derived_privacy"],
                         "private")
        # Strictest member governs the combined entry.
        cab = api.cabinet("cab-0002")
        self.assertEqual(cab["derived_privacy"], "secret-pointer")
        self.assertTrue(cab["content_entitled"])

    def test_e_secondary_resolves_both_cabinets(self):
        self.write_claims([claim("C-9007")])
        self.append([mint(), link("cab-0001", "claim-register", "C-9007",
                                   "epistemic-claim")])
        self.append([mint(), link("cab-0002", "claim-register", "C-9007",
                                   "epistemic-claim",
                                   relation="secondary")])
        api = self.api()
        out = api.resolve("claim-register", "C-9007")
        by_cab = {c["cabinet_id"]: c["relation"] for c in out["cabinets"]}
        self.assertEqual(by_cab, {"cab-0001": "primary",
                                  "cab-0002": "secondary"})
        cab2 = api.cabinet("cab-0002")
        self.assertEqual(cab2["members"][0]["relation"], "secondary")
        listing = api.members("claim-register")
        self.assertEqual(listing["count"], 1)
        self.assertEqual(len(listing["members"][0]["cabinets"]), 2)


class TestEntitlementEnforcement(Fixture):
    def test_c_no_default_namespace_denied(self):
        self.write_claims([claim("C-9001"),
                           claim("C-9002", privacy="private")])
        self.write_spine([("sp-fixture-1", "Fixture task", "QUEUED",
                           "prog", "surface", "proxy",
                           "2026-11-02T00:00:00Z", None, None)])
        self.append([mint(), link("cab-0001", "vm-spine", "sp-fixture-1",
                                   "planning-task")])
        self.append([mint(), link("cab-0002", "claim-register", "C-9001",
                                   "epistemic-claim")])
        self.append([mint(), link("cab-0003", "claim-register", "C-9002",
                                   "epistemic-claim")])
        # A defaults map with NO namespace defaults at all: only an
        # explicit field can entitle a read.
        api = self.api(namespace_defaults={})
        out = api.resolve("vm-spine", "sp-fixture-1")
        self.assertEqual(out["effective_privacy"], "unknown")
        self.assertEqual(out["privacy_basis"], "none")
        self.assertIsNone(out["content"])
        self.assertEqual(out["content_excluded"], "unknown-privacy-level")
        out = api.resolve("claim-register", "C-9001")
        self.assertEqual(out["effective_privacy"], "unknown")
        self.assertIsNone(out["content"])
        # Explicit field still wins over a missing default.
        out = api.resolve("claim-register", "C-9002")
        self.assertEqual(out["effective_privacy"], "private")
        self.assertEqual(out["content"]["id"], "C-9002")
        # Cabinet structure still lists; combined content is denied.
        cab = api.cabinet("cab-0001")
        self.assertTrue(cab["found"])
        self.assertEqual(len(cab["members"]), 1)
        self.assertEqual(cab["derived_privacy"], "unknown")
        self.assertFalse(cab["content_entitled"])
        self.assertIsNone(cab["contents"])

    def test_d_forgotten_member_excluded(self):
        self.write_claims(
            [claim("C-9003"), claim("C-9004")],
            extra_events=[{"event": "INVALIDATE", "id": "C-9004",
                           "reason": "forget",
                           "at": "2026-11-05T12:30:00+00:00",
                           "actor": ACTOR}])
        # Line 1 MINT, line 2 LINK C-9003, line 3 LINK C-9004.
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-9003",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9004",
                          "epistemic-claim")])
        # Registry-side forget of C-9003 (forget-consequence UNLINK).
        self.append([unlink("cab-0001", "claim-register", "C-9003",
                            "epistemic-claim", 2,
                            reason="forget-consequence")])
        api = self.api()
        out = api.resolve("claim-register", "C-9003")
        self.assertTrue(out["forgotten"])
        self.assertIsNone(out["content"])
        self.assertEqual(out["content_excluded"], "forgotten")
        self.assertEqual(out["cabinets"], [])
        # C-9004 is still LINKed in the registry but forgotten in its
        # own ledger: tombstone wins, content never readable.
        out = api.resolve("claim-register", "C-9004")
        self.assertTrue(out["forgotten"])
        self.assertEqual(out["tombstone"]["id"], "C-9004")
        self.assertIsNone(out["content"])
        cab = api.cabinet("cab-0001")
        self.assertEqual(cab["members"], [])
        self.assertEqual([m["id"] for m in cab["purged_members"]],
                         ["C-9004"])
        self.assertIsNone(cab["contents"])

    def test_invalidated_claim_membership_without_content(self):
        self.write_claims(
            [claim("C-9008")],
            extra_events=[{"event": "INVALIDATE", "id": "C-9008",
                           "by": "C-9009",
                           "at": "2026-11-05T12:30:00+00:00"}])
        self.append([mint(), link("cab-0001", "claim-register", "C-9008",
                                   "epistemic-claim")])
        api = self.api()
        out = api.resolve("claim-register", "C-9008")
        self.assertTrue(out["member"])          # membership resolves
        self.assertFalse(out["forgotten"])      # ordinary INVALIDATE
        self.assertIsNone(out["content"])       # content does not serve
        self.assertEqual(out["content_excluded"],
                         "invalidated-not-retrievable-by-default")

    def test_read_only_stores_untouched(self):
        self.write_claims([claim("C-9001")])
        self.write_spine([("sp-fixture-1", "Fixture task", "QUEUED",
                           "prog", "surface", "proxy",
                           "2026-11-02T00:00:00Z", None, None)])
        self.append([mint(), link("cab-0001", "claim-register", "C-9001",
                                   "epistemic-claim"),
                     link("cab-0001", "vm-spine", "sp-fixture-1",
                          "planning-task")])

        def digest(path):
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        before = (digest(self.reg), digest(self.claims_log),
                  digest(self.spine_db))
        api = self.api()
        api.cabinets()
        api.cabinet("cab-0001")
        api.resolve("claim-register", "C-9001")
        api.resolve("vm-spine", "sp-fixture-1")
        api.members("claim-register")
        after = (digest(self.reg), digest(self.claims_log),
                 digest(self.spine_db))
        self.assertEqual(before, after)
        # And the module carries no write path at all.
        with open(os.path.join(PKG, "read_api.py"),
                  encoding="utf-8") as f:
            src = f.read()
        for token in ("append_events(", "forget_member(", "project(",
                      "admit_batch(", "mode=rw"):
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()
