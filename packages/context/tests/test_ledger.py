#!/usr/bin/env python3
"""Tests for the Phase 4 Slice 1 usage-ledger core (ledger.py +
rollup.py).

Everything runs on FIXTURE-LOCAL state in temp directories: streams
are written by the production LedgerWriter into a scratch dir, or
tampered with as raw bytes for the broken-chain cases. No test
touches the claim register, the cabinet Registrar registry, or any
production store.

Covers dossier §5 Slice 1 acceptance:
  1. Golden fixture streams validate; schema violations are rejected
     with named reasons (incl. brief_id null without unjoined_reason,
     and a summed/combined token field).
  2. A rollup rebuilt from raw JSONL reproduces identical totals
     twice — byte-identical report output.
  3. The writer is append-only at the API level.
  4. A deliberately broken hash chain is detected and the affected
     rows are named in the rollup output.
  5. reported_tokens and estimated_tokens are never summed — not in
     an event, not in the rollup; estimated rows carry the estimator
     name or are rejected/named.

Run: python3 -m unittest test_ledger -v   (from this directory)
"""
import json
import os
import re
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)
import ledger as L  # noqa: E402
import rollup as R  # noqa: E402

TS = "2026-11-06T10:00:00+00:00"
HASHSET = "a" * 64


def serve_reported(**over):
    ev = {
        "ts": TS, "event_type": "serve", "host": "msi",
        "lane_id": "codex-cp", "run_id": "run-1",
        "brief_id": "brief-001", "consumer": "lane:codex-cp",
        "pack_id": "pack-cmm-basics", "pack_version": 1,
        "requested_key": {"domain": "cmm",
                          "task_type": "nightly production"},
        "outcome": "hit", "derived_level": "house",
        "entitlement_result": "served_full",
        "context_tokens_served": 4200, "token_counter": "char/4",
        "reported_tokens": {"provider": "openai-codex", "input": 1000,
                            "output": 200, "cached_input": 300},
        "old_path_equivalent_tokens": 9000,
        "sources_hash_set_hash": HASHSET,
    }
    ev.update(over)
    return ev


def serve_estimated(**over):
    ev = serve_reported()
    del ev["reported_tokens"]
    ev["outcome"] = "cache_hit"
    ev["estimated_tokens"] = {"value": 500, "estimator": "char/4"}
    ev.update(over)
    return ev


def fallback_unjoined(**over):
    ev = {
        "ts": TS, "event_type": "fallback", "host": "msi",
        "lane_id": "codex-cp", "run_id": "run-2",
        "brief_id": None,
        "unjoined_reason": "ad-hoc lane run; no codex-cp receipt",
        "consumer": "lane:codex-cp",
        "requested_key": {"domain": "cmm",
                          "task_type": "nightly production"},
        "outcome": "miss",
    }
    ev.update(over)
    return ev


def build_golden(tmp):
    """Two host streams. Returns (paths, stored events by stream)."""
    msi_path = os.path.join(tmp, "msi", "usage-ledger.jsonl")
    vm_path = os.path.join(tmp, "vm", "usage-ledger.jsonl")
    w = L.LedgerWriter(msi_path, "msi")
    stored = []
    stored.append(w.append({
        "ts": TS, "event_type": "assemble", "host": "msi",
        "lane_id": "codex-cp", "run_id": "run-1",
        "brief_id": "brief-001", "consumer": "lane:codex-cp",
        "pack_id": "pack-cmm-basics", "pack_version": 1,
        "requested_key": {"domain": "cmm",
                          "task_type": "nightly production"},
    }))
    rep = w.append(serve_reported())
    stored.append(rep)
    stored.append(w.append(serve_estimated()))
    stored.append(w.append(serve_reported(
        brief_id="brief-002", outcome="partial",
        entitlement_result="served_with_exclusions",
        excluded=[{"system": "spine", "id": "rec-9"}],
        reported_tokens={"provider": "openai-codex", "input": 400,
                         "output": 50, "cached_input": 0})))
    stored.append(w.append(fallback_unjoined()))
    stored.append(w.append({
        "ts": TS, "event_type": "correction", "host": "msi",
        "lane_id": "codex-cp", "run_id": "run-1",
        "brief_id": "brief-001",
        "corrects_event_id": rep["event_id"],
        "correction": "cached_input was 30 in the serve row; the "
                      "provider meter reports 300",
    }))
    wv = L.LedgerWriter(vm_path, "vm")
    vm_ev = serve_estimated(host="vm", lane_id="vm-lane")
    del vm_ev["brief_id"]
    vm_ev["brief_id"] = "brief-101"
    vm_stored = [wv.append(vm_ev)]
    return [msi_path, vm_path], stored, vm_stored


# ------------------------------------------------------- acceptance 1

class TestGoldenAndValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ledger-golden-")
        self.paths, self.stored, self.vm_stored = build_golden(self.tmp)

    def test_golden_streams_validate_and_chain_holds(self):
        for path in self.paths:
            stream = L.read_stream(path)
            self.assertEqual(stream["parse_errors"], {})
            self.assertEqual(
                L.verify_chain(stream["lines"], stream["events"]), [])
            for ev in stream["events"]:
                self.assertEqual(L.validate_event(ev, stored=True), [],
                                 f"{ev.get('event_id')}: "
                                 f"{L.validate_event(ev, stored=True)}")

    def test_event_ids_are_host_prefixed_sequence(self):
        self.assertEqual([e["event_id"] for e in self.stored],
                         [f"msi-{i:06d}" for i in range(1, 7)])
        self.assertEqual(self.vm_stored[0]["event_id"], "vm-000001")

    def test_violations_rejected_with_named_reasons(self):
        path = os.path.join(self.tmp, "bad", "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        w.append(serve_reported())
        lines_before = w.line_count

        def without(ev, *keys):
            ev = dict(ev)
            for k in keys:
                ev.pop(k, None)
            return ev

        cases = [
            # brief_id null WITHOUT unjoined_reason named.
            (without(serve_reported(brief_id=None), "unjoined_reason"),
             "unjoined_reason"),
            # A summed/combined token field on an event.
            (serve_reported(total_tokens=1500), "never summed"),
            (serve_reported(combined_tokens=1500), "never summed"),
            # Metered AND estimated on one event.
            (serve_reported(
                estimated_tokens={"value": 1, "estimator": "char/4"}),
             "never both"),
            # Estimate without a named estimator.
            (serve_estimated(estimated_tokens={"value": 10}),
             "estimator"),
            # Counted tokens without a named counter.
            (without(serve_reported(), "token_counter"),
             "token_counter"),
            # Null old-path figure without the named reason.
            (serve_reported(old_path_equivalent_tokens=None),
             "not_computable_reason"),
            # brief_id set AND unjoined_reason set.
            (serve_reported(unjoined_reason="should not be here"),
             "mutually exclusive"),
            # Unknown / illegal values.
            (serve_reported(surprise_field=1), "unknown field"),
            (serve_reported(event_type="delete"), "event_type"),
            (serve_reported(host="moon"), "host"),
            (serve_reported(outcome="vanished"), "outcome"),
            (serve_reported(reported_tokens={
                "provider": "openai-codex", "input": -5,
                "output": 0}), "non-negative"),
            # Type-specific requirements.
            (without(serve_reported(), "pack_id"), "pack_id"),
            (without(fallback_unjoined(), "requested_key"),
             "requested_key"),
            ({"ts": TS, "event_type": "correction", "host": "msi",
              "lane_id": "codex-cp", "run_id": "run-1",
              "correction": "fix stated but no target"},
             "corrects_event_id"),
            (serve_reported(entitlement_result="served_with_exclusions"),
             "excluded"),
        ]
        for cand, needle in cases:
            with self.subTest(needle=needle, cand=sorted(cand)[:3]):
                with self.assertRaises(L.ValidationError) as ctx:
                    w.append(cand)
                self.assertTrue(
                    any(needle in r for r in ctx.exception.reasons),
                    f"expected a reason naming {needle!r}, got "
                    f"{ctx.exception.reasons}")
        # Every rejection wrote nothing.
        self.assertEqual(w.line_count, lines_before)
        stream = L.read_stream(path)
        self.assertEqual(len(stream["lines"]), lines_before)


# ------------------------------------------------------- acceptance 3

class TestAppendOnly(unittest.TestCase):

    def test_writer_api_has_no_mutation_surface(self):
        public = {n for n in dir(L.LedgerWriter) if not n.startswith("_")}
        forbidden = {"update", "delete", "remove", "truncate",
                     "rewrite", "edit", "clear", "purge", "replace",
                     "pop", "discard", "rollback", "undo"}
        self.assertEqual(public & forbidden, set())
        self.assertTrue({"append", "append_many"} <= public)
        for mod in (L, R):
            fns = {n for n in dir(mod) if not n.startswith("_")
                   and callable(getattr(mod, n))}
            self.assertEqual(fns & forbidden, set(),
                             f"{mod.__name__} exposes {fns & forbidden}")

    def test_ledger_source_has_no_write_mode_but_append(self):
        with open(os.path.join(PKG, "ledger.py"),
                  encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"ab"', src)  # the one file mode used for writes
        self.assertIsNone(re.search(r'open\([^)]*,\s*["\']w', src))
        self.assertNotIn("os.remove", src)
        self.assertNotIn(".truncate(", src)

    def test_append_never_alters_prior_bytes(self):
        tmp = tempfile.mkdtemp(prefix="ledger-append-")
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        w.append(serve_reported())
        with open(path, "rb") as f:
            before = f.read()
        w.append(serve_estimated())
        with open(path, "rb") as f:
            after = f.read()
        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))


# ------------------------------------------------- acceptance 2, 4, 5

class TestRollup(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ledger-rollup-")
        self.paths, self.stored, _ = build_golden(self.tmp)

    def test_rebuild_is_byte_identical(self):
        first = R.rollup_report(self.paths)
        second = R.rollup_report(self.paths)
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))
        s1, s2 = R.rollup(self.paths), R.rollup(self.paths)
        self.assertEqual(s1["gate_valid_totals"],
                         s2["gate_valid_totals"])

    def test_totals_and_strata(self):
        s = R.rollup(self.paths)
        t = s["gate_valid_totals"]
        self.assertEqual(t["events"], 7)
        # Reported stratum: the two metered serves only.
        self.assertEqual(t["reported"]["events"], 2)
        self.assertEqual(t["reported"]["input"], 1400)
        self.assertEqual(t["reported"]["output"], 250)
        self.assertEqual(t["reported"]["cached_input"], 300)
        # Estimated stratum: separate, keyed by the estimator name.
        self.assertEqual(t["estimated"]["events"], 2)
        self.assertEqual(t["estimated"]["by_estimator"],
                         {"char/4": {"events": 2, "value": 1000}})
        # Per-brief join: brief-001 carries one reported + one
        # estimated event, in separate strata.
        b1 = s["per_brief"]["brief-001"]
        self.assertEqual(b1["reported"]["input"], 1000)
        self.assertEqual(b1["estimated"]["by_estimator"]["char/4"]
                         ["value"], 500)
        # Per-pack / per-class views exist.
        self.assertEqual(
            s["per_pack"]["pack-cmm-basics@v1"]["reported"]["input"],
            1400)
        self.assertIn("cmm/nightly production", s["per_class"])

    def test_no_combined_token_figure_anywhere(self):
        s = R.rollup(self.paths)
        bad_keys = {"total_tokens", "combined_tokens", "tokens_total",
                    "grand_total_tokens", "all_tokens"}

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    self.assertNotIn(k, bad_keys)
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(s)
        self.assertNotIn("total_tokens", R.render_report(s))

    def test_unjoined_and_corrections_are_named(self):
        s = R.rollup(self.paths)
        self.assertEqual(len(s["unjoined"]), 1)
        self.assertEqual(s["unjoined"][0]["unjoined_reason"],
                         "ad-hoc lane run; no codex-cp receipt")
        self.assertEqual(len(s["corrections"]), 1)
        corr = s["corrections"][0]
        self.assertEqual(corr["corrects_event_id"],
                         self.stored[1]["event_id"])
        self.assertTrue(corr["target_found"])

    def test_correction_to_unknown_target_is_named_not_dropped(self):
        w = L.LedgerWriter(self.paths[0], "msi")
        w.append({
            "ts": TS, "event_type": "correction", "host": "msi",
            "lane_id": "codex-cp", "run_id": "run-9",
            "corrects_event_id": "msi-999999",
            "correction": "points at an event that does not exist",
        })
        s = R.rollup(self.paths)
        orphan = [c for c in s["corrections"]
                  if c["corrects_event_id"] == "msi-999999"]
        self.assertEqual(len(orphan), 1)
        self.assertFalse(orphan[0]["target_found"])


class TestBrokenChain(unittest.TestCase):

    def _four_serves(self, tmp):
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        stored = [w.append(serve_reported(brief_id=f"brief-00{i}"))
                  for i in range(1, 5)]
        return path, stored

    def _rewrite_line(self, path, idx, mutate):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        lines[idx] = mutate(lines[idx])
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines) + "\n")

    def test_tampered_content_detected_rows_named_stream_excluded(self):
        tmp = tempfile.mkdtemp(prefix="ledger-broken-")
        path, stored = self._four_serves(tmp)
        # Tamper with line 2's payload (its own prev_hash still
        # matches line 1, so the break surfaces at line 3).
        self._rewrite_line(path, 1, lambda ln: ln.replace("4200",
                                                          "9999"))
        s = R.rollup([path])
        entry = s["streams"][0]
        self.assertFalse(entry["chain_ok"])
        self.assertFalse(entry["gate_valid"])
        self.assertEqual([b["line"] for b in entry["chain_breaks"]],
                         [3])
        # Gate-valid totals exclude the whole stream.
        self.assertEqual(s["gate_valid_totals"]["events"], 0)
        # Affected rows named: lines 2 and 3.
        excl = s["excluded_streams"][0]
        self.assertEqual(excl["affected_event_ids"],
                         [stored[1]["event_id"], stored[2]["event_id"]])
        self.assertEqual(len(excl["event_ids"]), 4)
        self.assertIn("line(s) 3", excl["reason"])

    def test_tampered_prev_hash_detected_at_that_line(self):
        tmp = tempfile.mkdtemp(prefix="ledger-broken2-")
        path, stored = self._four_serves(tmp)

        def forge(ln):
            ev = json.loads(ln)
            ev["prev_hash"] = "0" * 64
            return json.dumps(ev)
        self._rewrite_line(path, 1, forge)
        s = R.rollup([path])
        entry = s["streams"][0]
        # Forging line 2's prev_hash breaks line 2's own link AND
        # line 3's link (line 3 chains to line 2's original bytes).
        self.assertEqual([b["line"] for b in entry["chain_breaks"]],
                         [2, 3])
        self.assertEqual(s["excluded_streams"][0]["affected_event_ids"],
                         [stored[0]["event_id"], stored[1]["event_id"],
                          stored[2]["event_id"]])

    def test_writer_refuses_to_extend_a_broken_stream(self):
        tmp = tempfile.mkdtemp(prefix="ledger-broken3-")
        path, _ = self._four_serves(tmp)
        self._rewrite_line(path, 0, lambda ln: ln.replace("4200",
                                                          "9999"))
        with self.assertRaises(L.LedgerError):
            L.LedgerWriter(path, "msi")

    def test_invalid_row_named_without_condemning_stream(self):
        tmp = tempfile.mkdtemp(prefix="ledger-invalidrow-")
        path, stored = self._four_serves(tmp)
        # Rewrite line 4 as a schema-valid-JSON but invalid event by
        # re-chaining it honestly: easier to append a bad line through
        # raw bytes and accept the chain break is NOT what we test —
        # instead corrupt only a field the chain cannot see is wrong:
        # change outcome to an illegal value AND fix nothing else;
        # chain breaks too, so assert on the invalid_rows naming.
        def corrupt(ln):
            ev = json.loads(ln)
            ev["outcome"] = "vanished"
            return L.serialize_event(ev)
        self._rewrite_line(path, 3, corrupt)
        s = R.rollup([path])
        invalid = s["streams"][0]["invalid_rows"]
        named = [r for r in invalid
                 if r["event_id"] == stored[3]["event_id"]]
        self.assertEqual(len(named), 1)
        self.assertTrue(any("outcome" in r for r in named[0]["reasons"]))


# ------------------------------------------- fix round 1 (F1–F8)

def write_raw_stream(path, events):
    """Handcraft a chain-valid stream as raw bytes (bypasses the
    writer, the reviewer's probe method): each event gets the
    correct prev_hash for its position. NO head sidecar is written,
    unless a test adds one via the writer."""
    os.makedirs(os.path.dirname(os.path.abspath(path)),
                exist_ok=True)
    head = L.GENESIS_HASH
    lines = []
    for ev in events:
        ev = dict(ev)
        ev["prev_hash"] = head
        line = L.serialize_event(ev)
        lines.append(line)
        head = L.line_hash(line.encode("utf-8"))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    return path


def structured_correction(target, cset, **over):
    ev = {
        "ts": TS, "event_type": "correction", "host": "msi",
        "lane_id": "codex-cp", "run_id": "run-9",
        "corrects_event_id": target,
        "correction": "structured correction (fix round 1, F3)",
        "corrects": {"target_event_id": target, "set": cset},
    }
    ev.update(over)
    return ev


class TestHeadCommitmentF1(unittest.TestCase):

    def _four_serves(self, tmp):
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        stored = [w.append(serve_reported(brief_id=f"brief-00{i}"))
                  for i in range(1, 5)]
        return path, w, stored

    def test_sidecar_written_and_consistent_no_warning(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f1-")
        path, w, stored = self._four_serves(tmp)
        sidecar = L.head_sidecar_path(path)
        self.assertTrue(os.path.exists(sidecar))
        with open(sidecar, encoding="utf-8") as f:
            commitment = json.load(f)
        self.assertEqual(commitment["head_hash"], w.head_hash)
        self.assertEqual(commitment["line_count"], 4)
        self.assertEqual(commitment["last_event_id"],
                         stored[-1]["event_id"])
        self.assertEqual(commitment["host"], "msi")
        s = R.rollup([path])
        self.assertEqual(s["streams"][0]["head_commitment"], "ok")
        self.assertEqual(s["tail_uncommitted"], [])
        self.assertEqual(s["excluded_streams"], [])
        self.assertEqual(s["gate_valid_totals"]["events"], 4)

    def test_tail_content_tamper_detected_excluded_named(self):
        # Reviewer P10 shape: last line's reported input 1000 ->
        # 999999; the hash chain alone stays ok.
        tmp = tempfile.mkdtemp(prefix="ledger-f1b-")
        path, _, _ = self._four_serves(tmp)
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertIn('"input": 1000', lines[-1])
        lines[-1] = lines[-1].replace('"input": 1000',
                                      '"input": 999999')
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines) + "\n")
        s = R.rollup([path])
        self.assertTrue(s["streams"][0]["chain_ok"])  # chain blind
        self.assertEqual(s["gate_valid_totals"]["events"], 0)
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 0)
        excl = s["excluded_streams"][0]
        self.assertEqual(excl["reason"], "head_commitment_mismatch")
        self.assertEqual(excl["expected"]["line_count"], 4)
        self.assertEqual(excl["actual"]["line_count"], 4)
        self.assertNotEqual(excl["expected"]["head_hash"],
                            excl["actual"]["head_hash"])

    def test_tail_truncation_detected_excluded_named(self):
        # Reviewer P11 shape: last line deleted.
        tmp = tempfile.mkdtemp(prefix="ledger-f1c-")
        path, _, _ = self._four_serves(tmp)
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines[:-1]) + "\n")
        s = R.rollup([path])
        self.assertEqual(s["gate_valid_totals"]["events"], 0)
        excl = s["excluded_streams"][0]
        self.assertEqual(excl["reason"], "head_commitment_mismatch")
        self.assertEqual(excl["expected"]["line_count"], 4)
        self.assertEqual(excl["actual"]["line_count"], 3)

    def test_no_sidecar_folds_but_named_tail_uncommitted(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f1d-")
        path, _, _ = self._four_serves(tmp)
        os.remove(L.head_sidecar_path(path))
        s = R.rollup([path])
        self.assertEqual(s["gate_valid_totals"]["events"], 4)
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 4000)
        self.assertEqual([e["path"] for e in s["tail_uncommitted"]],
                         [path])
        self.assertEqual(s["streams"][0]["head_commitment"],
                         "missing")


class TestDuplicatesAndSequenceF2(unittest.TestCase):

    def test_duplicate_event_id_in_stream_excluded_named(self):
        # Reviewer P14 shape: two lines, both msi-000001.
        tmp = tempfile.mkdtemp(prefix="ledger-f2-")
        path = write_raw_stream(os.path.join(tmp, "s.jsonl"), [
            serve_reported(event_id="msi-000001"),
            serve_reported(event_id="msi-000001"),
        ])
        s = R.rollup([path])
        self.assertEqual(s["gate_valid_totals"]["events"], 1)
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 1000)
        self.assertEqual(len(s["duplicate_event_ids"]), 1)
        dup = s["duplicate_event_ids"][0]
        self.assertEqual(dup["event_id"], "msi-000001")
        self.assertEqual(dup["stream"], path)
        self.assertEqual(dup["line"], 2)
        self.assertEqual(s["sequence_warnings"], [])

    def test_duplicate_event_id_across_streams(self):
        # Reviewer P22 shape: same event_id in two same-host files.
        tmp = tempfile.mkdtemp(prefix="ledger-f2b-")
        p1 = write_raw_stream(os.path.join(tmp, "a.jsonl"),
                              [serve_reported(
                                  event_id="msi-000001")])
        p2 = write_raw_stream(os.path.join(tmp, "b.jsonl"),
                              [serve_reported(
                                  event_id="msi-000001")])
        s = R.rollup([p1, p2])
        self.assertEqual(s["gate_valid_totals"]["events"], 1)
        self.assertEqual(len(s["duplicate_event_ids"]), 1)
        self.assertEqual(s["duplicate_event_ids"][0]["stream"], p2)
        self.assertEqual(
            s["per_brief"]["brief-001"]["event_ids"], ["msi-000001"])

    def test_non_monotonic_sequence_named_but_folds(self):
        # Reviewer P23 shape: msi-000020 then msi-000003.
        tmp = tempfile.mkdtemp(prefix="ledger-f2c-")
        path = write_raw_stream(os.path.join(tmp, "s.jsonl"), [
            serve_reported(event_id="msi-000020"),
            serve_reported(event_id="msi-000003"),
        ])
        s = R.rollup([path])
        self.assertEqual(s["gate_valid_totals"]["events"], 2)
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 2000)
        self.assertEqual(len(s["sequence_warnings"]), 1)
        warn = s["sequence_warnings"][0]
        self.assertEqual(warn["event_id"], "msi-000003")
        self.assertEqual(warn["stream"], path)
        self.assertEqual(warn["line"], 2)


class TestStructuredCorrectionsF3(unittest.TestCase):

    def _serve_stream(self, tmp):
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        target = w.append(serve_reported())
        return path, w, target

    def test_correction_applied_totals_recomputed(self):
        # Reviewer P13 shape: serve input 1000 -> correction sets
        # the reported figure to input 10; totals become 10.
        tmp = tempfile.mkdtemp(prefix="ledger-f3-")
        path, w, target = self._serve_stream(tmp)
        w.append(structured_correction(target["event_id"], {
            "reported_tokens": {"provider": "openai-codex",
                                "input": 10, "output": 200,
                                "cached_input": 300}}))
        s = R.rollup([path])
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 10)
        entry = s["corrections"][0]
        self.assertTrue(entry["target_found"])
        self.assertTrue(entry["applied"])
        self.assertEqual(entry["before"]["reported_tokens"]
                         ["input"], 1000)
        self.assertEqual(entry["after"]["reported_tokens"]
                         ["input"], 10)

    def test_never_both_correction_named_not_applied(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f3b-")
        path, w, target = self._serve_stream(tmp)
        w.append(structured_correction(target["event_id"], {
            "estimated_tokens": {"value": 5,
                                 "estimator": "char/4"}}))
        s = R.rollup([path])
        entry = s["corrections"][0]
        self.assertFalse(entry["applied"])
        self.assertIn("both", entry["not_applied_reason"])
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 1000)
        self.assertEqual(s["gate_valid_totals"]["estimated"]
                         ["events"], 0)

    def test_set_with_both_fields_rejected_by_validator(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f3c-")
        path, w, target = self._serve_stream(tmp)
        with self.assertRaises(L.ValidationError):
            w.append(structured_correction(target["event_id"], {
                "reported_tokens": {"provider": "openai-codex",
                                    "input": 1, "output": 1},
                "estimated_tokens": {"value": 1,
                                     "estimator": "char/4"}}))
        self.assertEqual(w.line_count, 1)

    def test_two_corrections_same_target_deterministic(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f3d-")
        path, w, target = self._serve_stream(tmp)
        rep = {"provider": "openai-codex", "output": 200,
               "cached_input": 300}
        c1 = w.append(structured_correction(target["event_id"], {
            "reported_tokens": dict(rep, input=100),
            "context_tokens_served": 50}))
        c2 = w.append(structured_correction(target["event_id"], {
            "reported_tokens": dict(rep, input=7)}))
        s = R.rollup([path])
        # Later supersedes earlier per-field: input 7 wins;
        # context_tokens_served keeps correction 1's 50.
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 7)
        self.assertEqual(s["gate_valid_totals"]
                         ["context_tokens_served"], 50)
        self.assertEqual([c["event_id"] for c in s["corrections"]],
                         [c1["event_id"], c2["event_id"]])
        self.assertTrue(all(c["applied"]
                            for c in s["corrections"]))

    def test_structured_correction_unknown_target_named(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f3e-")
        path, w, _ = self._serve_stream(tmp)
        w.append(structured_correction("msi-999999", {
            "reported_tokens": {"provider": "openai-codex",
                                "input": 1, "output": 1}}))
        s = R.rollup([path])
        entry = s["corrections"][0]
        self.assertFalse(entry["target_found"])
        self.assertFalse(entry["applied"])
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 1000)


class TestCorrectionKindSlice4F2(unittest.TestCase):
    """Slice 4 fix F2 (additive, cross-slice delta on Slice 1):
    corrects.kind in {error_fix, late_accounting}; absent means
    error_fix. Valid kinds are accepted and preserved; an
    out-of-vocabulary kind is rejected with a named reason;
    rollup surfaces kind (defaulting absent to error_fix)."""

    def _serve_stream(self, tmp):
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        target = w.append(serve_reported())
        return path, w, target

    @staticmethod
    def _corr(target_id, kind="__absent__"):
        ev = structured_correction(target_id, {
            "reported_tokens": {"provider": "openai-codex",
                                "input": 10, "output": 200,
                                "cached_input": 300}})
        if kind != "__absent__":
            ev["corrects"]["kind"] = kind
        return ev

    def test_valid_kinds_accepted_and_preserved(self):
        for kind in ("error_fix", "late_accounting"):
            with self.subTest(kind=kind):
                tmp = tempfile.mkdtemp(prefix="ledger-kind-")
                path, w, target = self._serve_stream(tmp)
                stored = w.append(
                    self._corr(target["event_id"], kind))
                self.assertEqual(
                    stored["corrects"]["kind"], kind)
                self.assertEqual(
                    L.validate_event(stored, stored=True), [])
                stream = L.read_stream(path)
                self.assertEqual(
                    stream["events"][-1]["corrects"]["kind"],
                    kind)

    def test_absent_kind_accepted_backward_compatible(self):
        tmp = tempfile.mkdtemp(prefix="ledger-kind-absent-")
        path, w, target = self._serve_stream(tmp)
        stored = w.append(self._corr(target["event_id"]))
        self.assertNotIn("kind", stored["corrects"])
        self.assertEqual(L.validate_event(stored, stored=True),
                         [])

    def test_out_of_vocabulary_kind_rejected_named(self):
        tmp = tempfile.mkdtemp(prefix="ledger-kind-bad-")
        path, w, target = self._serve_stream(tmp)
        with self.assertRaises(L.ValidationError) as ctx:
            w.append(self._corr(target["event_id"], "oops"))
        self.assertTrue(
            any("corrects.kind" in r
                for r in ctx.exception.reasons),
            ctx.exception.reasons)
        self.assertEqual(w.line_count, 1)

    def test_rollup_surfaces_kind_defaulting_absent(self):
        tmp = tempfile.mkdtemp(prefix="ledger-kind-rollup-")
        path, w, target = self._serve_stream(tmp)
        w.append(self._corr(target["event_id"],
                            "late_accounting"))
        s = R.rollup([path])
        self.assertEqual(s["corrections"][0]["kind"],
                         "late_accounting")
        self.assertTrue(s["corrections"][0]["applied"])
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 10)
        tmp2 = tempfile.mkdtemp(prefix="ledger-kind-rollup2-")
        path2, w2, target2 = self._serve_stream(tmp2)
        w2.append(self._corr(target2["event_id"]))
        s2 = R.rollup([path2])
        self.assertEqual(s2["corrections"][0]["kind"],
                         "error_fix")


class TestConsumerClosedF4(unittest.TestCase):

    def test_total_tokens_in_consumer_rejected(self):
        # Reviewer P3b/P24 shape.
        tmp = tempfile.mkdtemp(prefix="ledger-f4-")
        w = L.LedgerWriter(os.path.join(tmp, "s.jsonl"), "msi")
        with self.assertRaises(L.ValidationError) as ctx:
            w.append(serve_reported(
                consumer={"identity": "lane:x",
                          "total_tokens": 999999}))
        self.assertTrue(any("consumer has unknown keys" in r
                            for r in ctx.exception.reasons))
        self.assertEqual(w.line_count, 0)

    def test_consumer_entitlement_context_keys_accepted(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f4b-")
        w = L.LedgerWriter(os.path.join(tmp, "s.jsonl"), "msi")
        stored = w.append(serve_reported(
            consumer={"identity": "lane:x", "max_level": "house"}))
        self.assertEqual(stored["consumer"]["max_level"], "house")


class TestMintingF5(unittest.TestCase):

    def test_mint_after_supplied_000002_is_000003(self):
        # Reviewer P8 shape 1: no bricking.
        tmp = tempfile.mkdtemp(prefix="ledger-f5-")
        w = L.LedgerWriter(os.path.join(tmp, "s.jsonl"), "msi")
        w.append(serve_reported(event_id="msi-000002"))
        nxt = w.append(serve_estimated())
        self.assertEqual(nxt["event_id"], "msi-000003")

    def test_mint_after_supplied_000100_is_000101(self):
        # Reviewer P8 shape 2: no backward sequence.
        tmp = tempfile.mkdtemp(prefix="ledger-f5b-")
        w = L.LedgerWriter(os.path.join(tmp, "s.jsonl"), "msi")
        w.append(serve_reported(event_id="msi-000100"))
        nxt = w.append(serve_estimated())
        self.assertEqual(nxt["event_id"], "msi-000101")

    def test_sequence_0000_rejected(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f5c-")
        w = L.LedgerWriter(os.path.join(tmp, "s.jsonl"), "msi")
        with self.assertRaises(L.ValidationError) as ctx:
            w.append(serve_reported(event_id="msi-000000"))
        self.assertTrue(any("0000" in r
                            for r in ctx.exception.reasons))
        self.assertEqual(w.line_count, 0)


class TestPrevHashRejectedF6(unittest.TestCase):

    def test_caller_supplied_prev_hash_rejected_not_stripped(self):
        # Reviewer P6 shape: the validator's documented contract
        # wins; the writer must not silently strip prev_hash.
        tmp = tempfile.mkdtemp(prefix="ledger-f6-")
        w = L.LedgerWriter(os.path.join(tmp, "s.jsonl"), "msi")
        w.append(serve_reported())
        with self.assertRaises(L.ValidationError) as ctx:
            w.append(serve_reported(prev_hash="0" * 64))
        self.assertTrue(any("prev_hash is writer-managed" in r
                            for r in ctx.exception.reasons))
        self.assertEqual(w.line_count, 1)


class TestReportNotesF7F8(unittest.TestCase):

    def test_f7_paths_are_input_identity_documented(self):
        self.assertIn("input identity", R.__doc__)
        self.assertIn("ORDERED", R.__doc__)

    def test_f8_note_line_when_streams_excluded(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f8-")
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        for i in range(1, 5):
            w.append(serve_reported(brief_id=f"brief-00{i}"))
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        lines[1] = lines[1].replace("4200", "9999")  # chain break
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines) + "\n")
        s = R.rollup([path])
        self.assertEqual(len(s["excluded_streams"]), 1)
        report = R.render_report(s)
        self.assertIn("does not include events from excluded "
                      "streams", report)
        parsed = json.loads(report)  # report stays valid JSON
        self.assertIn("note", parsed)

    def test_f8_no_note_when_nothing_excluded(self):
        tmp = tempfile.mkdtemp(prefix="ledger-f8b-")
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        w.append(serve_reported())
        parsed = json.loads(R.rollup_report([path]))
        self.assertNotIn("note", parsed)


# ------------------------------------------- fix round 2 (R1–R5)

class TestWriterHeadGateR1(unittest.TestCase):
    """R1: a writer opened over an existing stream must never
    launder a head-commitment mismatch by appending + rewriting the
    sidecar. Only the exact-prefix crash window heals."""

    def _four_serves(self, tmp):
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        stored = [w.append(serve_reported(brief_id=f"brief-00{i}"))
                  for i in range(1, 5)]
        return path, stored

    def _bytes(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_tampered_tail_writer_refuses_no_laundering(self):
        # Re-reviewer's shape: tamper the tail, then open a writer.
        tmp = tempfile.mkdtemp(prefix="ledger-r1-")
        path, _ = self._four_serves(tmp)
        sidecar = L.head_sidecar_path(path)
        with open(sidecar, encoding="utf-8") as f:
            committed_head = json.load(f)["head_hash"]
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        lines[-1] = lines[-1].replace('"input": 1000',
                                      '"input": 999999')
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines) + "\n")
        stream_bytes = self._bytes(path)
        sidecar_bytes = self._bytes(sidecar)
        with self.assertRaises(L.LedgerError) as ctx:
            L.LedgerWriter(path, "msi")
        self.assertIn("head-commitment mismatch",
                      str(ctx.exception))
        # No append, no sidecar write: both files untouched.
        self.assertEqual(self._bytes(path), stream_bytes)
        self.assertEqual(self._bytes(sidecar), sidecar_bytes)
        # Rollup still reports the ORIGINAL mismatch; the gate
        # figure is unchanged (0 events fold).
        s = R.rollup([path])
        self.assertEqual(s["gate_valid_totals"]["events"], 0)
        excl = s["excluded_streams"][0]
        self.assertEqual(excl["reason"], "head_commitment_mismatch")
        self.assertEqual(excl["expected"]["head_hash"],
                         committed_head)

    def test_truncated_stream_writer_refuses_no_id_reuse(self):
        # Truncation + writer-open previously re-minted msi-000004
        # for a different event; now the open itself refuses.
        tmp = tempfile.mkdtemp(prefix="ledger-r1b-")
        path, _ = self._four_serves(tmp)
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines[:-1]) + "\n")
        with self.assertRaises(L.LedgerError):
            L.LedgerWriter(path, "msi")
        self.assertEqual(len(self._bytes(path).splitlines()), 3)

    def test_crash_window_prefix_sidecar_heals(self):
        # Stream fsync landed, sidecar replace did not: hand-append
        # a chain-valid 4th line over a writer that stopped at 3.
        tmp = tempfile.mkdtemp(prefix="ledger-r1c-")
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        for i in range(1, 4):
            w.append(serve_reported(brief_id=f"brief-00{i}"))
        ev = serve_reported(brief_id="brief-004",
                            event_id="msi-000004")
        ev["prev_hash"] = w.head_hash
        line = L.serialize_event(ev)
        with open(path, "ab") as f:
            f.write(line.encode("utf-8") + b"\n")
        # Sidecar is now a stale but EXACT PREFIX state (3 lines).
        w2 = L.LedgerWriter(path, "msi")
        self.assertTrue(w2.healed)
        self.assertFalse(w2.adopted)
        self.assertEqual(w2.line_count, 4)
        nxt = w2.append(serve_reported(brief_id="brief-005"))
        self.assertEqual(nxt["event_id"], "msi-000005")
        s = R.rollup([path])
        self.assertEqual(s["streams"][0]["head_commitment"], "ok")
        self.assertEqual(s["gate_valid_totals"]["events"], 5)
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 5000)

    def test_no_sidecar_nonempty_stream_refuses_without_optin(self):
        tmp = tempfile.mkdtemp(prefix="ledger-r1d-")
        path = write_raw_stream(os.path.join(tmp, "s.jsonl"), [
            serve_reported(event_id="msi-000001"),
            serve_reported(event_id="msi-000002"),
        ])
        self.assertFalse(os.path.exists(L.head_sidecar_path(path)))
        with self.assertRaises(L.LedgerError) as ctx:
            L.LedgerWriter(path, "msi")
        self.assertIn("adopt_uncommitted", str(ctx.exception))
        # Still no sidecar: the refusal wrote nothing.
        self.assertFalse(os.path.exists(L.head_sidecar_path(path)))

    def test_no_sidecar_adoption_optin_recorded_and_named(self):
        tmp = tempfile.mkdtemp(prefix="ledger-r1e-")
        path = write_raw_stream(os.path.join(tmp, "s.jsonl"), [
            serve_reported(event_id="msi-000001"),
            serve_reported(event_id="msi-000002"),
        ])
        w = L.LedgerWriter(path, "msi", adopt_uncommitted=True)
        self.assertTrue(w.adopted)
        self.assertFalse(w.healed)
        with open(L.head_sidecar_path(path), encoding="utf-8") as f:
            commitment = json.load(f)
        self.assertTrue(commitment["adopted"])
        self.assertEqual(commitment["adopted_at_line_count"], 2)
        self.assertEqual(commitment["line_count"], 2)
        self.assertEqual(commitment["head_hash"], w.head_hash)
        # Post-adoption appends verify against the adopted head.
        w.append(serve_reported())
        s = R.rollup([path])
        self.assertEqual(s["gate_valid_totals"]["events"], 3)
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 3000)
        self.assertEqual(s["streams"][0]["head_commitment"], "ok")
        self.assertEqual(len(s["tail_uncommitted"]), 1)
        named = s["tail_uncommitted"][0]
        self.assertEqual(named["path"], path)
        self.assertIn("adopted history", named["reason"])
        self.assertEqual(named["adopted_at_line_count"], 2)

    def test_corrupt_sidecar_writer_refuses(self):
        tmp = tempfile.mkdtemp(prefix="ledger-r1f-")
        path, _ = self._four_serves(tmp)
        with open(L.head_sidecar_path(path), "w",
                  encoding="utf-8", newline="") as f:
            f.write("not json{{{")
        stream_bytes = self._bytes(path)
        with self.assertRaises(L.LedgerError):
            L.LedgerWriter(path, "msi")
        self.assertEqual(self._bytes(path), stream_bytes)


class TestCorrectionTargetsR2(unittest.TestCase):
    """R2: corrections never target corrections — the validator
    rejects self-reference; the rollup names (never applies) any
    correction whose target is a correction event."""

    def test_validator_rejects_self_correction(self):
        tmp = tempfile.mkdtemp(prefix="ledger-r2-")
        path = os.path.join(tmp, "s.jsonl")
        w = L.LedgerWriter(path, "msi")
        w.append(serve_reported())
        cand = structured_correction(
            "msi-000777",
            {"reported_tokens": {"provider": "openai-codex",
                                 "input": 424242, "output": 1,
                                 "cached_input": 0}},
            event_id="msi-000777")
        with self.assertRaises(L.ValidationError) as ctx:
            w.append(cand)
        self.assertTrue(any("targets itself" in r
                            for r in ctx.exception.reasons),
                        ctx.exception.reasons)
        self.assertEqual(w.line_count, 1)

    def test_correction_targeting_correction_named_not_applied(self):
        # Re-reviewer's fabrication probe: C2 sets
        # context_tokens_served 999 on C1 (a correction). Handcrafted
        # stream bypassing the writer.
        tmp = tempfile.mkdtemp(prefix="ledger-r2b-")
        rep = {"provider": "openai-codex", "output": 200,
               "cached_input": 300}
        path = write_raw_stream(os.path.join(tmp, "s.jsonl"), [
            serve_reported(event_id="msi-000001"),
            structured_correction(
                "msi-000001",
                {"reported_tokens": dict(rep, input=100)},
                event_id="msi-000002"),
            structured_correction(
                "msi-000002", {"context_tokens_served": 999},
                event_id="msi-000003"),
        ])
        s = R.rollup([path])
        # Honest figures only: C1 applied (input 100), the serve's
        # own ctx 4200 stands, the minted 999 never lands.
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 100)
        self.assertEqual(s["gate_valid_totals"]
                         ["context_tokens_served"], 4200)
        by_id = {c["event_id"]: c for c in s["corrections"]}
        self.assertTrue(by_id["msi-000002"]["applied"])
        self.assertFalse(by_id["msi-000003"]["applied"])
        self.assertIn("target_is_correction",
                      by_id["msi-000003"]["not_applied_reason"])

    def test_self_correction_handcrafted_named_not_applied(self):
        # Re-reviewer's fabrication probe: a self-correction minting
        # reported input 424242, in a stream that bypassed the writer.
        tmp = tempfile.mkdtemp(prefix="ledger-r2c-")
        path = write_raw_stream(os.path.join(tmp, "s.jsonl"), [
            serve_reported(event_id="msi-000001"),
            structured_correction(
                "msi-000002",
                {"reported_tokens": {"provider": "openai-codex",
                                     "input": 424242, "output": 1,
                                     "cached_input": 0}},
                event_id="msi-000002"),
        ])
        s = R.rollup([path])
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 1000)
        entry = s["corrections"][0]
        self.assertEqual(entry["event_id"], "msi-000002")
        self.assertTrue(entry["target_found"])
        self.assertFalse(entry["applied"])
        self.assertIn("target_is_correction",
                      entry["not_applied_reason"])


class TestPerBriefCtxR3(unittest.TestCase):

    def test_per_brief_carries_context_tokens_served(self):
        # R3: per-brief was the one token-carrying view with no
        # context_tokens_served, so a correction to it was invisible
        # there. Now every view agrees.
        tmp = tempfile.mkdtemp(prefix="ledger-r3-")
        path = os.path.join(tmp, "s.jsonl")
        w = L.LedgerWriter(path, "msi")
        target = w.append(serve_reported())
        w.append(structured_correction(
            target["event_id"], {"context_tokens_served": 111}))
        s = R.rollup([path])
        self.assertEqual(s["gate_valid_totals"]
                         ["context_tokens_served"], 111)
        self.assertEqual(s["per_pack"]["pack-cmm-basics@v1"]
                         ["context_tokens_served"], 111)
        self.assertEqual(
            list(s["per_class"].values())[0]
            ["context_tokens_served"], 111)
        self.assertEqual(s["per_brief"]["brief-001"]
                         ["context_tokens_served"], 111)


class TestSidecarLastEventIdR5(unittest.TestCase):

    def test_last_event_id_only_tamper_is_mismatch(self):
        # R5: hash + line_count intact but last_event_id forged —
        # previously folded as head "ok"; now a named mismatch.
        tmp = tempfile.mkdtemp(prefix="ledger-r5-")
        path = os.path.join(tmp, "s.jsonl")
        w = L.LedgerWriter(path, "msi")
        w.append(serve_reported())
        sidecar = L.head_sidecar_path(path)
        with open(sidecar, encoding="utf-8") as f:
            commitment = json.load(f)
        commitment["last_event_id"] = "msi-999999"
        with open(sidecar, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(commitment, sort_keys=True) + "\n")
        s = R.rollup([path])
        self.assertEqual(s["streams"][0]["head_commitment"],
                         "mismatch")
        self.assertEqual(s["gate_valid_totals"]["events"], 0)
        self.assertEqual(s["excluded_streams"][0]["reason"],
                         "head_commitment_mismatch")


class TestDurableHealMarkersFix3(unittest.TestCase):
    """Fix round 3: a crash-window heal leaves a DURABLE trace — a
    `heals` entry in the sidecar, carried forward on later rewrites,
    and the rollup names the stream in `healed_streams` while still
    folding it. Mirrors the adoption marker pattern (R1)."""

    def _hand_append(self, path, writer, event_id, **over):
        ev = serve_reported(event_id=event_id, **over)
        ev["prev_hash"] = writer.head_hash
        line = L.serialize_event(ev)
        with open(path, "ab") as f:
            f.write(line.encode("utf-8") + b"\n")
        return line

    def _sidecar(self, path):
        with open(L.head_sidecar_path(path), encoding="utf-8") as f:
            return json.load(f)

    def test_probe_c_forged_line_heals_but_is_named(self):
        # Re-review probe C shape: sidecar stale at 3, a
        # hand-appended chain-valid line 4 carries a forged
        # reported input of 555555. The heal is legitimate recovery
        # (the stream folds) but must never be silent again.
        tmp = tempfile.mkdtemp(prefix="ledger-fix3-")
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        for i in range(1, 4):
            w.append(serve_reported(brief_id=f"brief-00{i}"))
        forged_line = self._hand_append(
            path, w, "msi-000004", brief_id="brief-004",
            reported_tokens={"provider": "openai-codex",
                             "input": 555555, "output": 200,
                             "cached_input": 300})
        forged_hash = L.line_hash(forged_line.encode("utf-8"))
        w2 = L.LedgerWriter(path, "msi")
        self.assertTrue(w2.healed)
        self.assertEqual(w2.line_count, 4)
        # A subsequent append must not erase the heal marker.
        nxt = w2.append(serve_reported(brief_id="brief-005"))
        self.assertEqual(nxt["event_id"], "msi-000005")
        commitment = self._sidecar(path)
        self.assertEqual(commitment["line_count"], 5)
        self.assertEqual(len(commitment["heals"]), 1)
        heal = commitment["heals"][0]
        self.assertEqual(heal["healed_at_line_count"], 3)
        self.assertEqual(heal["stream_lines_at_heal"], 4)
        self.assertEqual(heal["healed_head_hash"], forged_hash)
        # Rollup folds the forged figures (558555 + the honest
        # post-heal append's 1000) BUT names the stream.
        s = R.rollup([path])
        self.assertEqual(s["streams"][0]["head_commitment"], "ok")
        self.assertEqual(s["gate_valid_totals"]["events"], 5)
        self.assertEqual(
            s["gate_valid_totals"]["reported"]["input"], 559555)
        self.assertEqual(len(s["healed_streams"]), 1)
        named = s["healed_streams"][0]
        self.assertEqual(named["path"], path)
        self.assertEqual(named["heal_count"], 1)
        self.assertEqual(named["heals"][0]["healed_at_line_count"], 3)
        self.assertEqual(named["heals"][0]["stream_lines_at_heal"], 4)
        self.assertEqual(named["healed_at_line_counts"], [3])
        self.assertEqual(named["stream_lines_at_heal"], [4])
        # The rendered report names it too.
        rendered = json.loads(R.render_report(s))
        self.assertEqual(len(rendered["healed_streams"]), 1)
        self.assertEqual(
            rendered["healed_streams"][0]["heal_count"], 1)

    def test_no_heal_stream_has_empty_healed_streams(self):
        tmp = tempfile.mkdtemp(prefix="ledger-fix3b-")
        path = os.path.join(tmp, "s.jsonl")
        w = L.LedgerWriter(path, "msi")
        w.append(serve_reported())
        w.append(serve_reported())
        self.assertNotIn("heals", self._sidecar(path))
        s = R.rollup([path])
        self.assertEqual(s["healed_streams"], [])
        self.assertEqual(
            json.loads(R.render_report(s))["healed_streams"], [])

    def test_two_successive_heals_accumulate(self):
        tmp = tempfile.mkdtemp(prefix="ledger-fix3c-")
        path = os.path.join(tmp, "usage-ledger.jsonl")
        w = L.LedgerWriter(path, "msi")
        for i in range(1, 3):
            w.append(serve_reported(brief_id=f"brief-00{i}"))
        # First crash window: line 3 lands, sidecar stays at 2.
        self._hand_append(path, w, "msi-000003",
                          brief_id="brief-003")
        w2 = L.LedgerWriter(path, "msi")
        self.assertTrue(w2.healed)
        w2.append(serve_reported(brief_id="brief-004"))
        # Second crash window: line 5 lands, sidecar stays at 4.
        self._hand_append(path, w2, "msi-000005",
                          brief_id="brief-005")
        w3 = L.LedgerWriter(path, "msi")
        self.assertTrue(w3.healed)
        w3.append(serve_reported(brief_id="brief-006"))
        commitment = self._sidecar(path)
        self.assertEqual(len(commitment["heals"]), 2)
        self.assertEqual(
            [(h["healed_at_line_count"], h["stream_lines_at_heal"])
             for h in commitment["heals"]], [(2, 3), (4, 5)])
        s = R.rollup([path])
        self.assertEqual(s["gate_valid_totals"]["events"], 6)
        self.assertEqual(len(s["healed_streams"]), 1)
        named = s["healed_streams"][0]
        self.assertEqual(named["heal_count"], 2)
        self.assertEqual(named["healed_at_line_counts"], [2, 4])
        self.assertEqual(named["stream_lines_at_heal"], [3, 5])


if __name__ == "__main__":
    unittest.main()
