#!/usr/bin/env python3
"""Tests for the production Cabinet Registrar tool (registrar.py).

All write tests run on SCRATCH registries in temp directories. The one
test that touches the accepted registry (projection parity) is strictly
read-only: it folds docs/cabinet-registry/REGISTRY.jsonl and compares a
rebuilt projection against the committed PROJECTION.json bytes.

Run: python3 -m unittest test_registrar -v   (from this directory)
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, PKG)
import registrar as R  # noqa: E402

AT = "2026-11-05T13:00:00-08:00"
EV = "sha256:" + "a" * 64 + "@2026-11-05T12:59:00-08:00"
ACTOR = "registrar-test"


def mint(cab=None, **kw):
    d = {"type": "MINT", "at": AT, "actor": ACTOR, "reason": "new-work-area"}
    if cab:
        d["cabinet_id"] = cab
    d.update(kw)
    return d


def link(cab, cid, rl_member="C-0001", relation="primary", **kw):
    d = {"type": "LINK", "cabinet_id": cab, "at": AT, "actor": ACTOR,
         "member": {"system": "claim-register", "id": rl_member,
                    "kind": "epistemic-claim"},
         "relation": relation, "evidence": EV, "reason": "title-citation"}
    d.update(kw)
    return d


def unlink(cab, corrects, cid="C-0001", relation="primary", **kw):
    d = {"type": "UNLINK", "cabinet_id": cab, "at": AT, "actor": ACTOR,
         "member": {"system": "claim-register", "id": cid,
                    "kind": "epistemic-claim"},
         "relation": relation, "evidence": EV, "reason": "evidence-refuted",
         "corrects": str(corrects)}
    d.update(kw)
    return d


class ScratchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reg = os.path.join(self.tmp.name, "REGISTRY.jsonl")

    def bytes_now(self):
        with open(self.reg, "rb") as f:
            return f.read()

    def genesis(self):
        """cab-0001 + LINK C-0001 (line 2) + LINK C-0002 (line 3)."""
        out = R.append_events(self.reg, [
            mint(),
            link("cab-0001", None, "C-0001"),
            link("cab-0001", None, "C-0002")], R.GENESIS_HASH)
        return out


class TestAppendDiscipline(ScratchCase):
    def test_genesis_append_and_prefix_preservation(self):
        out = self.genesis()
        self.assertEqual(out["appended"], 3)
        self.assertEqual(out["lines"], 3)
        prefix = self.bytes_now()
        out2 = R.append_events(self.reg, [link("cab-0001", None, "C-0003")],
                               out["head"])
        self.assertEqual(out2["first_new_line"], 4)
        self.assertTrue(self.bytes_now().startswith(prefix))
        lines, events = R.read_registry(self.reg)
        R.verify_chain(lines, events)
        state = R.fold_events(events)
        self.assertEqual(state["max_mint_seq"], 1)
        self.assertEqual(len(state["cabinets"]["cab-0001"]["members"]), 3)

    def test_allocation_from_greatest_mint_not_tail(self):
        out = self.genesis()  # tail is a LINK, greatest MINT is 1
        out2 = R.append_events(self.reg, [mint()], out["head"])
        lines, events = R.read_registry(self.reg)
        self.assertEqual(events[-1]["cabinet_id"], "cab-0002")
        self.assertEqual(out2["appended"], 1)

    def test_stale_head_rejected_and_file_unchanged(self):
        out = self.genesis()
        before = self.bytes_now()
        with self.assertRaises(R.StaleHeadError):
            R.append_events(self.reg, [mint()], R.GENESIS_HASH)
        with self.assertRaises(R.StaleHeadError):
            R.append_events(self.reg, [mint()], "0" * 64)
        self.assertEqual(self.bytes_now(), before)
        self.assertEqual(out["head"], R.head_of(R.read_registry(self.reg)[0]))

    def test_unlink_fold_and_projection_absence(self):
        out = self.genesis()
        out2 = R.append_events(self.reg, [unlink("cab-0001", 2)], out["head"])
        lines, events = R.read_registry(self.reg)
        state = R.fold_events(events)
        members = state["cabinets"]["cab-0001"]["members"]
        self.assertEqual([m["id"] for m in members], ["C-0002"])
        self.assertIsNone(state["members"]["claim-register:C-0001"]["primary"])
        res = R.project(self.reg, generated_at=AT)
        self.assertEqual(res["active_memberships"], 1)
        with open(os.path.join(self.tmp.name, "PROJECTION.json"), "rb") as f:
            proj = json.loads(f.read().decode("utf-8"))
        self.assertNotIn("claim-register:C-0001", proj["members"])
        self.assertEqual(
            [m["id"] for m in proj["cabinets"]["cab-0001"]["members"]],
            ["C-0002"])
        # Projection retry with the same fold is byte-idempotent.
        with open(os.path.join(self.tmp.name, "PROJECTION.json"), "rb") as f:
            first = f.read()
        R.project(self.reg, generated_at=AT)
        with open(os.path.join(self.tmp.name, "PROJECTION.json"), "rb") as f:
            self.assertEqual(f.read(), first)
        self.assertEqual(out2["appended"], 1)

    def test_secondary_membership_projection(self):
        out = self.genesis()
        out = R.append_events(self.reg, [mint()], out["head"])  # cab-0002
        out = R.append_events(self.reg, [
            link("cab-0002", None, "C-0001", relation="secondary",
                 reason="secondary-relation")], out["head"])
        R.project(self.reg, generated_at=AT)
        with open(os.path.join(self.tmp.name, "PROJECTION.json"), "rb") as f:
            proj = json.loads(f.read().decode("utf-8"))
        entry = proj["members"]["claim-register:C-0001"]
        self.assertEqual(entry["cabinet_id"], "cab-0001")
        self.assertEqual(entry["also"][0]["cabinet_id"], "cab-0002")
        self.assertEqual(entry["also"][0]["relation"], "secondary")


class TestValidation(ScratchCase):
    def setUp(self):
        super().setUp()
        self.head = self.genesis()["head"]
        self.before = self.bytes_now()

    def assert_rejected(self, candidates):
        with self.assertRaises(R.ValidationError):
            R.append_events(self.reg, candidates, self.head)
        self.assertEqual(self.bytes_now(), self.before)

    def test_battery(self):
        self.assert_rejected([link("cab-0099", None, "C-0009")])  # unminted
        self.assert_rejected([link("cab-0001", None, "C-0001")])  # 2nd primary
        self.assert_rejected([mint("cab-0001")])                  # duplicate MINT
        self.assert_rejected([unlink("cab-0001", 1)])             # corrects a MINT
        self.assert_rejected([unlink("cab-0001", 2, cid="C-0002")])  # mismatch
        self.assert_rejected([link("cab-0001", None, "C-0009",
                                   evidence="not-a-digest")])
        self.assert_rejected([link("cab-0001", None, "C-0009",
                                   reason="free-text-reason")])
        self.assert_rejected([link("cab-0001", None, "C-0009",
                                   actor="has space")])
        bad = link("cab-0001", None, "C-0009")
        del bad["reason"]
        self.assert_rejected([bad])
        bad2 = link("cab-0001", None, "C-0009")
        bad2["extra"] = "field"
        self.assert_rejected([bad2])
        bad3 = mint("cab-0002")
        bad3["reason"] = "some-other-code"
        self.assert_rejected([bad3])

    def test_seq_monotonicity(self):
        out = R.append_events(self.reg, [mint("cab-0005")], self.head)
        before = self.bytes_now()
        with self.assertRaises(R.ValidationError):
            R.append_events(self.reg, [mint("cab-0003")], out["head"])
        self.assertEqual(self.bytes_now(), before)

    def test_double_unlink_rejected(self):
        out = R.append_events(self.reg, [unlink("cab-0001", 2)], self.head)
        before = self.bytes_now()
        with self.assertRaises(R.ValidationError):
            R.append_events(self.reg,
                            [unlink("cab-0001", 2, at="2026-11-05T13:05:00-08:00")],
                            out["head"])
        self.assertEqual(self.bytes_now(), before)


class TestByteRules(ScratchCase):
    def _write(self, data):
        with open(self.reg, "wb") as f:
            f.write(data)

    def test_partial_tail_no_lf_refused_then_recovered(self):
        out = self.genesis()
        good = self.bytes_now()
        partial = b'{"type": "LINK", "cabinet_id": "cab-0001", "at'
        with open(self.reg, "ab") as f:
            f.write(partial)
        with self.assertRaises(R.PartialTailError):
            R.read_registry(self.reg)
        damaged = self.bytes_now()
        # B2: recovery without an INDEX path fails BEFORE any mutation —
        # a removal record must be durable, never stdout-only.
        with self.assertRaises(R.RegistryError):
            R.recover_tail(self.reg)
        self.assertEqual(self.bytes_now(), damaged)
        # With an index path (INDEX.md absent -> created by recovery):
        index = os.path.join(self.tmp.name, "INDEX.md")
        res = R.recover_tail(self.reg, index_path=index)
        self.assertEqual(res["removed_bytes"], len(partial))
        self.assertEqual(res["head"], out["head"])
        self.assertEqual(self.bytes_now(), good)
        with open(index, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Recovery records", text)
        self.assertIn(f"removed {len(partial)} trailing", text)
        state = R.fold_events(R.read_registry(self.reg)[1])
        self.assertEqual(len(state["cabinets"]["cab-0001"]["members"]), 2)

    def test_invalid_json_final_line_lf_terminated_refused(self):
        # AMENDED in fix round 1 (finding B1): an LF-terminated final
        # line is COMPLETE by construction — invalid JSON behind an LF
        # is hard corruption, never crash debris, and recovery must not
        # truncate it. (The pre-fix suite treated it as a partial tail;
        # that expectation encoded the defect.)
        self.genesis()
        good = self.bytes_now()
        with open(self.reg, "ab") as f:
            f.write(b'{"type": "LINK", nope\n')
        with self.assertRaises(R.RegistryError) as cm:
            R.read_registry(self.reg)
        self.assertNotIsInstance(cm.exception, R.PartialTailError)
        index = os.path.join(self.tmp.name, "INDEX.md")
        with self.assertRaises(R.RegistryError):
            R.recover_tail(self.reg, index_path=index)
        self.assertEqual(self.bytes_now(),
                         good + b'{"type": "LINK", nope\n')

    def test_unterminated_complete_line_is_partial_tail(self):
        self.genesis()
        ev = link("cab-0001", None, "C-0003")
        ev["prev_hash"] = R.head_of(R.read_registry(self.reg)[0])
        with open(self.reg, "ab") as f:
            f.write(R.serialize_event(ev).encode("utf-8"))  # no LF
        with self.assertRaises(R.PartialTailError):
            R.read_registry(self.reg)

    def test_interior_corruption_is_not_a_tail(self):
        line = R.serialize_event({**mint("cab-0001"),
                                  "prev_hash": R.GENESIS_HASH})
        dup = ('{"type": "MINT", "type": "MINT"}').encode()
        self._write(dup + b"\n" + line.encode() + b"\n")
        with self.assertRaises(R.RegistryError) as cm:
            R.read_registry(self.reg)
        self.assertNotIsInstance(cm.exception, R.PartialTailError)
        crlf = line.replace('{"type"', '{"type"').encode() + b"\r\n" \
            + line.encode() + b"\n"
        self._write(crlf)
        with self.assertRaises(R.RegistryError):
            R.read_registry(self.reg)

    def test_chain_break_detected(self):
        self.genesis()
        lines, events = R.read_registry(self.reg)
        events[1]["prev_hash"] = "0" * 64
        with self.assertRaises(R.ValidationError):
            R.verify_chain(lines, events)


class TestFinalLineHardErrors(ScratchCase):
    """Finding B1: hard §4 errors on the FINAL line are corruption, not
    crash debris — never PartialTailError, never truncated by recovery."""

    def _append_raw(self, data):
        with open(self.reg, "ab") as f:
            f.write(data)

    def test_complete_mint_crlf_terminated_survives_recovery_attempt(self):
        out = self.genesis()
        ev = mint("cab-0002")
        ev["prev_hash"] = out["head"]
        line = R.serialize_event(ev).encode("utf-8") + b"\r\n"  # complete, CRLF
        self._append_raw(line)
        damaged = self.bytes_now()
        with self.assertRaises(R.RegistryError) as cm:
            R.read_registry(self.reg)
        self.assertNotIsInstance(cm.exception, R.PartialTailError)
        index = os.path.join(self.tmp.name, "INDEX.md")
        with self.assertRaises(R.RegistryError):
            R.recover_tail(self.reg, index_path=index)
        self.assertEqual(self.bytes_now(), damaged)  # nothing removed

    def test_duplicate_key_final_line_errors_without_mutation(self):
        self.genesis()
        dup = b'{"type": "MINT", "type": "MINT", "cabinet_id": "cab-0002"}\n'
        self._append_raw(dup)
        damaged = self.bytes_now()
        with self.assertRaises(R.RegistryError) as cm:
            R.read_registry(self.reg)
        self.assertNotIsInstance(cm.exception, R.PartialTailError)
        index = os.path.join(self.tmp.name, "INDEX.md")
        with self.assertRaises(R.RegistryError):
            R.recover_tail(self.reg, index_path=index)
        self.assertEqual(self.bytes_now(), damaged)

    def test_recovery_record_failure_fails_before_mutation(self):
        # B2: index path exists as a DIRECTORY -> the removal record
        # cannot be written -> recovery aborts, registry untouched.
        self.genesis()
        partial = b'{"type": "LINK", "cab'
        self._append_raw(partial)
        damaged = self.bytes_now()
        index_dir = os.path.join(self.tmp.name, "INDEX.md")
        os.mkdir(index_dir)
        with self.assertRaises(R.RegistryError):
            R.recover_tail(self.reg, index_path=index_dir)
        self.assertEqual(self.bytes_now(), damaged)

    def test_unterminated_invalid_json_is_still_a_partial_tail(self):
        out = self.genesis()
        good = self.bytes_now()
        self._append_raw(b'{"type": "LINK", nope')  # no LF terminator
        with self.assertRaises(R.PartialTailError):
            R.read_registry(self.reg)
        index = os.path.join(self.tmp.name, "INDEX.md")
        res = R.recover_tail(self.reg, index_path=index)
        self.assertGreater(res["removed_bytes"], 0)
        self.assertEqual(res["head"], out["head"])
        self.assertEqual(self.bytes_now(), good)


class TestForgetMember(ScratchCase):
    """Finding C2: forget purges the member's derived memberships from
    the fold and both projections in the same operation."""

    def _setup(self):
        out = self.genesis()  # cab-0001: C-0001 primary (2), C-0002 primary (3)
        out = R.append_events(self.reg, [mint()], out["head"])  # cab-0002 (4)
        out = R.append_events(self.reg, [
            link("cab-0002", None, "C-0001", relation="secondary",
                 reason="secondary-relation")], out["head"])  # line 5
        # A previously reversed link for C-0002 (secondary, then UNLINK):
        out = R.append_events(self.reg, [
            link("cab-0002", None, "C-0002", relation="secondary",
                 reason="secondary-relation")], out["head"])  # line 6
        out = R.append_events(self.reg, [
            unlink("cab-0002", 6, cid="C-0002", relation="secondary")],
            out["head"])  # line 7
        return out

    def test_forget_purges_fold_projection_and_index(self):
        out = self._setup()
        res = R.forget_member(self.reg, "claim-register", "C-0001",
                              out["head"], ACTOR, EV, at=AT)
        self.assertEqual(res["unlinked"], 2)  # primary + secondary
        lines, events = R.read_registry(self.reg)
        state = R.fold_events(events)
        self.assertIsNone(state["members"]["claim-register:C-0001"]["primary"])
        self.assertEqual(state["members"]["claim-register:C-0001"]["secondary"],
                         [])
        # C-0002 untouched (its primary survives; its reversed secondary
        # stays reversed — forget appended nothing for it):
        self.assertEqual(
            state["members"]["claim-register:C-0002"]["primary"]["cabinet_id"],
            "cab-0001")
        forgets = [e for e in events
                   if e["type"] == "UNLINK"
                   and e["reason"] == "forget-consequence"]
        self.assertEqual(len(forgets), 2)
        with open(os.path.join(self.tmp.name, "PROJECTION.json"), "rb") as f:
            proj = json.loads(f.read().decode("utf-8"))
        self.assertNotIn("claim-register:C-0001", proj["members"])
        with open(os.path.join(self.tmp.name, "INDEX.md"),
                  encoding="utf-8") as f:
            self.assertNotIn("C-0001", f.read())
        # History is tombstone-grade: the member's (system, ID) pair and
        # kind remain in history lines (permitted tombstone content),
        # but no event carries anything beyond the closed inventory.
        for e in events:
            self.assertLessEqual(
                set(e), {"type", "cabinet_id", "at", "actor", "member",
                         "relation", "evidence", "corrects", "reason",
                         "prev_hash"})
        # Rebuild after purge shows no residue:
        R.project(self.reg, generated_at=AT)
        with open(os.path.join(self.tmp.name, "PROJECTION.json"), "rb") as f:
            proj2 = json.loads(f.read().decode("utf-8"))
        self.assertNotIn("claim-register:C-0001", proj2["members"])

    def test_forget_member_with_only_reversed_links_appends_nothing(self):
        out = self.genesis()
        out = R.append_events(self.reg, [unlink("cab-0001", 3, cid="C-0002")],
                              out["head"])  # C-0002 fully reversed already
        before = self.bytes_now()
        res = R.forget_member(self.reg, "claim-register", "C-0002",
                              out["head"], ACTOR, EV, at=AT)
        self.assertEqual(res["unlinked"], 0)
        self.assertEqual(self.bytes_now(), before)

    def test_forget_stale_head_rejected(self):
        out = self._setup()
        before = self.bytes_now()
        with self.assertRaises(R.StaleHeadError):
            R.forget_member(self.reg, "claim-register", "C-0001",
                            R.GENESIS_HASH, ACTOR, EV, at=AT)
        self.assertEqual(self.bytes_now(), before)


class TestForgetLabels(ScratchCase):
    """Fix round 2 (finding C2): INDEX labels derive only from the
    post-forget fold. A label sourced from a forgotten member's
    record is purged in the same operation and never merged back in;
    a label on a Cabinet left empty by the forget is dropped; an
    operator label on a still-populated Cabinet survives."""

    def _index(self):
        with open(os.path.join(self.tmp.name, "INDEX.md"),
                  encoding="utf-8") as f:
            return f.read()

    def test_member_derived_label_purged_on_forget(self):
        out = self.genesis()  # cab-0001: C-0001 + C-0002
        R.project(self.reg, generated_at=AT, labels={
            "cab-0001": {"label": "target-work-area",
                         "derived_from": "claim-register:C-0001"}})
        text = self._index()
        self.assertIn("target-work-area", text)
        self.assertIn("- cab-0001 <= claim-register:C-0001", text)
        R.forget_member(self.reg, "claim-register", "C-0001",
                        out["head"], ACTOR, EV, at=AT)
        text = self._index()
        self.assertNotIn("target-work-area", text)
        self.assertNotIn("Label provenance", text)
        self.assertIn("| cab-0001 | — |", text)
        self.assertIn("C-0002", text)  # bystander membership intact
        # A later rebuild must not merge the label back in either.
        R.project(self.reg, generated_at=AT)
        self.assertNotIn("target-work-area", self._index())

    def test_plain_label_dropped_when_cabinet_empties(self):
        out = R.append_events(self.reg, [
            mint(), link("cab-0001", None, "C-0009")], R.GENESIS_HASH)
        R.project(self.reg, generated_at=AT,
                  labels={"cab-0001": "solo-area-label"})
        self.assertIn("solo-area-label", self._index())
        R.forget_member(self.reg, "claim-register", "C-0009",
                        out["head"], ACTOR, EV, at=AT)
        text = self._index()
        self.assertNotIn("solo-area-label", text)
        self.assertIn("| cab-0001 | — |", text)

    def test_operator_label_survives_while_cabinet_nonempty(self):
        out = self.genesis()
        R.project(self.reg, generated_at=AT,
                  labels={"cab-0001": "operator-area"})
        R.forget_member(self.reg, "claim-register", "C-0001",
                        out["head"], ACTOR, EV, at=AT)
        self.assertIn("operator-area", self._index())


class TestIndexRegeneration(ScratchCase):
    def test_labels_and_pending_carried(self):
        self.genesis()
        index_path = os.path.join(self.tmp.name, "INDEX.md")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Cabinet Registrar — Index\n\n"
                    "| Cabinet | INDEX label | Members |\n|---|---|---|\n"
                    "| cab-0001 | my-work-area | x |\n\n"
                    "## Pending exhibits (not stamped)\n\n"
                    "- **Pair X** — pending a human decision.\n")
        R.project(self.reg, generated_at=AT)
        with open(index_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("my-work-area", text)
        self.assertIn("Pair X", text)
        self.assertIn("Cabinets minted: 1", text)
        self.assertIn("2 primary, 0 secondary", text)


class TestAcceptedRegistryParity(unittest.TestCase):
    """Read-only: the production fold/projector must reproduce the
    accepted Step 1 projection byte-for-byte (same generated_at)."""

    def test_projection_parity(self):
        reg = os.path.join(REPO, "docs", "cabinet-registry", "REGISTRY.jsonl")
        proj_path = os.path.join(REPO, "docs", "cabinet-registry",
                                 "PROJECTION.json")
        if not (os.path.exists(reg) and os.path.exists(proj_path)):
            self.skipTest("accepted registry not present")
        with open(proj_path, "rb") as f:
            committed = f.read()
        committed_proj = json.loads(committed.decode("utf-8"))
        lines, events = R.read_registry(reg)
        R.verify_chain(lines, events)
        state = R.fold_events(events)
        self.assertEqual(state["max_mint_seq"], 16)
        self.assertEqual(state["event_count"], 58)
        rebuilt = R.build_projection(
            state, R.head_of(lines), len(lines),
            committed_proj["generated_from"]["generated_at"])
        self.assertEqual(R.projection_bytes(rebuilt), committed)


class TestCli(unittest.TestCase):
    def run_cli(self, *argv):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [sys.executable, os.path.join(PKG, "registrar.py"), *argv],
            capture_output=True, text=True, env=env)

    def test_verify_accepted_registry_readonly(self):
        reg = os.path.join(REPO, "docs", "cabinet-registry", "REGISTRY.jsonl")
        if not os.path.exists(reg):
            self.skipTest("accepted registry not present")
        r = self.run_cli("verify", "--registry", reg)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["lines"], 58)
        self.assertEqual(
            out["head"],
            "24d0b715fa4e61d85aaa4dfa49ae25e56e95267270a1805db3d5789cab4fd716")

    def test_cli_append_project_recover_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = os.path.join(tmp, "REGISTRY.jsonl")
            evs = os.path.join(tmp, "events.json")
            with open(evs, "w", encoding="utf-8") as f:
                json.dump([mint(), link("cab-0001", None, "C-0001")], f)
            r = self.run_cli("append", "--registry", reg,
                             "--expected-head", R.GENESIS_HASH,
                             "--events", evs)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            head = json.loads(r.stdout)["head"]
            r = self.run_cli("append", "--registry", reg,
                             "--expected-head", R.GENESIS_HASH,
                             "--events", evs)
            self.assertEqual(r.returncode, 2)  # stale head via CLI
            self.assertIn("StaleHeadError", r.stdout)
            r = self.run_cli("project", "--registry", reg,
                             "--generated-at", AT)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            with open(reg, "ab") as f:
                f.write(b'{"type": "LI')
            r = self.run_cli("recover", "--registry", reg)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(r.stdout)["head"], head)


if __name__ == "__main__":
    unittest.main()
