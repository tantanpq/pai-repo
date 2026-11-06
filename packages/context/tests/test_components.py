#!/usr/bin/env python3
"""Characterization tests for Phase 4 Slice 3 — component adapters
(packages/context/components.py).

Golden fixtures are the deterministic captures from SLICE3_RECON §6,
copied into tests/fixtures/ — EXCEPT home-cp-readers.json, which
embeds 768 base64 bytes of a REAL run receipt and stays
programme-side only (recon §6.3 hygiene); the repo fixture is the
synthetic content-free variant (home-cp-readers-synthetic.json)
staged exactly as recon §6.3 prescribes. retrieval-query-snapshot.json
is likewise not copied: it is a live-data snapshot, not byte-stable
(recon §6.4).

Everything runs offline through FixtureTransport (Chief / Resident /
home-cp) and the in-process transport (retrieval — the repo's own
package). Live tests against HOME are guarded by PAI_SLICE3_LIVE=1
and skipped by default; the suite never requires the network.

HONESTY NOTE (review F3): two fixture replays are input-insensitive
stubs, and assertions against them characterize the RECORDED FIXTURE,
not the component. FixtureTransport._do_resident_fidelity returns
{ok: True, missing: []} unconditionally, so any fidelity_missing == []
assertion here is a fixture-shape check. FixtureTransport
._do_home_cp_bounded returns the recorded bounded dict for any
input, so test_bounded_preview_fixture likewise characterizes the
recorded fixture, not live home-cp behaviour. Component-behaviour
evidence for those paths is the live reproduction script
(pai-repo-program/phase4/slice3_live_repro.py), not these stub
assertions — do not mistake a stub assertion for a component
assertion.

Run: python3 -m unittest test_components -v   (from this directory)
"""
import base64
import hashlib
import json
import os
import sys
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
CTX = os.path.abspath(os.path.join(HERE, ".."))
if CTX not in sys.path:
    sys.path.insert(0, CTX)
import components as C  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
LIVE = os.environ.get("PAI_SLICE3_LIVE") == "1"

HEAVY_BODY = ("# TASK\n\n## OBJECTIVE\n"
              + " ".join(["Heavy objective sentence."] * 40)
              + " \n\n## ACCEPTANCE\nHeavy fixture passes.\n")
FUSE_BODY = "# TASK\n\n## OBJECTIVE\n" + "x" * 20000 + "\n"


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def fixture_transport():
    return C.FixtureTransport(FIXTURES)


class ChiefCapsuleTest(unittest.TestCase):
    def setUp(self):
        self.chief = C.ChiefAdapter(fixture_transport())

    def test_ready_reproduces_fixture(self):
        fx = load("chief-capsule-ready.json")
        out = self.chief.build_capsule(fx["input"])
        self.assertEqual(out, fx["output"])
        self.assertEqual(out["status"], "READY")
        src_b = [s for s in out["sources"] if s["id"] == "b"][0]
        self.assertTrue(src_b["truncated"])
        self.assertTrue(src_b["content"].endswith("…[TRUNCATED]"))
        self.assertEqual(out["budget_decision"]["degradationTrace"], ["b"])

    def test_context_miss_reproduces_fixture(self):
        fx = load("chief-capsule-context-miss.json")
        out = self.chief.build_capsule(fx["input"])
        self.assertEqual(out, fx["output"])
        self.assertEqual(out["status"], "CONTEXT_MISS")
        self.assertEqual(out["context_miss"]["reason"],
                         "REQUIRED_SOURCE_TRUNCATED")

    def test_budget_validated_before_invoking(self):
        # A source without a declared cap must fail BEFORE the
        # transport is touched (contract rule 2 at the boundary).
        calls = []

        def spy(component, operation, payload):
            calls.append((component, operation))
            return {}

        chief = C.ChiefAdapter(C.CallableTransport(spy))
        bad = {"objective": "x", "context_budget":
               {"total": 100, "output_reserve": 10, "source_caps": {}},
               "sources": [{"id": "s1", "content": "hello"}]}
        with self.assertRaises(C.AdapterBudgetError):
            chief.build_capsule(bad)
        self.assertEqual(calls, [])

    def test_over_budget_component_output_fails_loudly(self):
        fx = load("chief-capsule-ready.json")
        oversized = json.loads(json.dumps(fx["output"]))
        oversized["sources"][0]["content"] = "z" * 500  # cap is 100

        def stub(component, operation, payload):
            return oversized

        chief = C.ChiefAdapter(C.CallableTransport(stub))
        with self.assertRaises(C.AdapterBudgetError):
            chief.build_capsule(fx["input"])


class ChiefCursorTest(unittest.TestCase):
    def setUp(self):
        self.chief = C.ChiefAdapter(fixture_transport())

    def test_sequence_reproduces_fixture_exactly(self):
        fx = load("chief-cursor-continuity.json")
        out = self.chief.cursor_sequence()
        self.assertEqual(out, fx)
        self.assertEqual(
            out["commit1"]["bundleHash"],
            "39f8c42bf9a9ae5a24562736bd1472b8d6bf9f7930da804d5d389ba3184956d1")
        self.assertEqual(out["gapError"], "CURSOR_GAP")
        self.assertEqual(out["hashError"], "PRIOR_HASH_MISMATCH")

    def test_commit_and_compact_through_adapter(self):
        receipt = self.chief.commit_bundle({
            "threadRef": "t-fix", "fromCursor": 0,
            "previousBundleHash": None, "idempotencyKey": "k-1",
            "events": [{"threadRef": "t-fix", "sequence": 1,
                        "role": "user", "text": "hello"}]})
        self.assertEqual(receipt["bundleHash"],
                         load("chief-cursor-continuity.json")
                         ["commit1"]["bundleHash"])
        compact = self.chief.compact_bundle("t-fix", 32)
        self.assertEqual(compact["cursor"], 1)
        self.assertEqual(compact["retained"][0]["text"], "hello")

    def test_read_cursor_resume_after_evidence_change_is_stale(self):
        evidence = {"sources": [{"id": "a", "hash": "aa"},
                                {"id": "b", "hash": "bb"}]}
        cursor = self.chief.issue_read_cursor(evidence, position=40)
        self.assertEqual(
            self.chief.resume_read_cursor(cursor, evidence), 40)
        changed = {"sources": [{"id": "a", "hash": "aa"},
                               {"id": "b", "hash": "CHANGED"}]}
        with self.assertRaises(C.StaleCursorError) as cm:
            self.chief.resume_read_cursor(cursor, changed)
        self.assertIn("STALE", str(cm.exception))


class ChiefReducerTest(unittest.TestCase):
    def setUp(self):
        self.chief = C.ChiefAdapter(fixture_transport())

    def test_frozen_envelope_fields(self):
        fx = load("chief-reducer-frozen-envelope.json")
        out = self.chief.reduce_envelope(fx["input"], fx["options"])
        for key, value in fx["output"].items():
            self.assertEqual(out[key], value, key)
        self.assertTrue(out["redacted"])
        self.assertNotIn("hunter2", out["excerpt"])
        self.assertEqual(out["exactRanges"],
                         [{"startByte": 0, "endByteExclusive": 100}])
        self.assertEqual(out["adapter_counted_input_bytes"],
                         len(fx["input"]["raw"].encode("utf-8")))

    def test_current_receipt_silent_caps_are_surfaced(self):
        fx = load("chief-reducer-current.json")
        out = self.chief.reduce_receipt(fx["input"])
        self.assertEqual(out["receipt"], fx["output"])
        # The component sliced silently (findings 8->6, files 15->12,
        # deltas 7->6, refs 7->6) with NO truncated flag; the adapter
        # must mark it and name the sliced fields (recon §1.4a).
        self.assertFalse(out["component_truncated_flag"])
        self.assertTrue(out["truncated"])
        self.assertEqual(out["counts"]["keyFindings"], {"in": 8, "out": 6})
        self.assertEqual(out["counts"]["changedFiles"],
                         {"in": 15, "out": 12})
        for field in ("keyFindings", "materialDeltas",
                      "changedFiles", "evidenceRefs"):
            self.assertIn(field, out["sliced_fields"])

    def test_reducers_are_distinct_operations(self):
        self.assertTrue(hasattr(self.chief, "reduce_envelope"))
        self.assertTrue(hasattr(self.chief, "reduce_receipt"))
        self.assertFalse(hasattr(self.chief, "reduce_tool_result"))

    def test_paginate_fixture(self):
        fx = load("chief-reducer-current.json")["paginate"]
        out = self.chief.paginate(list(range(1, 11)), page=1, page_size=8)
        self.assertEqual(out, fx)
        self.assertEqual(out["cursor"], "cursor_8")
        self.assertTrue(out["has_more"])


class ChiefTypedOutwardTest(unittest.TestCase):
    def setUp(self):
        self.chief = C.ChiefAdapter(fixture_transport())
        self.fx = load("chief-typed-outward.json")

    def test_budgets_recorded_verbatim(self):
        self.assertEqual(C.ChiefAdapter.OUTWARD_BUDGETS, self.fx["budgets"])

    def test_exact_fetch_chunk_is_8192_bytes(self):
        out = self.chief.format_typed_outward(
            "fetch", call={"toolName": "fetch", "input": {},
                           "result": {"id": "doc-fix-1",
                                      "text": "x" * 15000}})
        self.assertEqual(out["contract_type"], "EXACT_FETCH_CHUNK")
        self.assertEqual(out["bytes"], 8192)
        self.assertEqual(len(out["text"].encode("utf-8")), 8192)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["pointer"], "doc-fix-1")

    def test_terminal_read_chunk_bounds(self):
        out = self.chief.format_typed_outward("terminal")
        exp = self.fx["terminal"]["output"]
        self.assertEqual(out, exp)
        self.assertEqual(out["text"].count("\n"), 40)      # 40 lines
        self.assertEqual(out["bytes"], 200)                # 200 bytes
        self.assertEqual(out["next_cursor"],
                         out["cursor"] + out["bytes"])    # exact
        self.assertTrue(out["has_more"])


class ResidentTest(unittest.TestCase):
    def setUp(self):
        self.resident = C.ResidentAdapter(fixture_transport())
        self.fx = load("resident-packet-compiler.json")

    def test_ceilings_are_bytes_never_tokens(self):
        self.assertEqual(self.fx["output"]["ceilings"],
                         {"HARD_CEILING": 12288, "PREFERRED_CEILING": 8192})
        self.assertEqual(C.ResidentAdapter.HARD_CEILING_BYTES, 12288)
        self.assertEqual(C.ResidentAdapter.PREFERRED_CEILING_BYTES, 8192)

    def test_small_packet_byte_identical(self):
        art = self.fx["inputs"]["small"]
        out = self.resident.compile_packet(art)
        exp = self.fx["output"]["small"]
        self.assertEqual(out["packet"], exp["packet"])  # byte-identical
        self.assertEqual(out["bytes"], 537)
        self.assertEqual(out["unit"], "bytes")
        self.assertFalse(out["heavy"])
        self.assertEqual(out["fidelity_missing"], [])
        self.assertEqual(out["warnings"], [])

    def test_heavy_packet_byte_identical_and_cursor_bound(self):
        art = {"header": {"TASK_ID": "FIX-HEAVY", "TYPE": "WORK",
                          "MUTABLE_SCOPE": "scope/fix"},
               "body": HEAVY_BODY}
        self.assertEqual(len(HEAVY_BODY), 1099)
        self.assertEqual(hashlib.sha256(HEAVY_BODY.encode()).hexdigest(),
                         self.fx["output"]["heavy"]["inputSha256"])
        out = self.resident.compile_packet(art)
        exp = self.fx["output"]["heavy"]
        self.assertEqual(out["packet"], exp["packet"])  # byte-identical
        self.assertEqual(out["bytes"], 1633)
        self.assertTrue(out["heavy"])
        self.assertEqual(out["inputRef"], "_PAI_EXECUTOR_INPUT.md")
        # Cursor binds to inputSha256: same hash resumes, changed fails.
        ok = self.resident.resume_packet(out["cursor"], out["inputSha256"])
        self.assertEqual(ok["status"], "ok")
        with self.assertRaises(C.StaleCursorError) as cm:
            self.resident.resume_packet(out["cursor"], "0" * 64)
        self.assertIn("STALE", str(cm.exception))

    def test_fuse_overflow_fails_loudly_with_component_code(self):
        # Fully specified input (review F2): MUTABLE_SCOPE
        # 'scope/fix' (9 chars) vs the component default 'NONE'
        # (4 chars) is the Δ5B — this header is what makes the
        # asserted 20582B the count the component actually throws
        # for this input (without it the live count is 20577B).
        art = {"header": {"TASK_ID": "FIX-FUSE", "TYPE": "WORK",
                          "MUTABLE_SCOPE": "scope/fix"},
               "body": FUSE_BODY}
        with self.assertRaises(C.AdapterBudgetError) as cm:
            self.resident.compile_packet(art)
        self.assertEqual(cm.exception.code,
                         "CONTEXT_BUDGET_OVERRIDE_REQUIRED")
        self.assertIn("20582B exceeds 12288B", str(cm.exception))

    def test_preferred_ceiling_is_a_flagged_warning(self):
        def stub(component, operation, payload):
            if operation == "compile":
                packet = "p" * 9000  # between 8192 and 12288 bytes
                return {"schema": "pai-executor-context-packet/r16",
                        "packet": packet, "bytes": 9000,
                        "inputSha256": "a" * 64, "heavy": True,
                        "protected_semantic_field_fidelity": 1}
            return {"ok": True, "missing": [],
                    "protected_semantic_field_fidelity": 1}

        resident = C.ResidentAdapter(C.CallableTransport(stub))
        out = resident.compile_packet({"header": {}, "body": "b"})
        self.assertTrue(out["preferred_ceiling_exceeded"])
        self.assertIn("PREFERRED_CEILING_EXCEEDED", out["warnings"][0])
        self.assertIn("bytes", out["warnings"][0])

    def test_over_hard_ceiling_output_fails_loudly(self):
        def stub(component, operation, payload):
            if operation == "compile":
                packet = "p" * 13000
                return {"packet": packet, "bytes": 13000,
                        "inputSha256": "a" * 64,
                        "protected_semantic_field_fidelity": 1}
            return {"ok": True, "missing": []}

        resident = C.ResidentAdapter(C.CallableTransport(stub))
        with self.assertRaises(C.AdapterBudgetError):
            resident.compile_packet({"header": {}, "body": "b"})

    def test_bounded_artifact_tail_fixture(self):
        out = self.resident.bounded_artifact("q" * 20000, 12288)
        tail = self.fx["output"]["boundedArtifact"]
        self.assertEqual(out["tail"], tail)
        self.assertTrue(tail.endswith("/* boundedArtifact emergency fuse */\n"))


class HomeCpTest(unittest.TestCase):
    def setUp(self):
        self.transport = fixture_transport()
        self.homecp = C.HomeCpAdapter(self.transport)
        self.fx = load("home-cp-readers-synthetic.json")
        self.ref = self.fx["usedResultRefRelative"]

    def test_validate_passes_through(self):
        out = self.homecp.validate_read(
            {"action": "result.read",
             "params": {"result_ref": self.ref, "cursor": 0,
                        "max_bytes": 768}})
        self.assertEqual(out, self.fx["validated"])

    def test_page_zero_fields(self):
        out = self.homecp.read_page(self.ref, max_bytes=768)
        exp = self.fx["page"]
        self.assertEqual(out["bytes"], 768)
        self.assertEqual(out["next_cursor"], 768)
        self.assertEqual(out["total_bytes"], 868)
        self.assertEqual(out["sha256"], exp["sha256"])
        self.assertEqual(out["content"], exp["content"])
        self.assertTrue(out["has_more"])
        self.assertIsNotNone(out["adapter_cursor"])

    def test_resume_with_adapter_cursor(self):
        page0 = self.homecp.read_page(self.ref, max_bytes=768)
        page1 = self.homecp.read_page(self.ref, max_bytes=768,
                                      cursor=page0["adapter_cursor"])
        self.assertEqual(page1["bytes"], 100)
        self.assertFalse(page1["has_more"])
        whole = base64.b64decode(page0["content"]) \
            + base64.b64decode(page1["content"])
        self.assertEqual(hashlib.sha256(whole).hexdigest(),
                         self.fx["page"]["sha256"])

    def test_cursor_beyond_eof_is_component_budget_error(self):
        with self.assertRaises(C.ComponentError) as cm:
            self.transport.invoke("home_cp", "read_page",
                                  {"result_ref": self.ref, "cursor": 9999,
                                   "max_bytes": 768})
        self.assertEqual(cm.exception.code, "HOME_CP_RESULT_BUDGET")

    def test_adapter_chunks_over_the_3072_cap(self):
        # One adapter read of 800 bytes crosses two component pages
        # only if the cap forced it; here a 3072+ request on the
        # 868-byte file delivers the whole file in chunks.
        out = self.homecp.read_page(self.ref, max_bytes=5000)
        self.assertEqual(out["bytes"], 868)
        self.assertEqual(out["total_bytes"], 868)
        self.assertFalse(out["has_more"])

    def test_resume_after_change_is_stale_via_page_hash(self):
        page0 = self.homecp.read_page(self.ref, max_bytes=768)
        self.transport.replace_synthetic_content(b'{"ok": false}' * 60)
        with self.assertRaises(C.StaleCursorError) as cm:
            self.homecp.read_page(self.ref, max_bytes=100,
                                  cursor=page0["adapter_cursor"])
        self.assertIn("STALE", str(cm.exception))

    def test_oversized_page_fails_loudly(self):
        # Review F1 probe shape: a self-consistent 5000-byte page
        # returned against a 768-byte request must fail loudly,
        # never pass through the adapter.
        raw = b"x" * 5000

        def stub(component, operation, payload):
            return {"result_ref": self.ref, "cursor": 0,
                    "next_cursor": 5000, "bytes": 5000,
                    "total_bytes": 5000, "encoding": "base64",
                    "content": base64.b64encode(raw).decode("ascii"),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "has_more": False}

        homecp = C.HomeCpAdapter(C.CallableTransport(stub))
        with self.assertRaises(C.AdapterBudgetError):
            homecp.read_page(self.ref, max_bytes=768)

    def test_component_changed_error_translates_to_stale(self):
        def stub(component, operation, payload):
            raise C.ComponentError("HOME_CP_RESULT_CHANGED",
                                   code="HOME_CP_RESULT_CHANGED")

        homecp = C.HomeCpAdapter(C.CallableTransport(stub))
        with self.assertRaises(C.StaleCursorError) as cm:
            homecp.read_page(self.ref, max_bytes=100)
        self.assertIn("STALE", str(cm.exception))

    def test_bounded_preview_fixture(self):
        out = self.homecp.bounded({"cp_result": "y" * 10000}, limit=1000)
        self.assertEqual(out, self.fx["bounded"])
        self.assertTrue(out["truncated"])
        self.assertEqual(out["previewBytes"], 1000)


class RetrievalTest(unittest.TestCase):
    def setUp(self):
        self.retrieval = C.RetrievalAdapter()
        self.fx = load("retrieval-snippet.json")

    def test_snippet_and_est_tokens_exact(self):
        out = self.retrieval.make_snippet(
            self.fx["text"], self.fx["qtokens"], cap=self.fx["cap"])
        self.assertEqual(out["snippet"], self.fx["snippet"])
        self.assertEqual(out["est_tokens"],
                         self.fx["est_tokens_of_snippet"])
        self.assertEqual(out["est_tokens"], 46)
        self.assertEqual(out["estimator"], "ceil(chars/4)")

    def test_snippet_from_query_string(self):
        out = self.retrieval.make_snippet(
            self.fx["text"],
            "token gate threshold baseline tokens per finished brief",
            cap=260)
        self.assertEqual(out["snippet"], self.fx["snippet"])

    def test_budget_checked_before_invoking(self):
        with self.assertRaises(C.AdapterBudgetError):
            self.retrieval.make_snippet("text", ["token"], cap=500,
                                        budget_chars=260)

    def test_cursor_resume_and_stale_on_fingerprint_change(self):
        fp = hashlib.sha256(self.fx["text"].encode()).hexdigest()
        out = self.retrieval.snippet_with_cursor(
            "rec-1", self.fx["text"], self.fx["qtokens"], fp, cap=260)
        self.assertEqual(out["snippet"], self.fx["snippet"])
        resumed = self.retrieval.resume_snippet(
            out["cursor"], self.fx["text"], self.fx["qtokens"], fp,
            cap=260)
        self.assertEqual(resumed["record_id"], "rec-1")
        changed = hashlib.sha256(b"different source").hexdigest()
        with self.assertRaises(C.StaleCursorError) as cm:
            self.retrieval.resume_snippet(
                out["cursor"], self.fx["text"], self.fx["qtokens"],
                changed, cap=260)
        self.assertIn("STALE", str(cm.exception))


class AdapterInvariantTest(unittest.TestCase):
    """The recon §7 global invariant: over-budget component output
    fails loudly in the adapter, never silently truncates."""

    def test_resident_stub_oversized_output(self):
        def stub(component, operation, payload):
            return {"packet": "p" * 99999, "bytes": 99999,
                    "inputSha256": "a" * 64}

        resident = C.ResidentAdapter(C.CallableTransport(stub))
        with self.assertRaises(C.AdapterBudgetError):
            resident.compile_packet({"header": {}, "body": "b"})

    def test_retrieval_stub_oversized_output(self):
        def stub(component, operation, payload):
            if operation == "tokenize":
                return {"tokens": ["token"]}
            return {"snippet": "s" * 9999, "est_tokens": 2500}

        retrieval = C.RetrievalAdapter(C.CallableTransport(stub))
        with self.assertRaises(C.AdapterBudgetError):
            retrieval.make_snippet("text", "token", cap=260)


@unittest.skipUnless(LIVE, "live HOME reproduction is env-guarded "
                           "(PAI_SLICE3_LIVE=1); tests must not "
                           "require the network")
class LiveHomeTest(unittest.TestCase):
    def setUp(self):
        self.live = C.LiveNodeTransport()

    def test_live_capsule_ready(self):
        chief = C.ChiefAdapter(self.live)
        fx = load("chief-capsule-ready.json")
        self.assertEqual(chief.build_capsule(fx["input"]), fx["output"])

    def test_live_resident_small(self):
        resident = C.ResidentAdapter(self.live)
        fx = load("resident-packet-compiler.json")
        out = resident.compile_packet(fx["inputs"]["small"])
        self.assertEqual(out["packet"], fx["output"]["small"]["packet"])


if __name__ == "__main__":
    unittest.main()
