"""Unit tests for gate.py — Slice 5 gate machinery (method DRAFT).

Stdlib only (unittest). All fixtures are synthetic and fixture-local
(temp dirs). Run from this directory:

    python3 -m unittest test_gate
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate  # noqa: E402

BASE_START, BASE_END = "2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z"
GATE_START, GATE_END = "2026-11-01T00:00:00Z", "2026-11-08T00:00:00Z"


def brief(name, tokens, status="done", ts="2026-10-02T00:00:00Z",
          brief_id=None):
    rec = gate.BriefRecord(
        job_key=name, name=name, brief_id=brief_id or name, status=status,
        started_at=gate.parse_iso(ts), reported_tokens=tokens)
    return rec


def serve(event_id, brief_id=None, served=100, old=1000, reported=None,
          estimated=None, estimator=None, reason=None, etype="serve"):
    ev = {"event_id": event_id, "event_type": etype, "brief_id": brief_id,
          "context_tokens_served": served,
          "old_path_equivalent_tokens": old,
          "not_computable_reason": reason}
    if reported is not None:
        ev["reported_tokens"] = {"provider": "codex", "input": reported,
                                 "output": 0, "cached_input": 0}
    if estimated is not None:
        ev["estimated_tokens"] = {"value": estimated, "estimator": estimator}
    return gate.ledger_event_to_serve(ev)


class TestUsageExtraction(unittest.TestCase):
    def test_turn_completed_sums_and_cached_counted_in_full(self):
        text = "\n".join([
            json.dumps({"type": "turn.completed",
                        "usage": {"input_tokens": 1000, "output_tokens": 50,
                                  "cached_input_tokens": 800}}),
            json.dumps({"type": "turn.completed",
                        "usage": {"input_tokens": 500, "output_tokens": 25,
                                  "cached_input_tokens": 500}}),
            json.dumps({"type": "item.completed", "usage": {"input_tokens": 9}}),
            "not json at all",
            json.dumps({"type": "turn.completed"}),  # no usage: ignored
        ])
        u = gate.extract_usage_from_text(text)
        self.assertEqual(u.turns, 2)
        self.assertEqual(u.input_tokens, 1500)
        # cached is inside input; total is input+output, NOT input-cached
        # and NOT input+output+cached.
        self.assertEqual(u.total, 1575)
        self.assertEqual(u.cached_input_tokens, 1300)


class TestTaxonomy(unittest.TestCase):
    def test_classes(self):
        cases = [
            ("prod-M-C11-2026-10-20", gate.CLASS_NIGHTLY_PRODUCTION),
            ("prod-tessa-daily", gate.CLASS_NIGHTLY_PRODUCTION),
            ("codex-review-slice1", gate.CLASS_REVIEW),
            ("rereview-fix7", gate.CLASS_REVIEW),
            ("census-refresh-design-fix", gate.CLASS_CENSUS_BUILD),
            ("claimreg-build-storm", gate.CLASS_CENSUS_BUILD),
            ("card-core-fix-v2", gate.CLASS_FIX),
            ("1-qKpeQiYlnFXtrKWoSmnFNUsGT9la0ej-eddab817",
             gate.CLASS_HASHED_DRIVE_DOC),
            ("0123456789abcdef0123456789abcdef", gate.CLASS_HASHED_DRIVE_DOC),
            ("skin-lane-round2", gate.CLASS_OTHER_NAMED),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                cls, stratum, _ = gate.classify_brief(name)
                self.assertEqual(cls, expected)
                self.assertEqual(stratum, gate.STRATUM_BRIEF)

    def test_notebook_cp_is_named_exclusion(self):
        cls, stratum, reason = gate.classify_brief("notebook-cp-ask-42")
        self.assertIsNone(cls)
        self.assertEqual(stratum, gate.STRATUM_EXCLUDED)
        self.assertIn("notebook-cp", reason)

    def test_interactive_is_separate_stratum(self):
        cls, stratum, _ = gate.classify_brief("interactive-codexcp-session-7")
        self.assertEqual(cls, gate.CLASS_INTERACTIVE_SESSION)
        self.assertEqual(stratum, gate.STRATUM_SESSION)


class TestReceiptLoading(unittest.TestCase):
    def test_load_receipt_dir_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td) / "prod-M-C11-x"
            job.mkdir()
            (job / "receipt.json").write_text(json.dumps({
                "job_key": "prod-M-C11-x", "brief_id": "b1",
                "status": "done", "started_at": "2026-10-02T00:00:00Z",
                "ended_at": "2026-10-02T01:00:00Z"}))
            (job / "stdout.log").write_text(json.dumps(
                {"type": "turn.completed",
                 "usage": {"input_tokens": 2000, "output_tokens": 100,
                           "cached_input_tokens": 300}}) + "\n")
            records = gate.load_receipt_dir(td)
            self.assertEqual(len(records), 1)
            r = records[0]
            self.assertEqual(r.reported_tokens, 2100)
            self.assertEqual(r.class_name, gate.CLASS_NIGHTLY_PRODUCTION)
            stats = gate.window_stats(records, BASE_START, BASE_END)
            self.assertEqual(stats["finished_with_usage"], 1)
            self.assertEqual(stats["tokens_per_finished_brief"], 2100)

    def test_done_without_usage_is_named_not_dropped(self):
        records = [brief("prod-M-C11-a", None), brief("prod-M-C11-b", 100)]
        stats = gate.window_stats(records, BASE_START, BASE_END)
        self.assertEqual(stats["finished_briefs"], 2)
        self.assertEqual(stats["finished_with_usage"], 1)
        self.assertEqual(stats["finished_without_usage_named"],
                         ["prod-M-C11-a"])

    def test_window_membership_is_started_at_half_open(self):
        records = [brief("prod-M-C11-a", 10, ts="2026-10-01T00:00:00Z"),
                   brief("prod-M-C11-b", 20, ts="2026-10-08T00:00:00Z"),
                   brief("prod-M-C11-c", 30, status="error",
                         ts="2026-10-03T00:00:00Z")]
        stats = gate.window_stats(records, BASE_START, BASE_END)
        self.assertEqual(stats["finished_with_usage"], 1)
        self.assertEqual(stats["total_tokens"], 10)

    def test_matched_series_exclude_first_run(self):
        records = [brief("prod-M-C11-a", 1000, ts="2026-10-02T00:00:00Z"),
                   brief("prod-M-C11-b", 100, ts="2026-10-03T00:00:00Z"),
                   brief("prod-M-C11-c", 300, ts="2026-10-04T00:00:00Z")]
        st = gate.matched_series(records, r"^prod-M-C11", BASE_START, BASE_END)
        self.assertEqual(st["n"], 3)
        st2 = gate.matched_series(records, r"^prod-M-C11", BASE_START, BASE_END,
                                  exclude_first_run=True)
        self.assertEqual(st2["n"], 2)
        self.assertEqual(st2["mean"], 200)


class TestG1Coverage(unittest.TestCase):
    def _records(self, n):
        return [brief(f"lane-brief-{i}", 100, ts="2026-11-02T00:00:00Z",
                      brief_id=f"b{i}") for i in range(n)]

    def test_coverage_pass_and_unjoined_named(self):
        records = self._records(10)
        serves = [serve(f"e{i}", brief_id=f"b{i}", reported=100)
                  for i in range(9)]
        g1 = gate.compute_g1(records, serves, GATE_START, GATE_END)
        self.assertEqual(g1["coverage"], 0.9)
        self.assertEqual(g1["status"], "pass")
        self.assertEqual(g1["unjoined_named"], ["lane-brief-9"])

    def test_below_threshold_is_invalid_not_failed(self):
        records = self._records(10)
        serves = [serve(f"e{i}", brief_id=f"b{i}", reported=100)
                  for i in range(5)]
        g1 = gate.compute_g1(records, serves, GATE_START, GATE_END)
        self.assertEqual(g1["status"], "invalid")

    def test_estimated_only_join_does_not_count(self):
        records = self._records(2)
        serves = [serve("e0", brief_id="b0", estimated=500, estimator="char/4"),
                  serve("e1", brief_id="b1", estimated=500, estimator="char/4")]
        g1 = gate.compute_g1(records, serves, GATE_START, GATE_END)
        self.assertEqual(g1["coverage"], 0.0)
        self.assertEqual(g1["status"], "invalid")


class TestG2MixAdjustment(unittest.TestCase):
    def _tables(self, base_rows, gate_rows):
        bt = gate.window_stats(base_rows, BASE_START, BASE_END)
        gt = gate.window_stats(gate_rows, GATE_START, GATE_END)
        return bt, gt

    def test_adjusted_win_passes(self):
        base = [brief("prod-M-C11-a", 1000), brief("prod-M-C11-b", 1000),
                brief("x-review-1", 100)]
        gate_rows = [brief("prod-M-C11-a", 900, ts="2026-11-02T00:00:00Z"),
                     brief("prod-M-C11-b", 900, ts="2026-11-02T00:00:00Z"),
                     brief("x-review-1", 90, ts="2026-11-02T00:00:00Z")]
        bt, gt = self._tables(base, gate_rows)
        g2 = gate.compute_g2(bt, gt)
        self.assertEqual(g2["status"], "pass")
        self.assertFalse(g2["sign_disagreement"])

    def test_raw_vs_adjusted_sign_disagreement_flagged(self):
        # Simpson's paradox: EVERY class gets more expensive in the gate
        # week, but the mix shifts to the cheap class, so the RAW mean
        # falls while the mix-adjusted mean rises.
        base = [brief("x-review-1", 100)]
        base += [brief(f"prod-M-C11-{i}", 1000) for i in range(9)]
        gate_rows = [brief(f"x-review-{i}", 200, ts="2026-11-02T00:00:00Z")
                     for i in range(9)]
        gate_rows.append(brief("prod-M-C11-a", 1100, ts="2026-11-02T00:00:00Z"))
        bt, gt = self._tables(base, gate_rows)
        g2 = gate.compute_g2(bt, gt)
        self.assertLess(g2["raw"]["raw_change"], 0)
        self.assertGreater(g2["adjusted"]["adjusted_change"], 0)
        self.assertTrue(g2["sign_disagreement"])
        self.assertEqual(g2["status"], "fail")
        self.assertFalse(g2["adjustment_partial"])

    def test_vanished_baseline_class_named_and_partial(self):
        base = [brief("x-review-1", 100), brief("prod-M-C11-a", 1000)]
        gate_rows = [brief("prod-M-C11-a", 900, ts="2026-11-02T00:00:00Z")]
        bt, gt = self._tables(base, gate_rows)
        g2 = gate.compute_g2(bt, gt)
        self.assertEqual(g2["classes_only_in_baseline_named"],
                         [gate.CLASS_REVIEW])
        self.assertTrue(g2["adjustment_partial"])

    def test_partial_adjustment_cannot_pass_sign_flip_probe(self):
        # Review probe P3 / F1: the cheap baseline class (review, share
        # 0.5, mean 100) vanishes on the gate side; renormalisation over
        # the intersection raises the adjusted baseline to 1000, so the
        # adjusted change is -100 while the raw change is +350. The
        # computation stays, but a PARTIAL G2 must not pass.
        base = [brief("x-review-1", 100), brief("prod-M-C11-a", 1000)]
        gate_rows = [brief("prod-M-C11-a", 900, ts="2026-11-02T00:00:00Z")]
        bt, gt = self._tables(base, gate_rows)
        g2 = gate.compute_g2(bt, gt)
        self.assertTrue(g2["adjustment_partial"])
        self.assertEqual(g2["raw"]["raw_change"], 350)
        self.assertEqual(g2["adjusted"]["adjusted_change"], -100.0)
        self.assertTrue(g2["sign_disagreement"])
        self.assertEqual(g2["status"], "partial")

    def test_partial_adjustment_with_adjusted_loss_is_fail_not_partial(self):
        # Precedence fail > partial (F3a) inside G2 as well.
        base = [brief("x-review-1", 100), brief("prod-M-C11-a", 1000)]
        gate_rows = [brief("prod-M-C11-a", 1200, ts="2026-11-02T00:00:00Z")]
        bt, gt = self._tables(base, gate_rows)
        g2 = gate.compute_g2(bt, gt)
        self.assertTrue(g2["adjustment_partial"])
        self.assertEqual(g2["status"], "fail")

    def test_class_only_in_gate_named(self):
        base = [brief("prod-M-C11-a", 100)]
        gate_rows = [brief("prod-M-C11-a", 90, ts="2026-11-02T00:00:00Z"),
                     brief("new-fix-1", 50, ts="2026-11-02T00:00:00Z")]
        bt, gt = self._tables(base, gate_rows)
        g2 = gate.compute_g2(bt, gt)
        self.assertEqual(g2["classes_only_in_gate_named"], [gate.CLASS_FIX])
        self.assertFalse(g2["adjustment_partial"])


class TestG3aHarmBound(unittest.TestCase):
    def _tables(self, base_rows, gate_rows):
        return (gate.window_stats(base_rows, BASE_START, BASE_END),
                gate.window_stats(gate_rows, GATE_START, GATE_END))

    def test_breach_fails_and_is_named(self):
        base = [brief(f"prod-M-C11-{i}", 1000) for i in range(3)]
        gate_rows = [brief(f"prod-M-C11-{i}", 1200, ts="2026-11-02T00:00:00Z")
                     for i in range(3)]
        bt, gt = self._tables(base, gate_rows)
        g3a = gate.compute_g3a(bt, gt)
        self.assertEqual(g3a["status"], "fail")
        self.assertEqual([b["class"] for b in g3a["breaches"]],
                         [gate.CLASS_NIGHTLY_PRODUCTION])

    def test_within_bound_passes_exactly_at_bound(self):
        base = [brief(f"prod-M-C11-{i}", 1000) for i in range(3)]
        gate_rows = [brief(f"prod-M-C11-{i}", 1100, ts="2026-11-02T00:00:00Z")
                     for i in range(3)]
        bt, gt = self._tables(base, gate_rows)
        self.assertEqual(gate.compute_g3a(bt, gt)["status"], "pass")

    def test_small_classes_skipped_and_named(self):
        base = [brief("prod-M-C11-a", 1000), brief("prod-M-C11-b", 1000),
                brief("x-fix-1", 10)]
        gate_rows = [brief("prod-M-C11-a", 900, ts="2026-11-02T00:00:00Z"),
                     brief("prod-M-C11-b", 900, ts="2026-11-02T00:00:00Z"),
                     brief("x-fix-1", 99999, ts="2026-11-02T00:00:00Z")]
        bt, gt = self._tables(base, gate_rows)
        g3a = gate.compute_g3a(bt, gt)
        self.assertEqual(g3a["status"], "pass")
        skipped = {s["class"] for s in g3a["skipped_below_min_n_named"]}
        self.assertIn(gate.CLASS_FIX, skipped)
        self.assertIn(gate.CLASS_NIGHTLY_PRODUCTION, skipped)

    def test_one_side_only_class_named_not_failed(self):
        base = [brief(f"prod-M-C11-{i}", 1000) for i in range(3)]
        gate_rows = [brief(f"prod-M-C11-{i}", 900, ts="2026-11-02T00:00:00Z")
                     for i in range(3)]
        gate_rows.append(brief("brand-new-census-1", 5000,
                               ts="2026-11-02T00:00:00Z"))
        bt, gt = self._tables(base, gate_rows)
        g3a = gate.compute_g3a(bt, gt)
        self.assertEqual(g3a["status"], "pass")
        self.assertEqual(g3a["classes_on_one_side_only_named"],
                         [{"class": gate.CLASS_CENSUS_BUILD,
                           "side": "gate_only"}])


class TestG3bServeLevel(unittest.TestCase):
    def test_aggregate_and_per_serve_win(self):
        serves = [serve("e1", served=400, old=1000),
                  serve("e2", served=600, old=2000)]
        g3b = gate.compute_g3b(serves)
        self.assertEqual(g3b["status"], "pass")
        self.assertTrue(g3b["aggregate"]["win"])

    def test_micro_class_serve_named_not_failed(self):
        serves = [serve("big", served=400, old=1000),
                  serve("micro1", served=450, old=300)]  # loses, but micro
        g3b = gate.compute_g3b(serves)
        self.assertEqual([m["event_id"] for m in
                          g3b["micro_class_serves_named"]], ["micro1"])
        self.assertEqual(g3b["per_serve_failures_named"], [])

    def test_regular_per_serve_loss_fails(self):
        serves = [serve("e1", served=1500, old=1000)]
        g3b = gate.compute_g3b(serves)
        self.assertEqual(g3b["status"], "fail")
        self.assertEqual(len(g3b["per_serve_failures_named"]), 1)

    def test_noncomputable_over_20pct_is_partial_and_named(self):
        serves = [serve("ok", served=100, old=1000)]
        serves += [serve(f"nc{i}", served=100, old=None,
                         reason="no old-path accounting") for i in range(2)]
        g3b = gate.compute_g3b(serves)
        self.assertEqual(g3b["status"], "partial")
        self.assertEqual(len(g3b["noncomputable_named"]), 2)
        self.assertEqual(g3b["noncomputable_named"][0]["reason"],
                         "no old-path accounting")

    def test_served_tokens_missing_is_noncomputable_named(self):
        # F2: old-path present but served/context tokens missing (None)
        # => non-computable with reason served_tokens_missing, counted
        # toward the >20% PARTIAL share; never silently dropped.
        serves = [serve("ok", served=100, old=1000),
                  serve("ghost", served=None, old=1000)]
        g3b = gate.compute_g3b(serves)
        self.assertEqual(g3b["serves_total"], 2)
        self.assertEqual(g3b["computable"], 1)
        self.assertEqual(g3b["noncomputable_named"],
                         [{"event_id": "ghost",
                           "reason": "served_tokens_missing"}])
        self.assertEqual(g3b["noncomputable_share"], 0.5)
        self.assertEqual(g3b["status"], "partial")

    def test_fail_takes_precedence_over_partial(self):
        # F3a / review probe P7: aggregate loss + a named per-serve
        # failure + 66.7% non-computable must report fail, not partial.
        serves = [serve("fail1", served=1500, old=1000),
                  serve("nc1", served=100, old=None, reason="no accounting"),
                  serve("nc2", served=100, old=None, reason="no accounting")]
        g3b = gate.compute_g3b(serves)
        self.assertEqual(g3b["noncomputable_share"], 0.6667)
        self.assertEqual(len(g3b["per_serve_failures_named"]), 1)
        self.assertEqual(g3b["status"], "fail")

    def test_noncomputable_under_threshold_not_partial(self):
        serves = [serve(f"ok{i}", served=100, old=1000) for i in range(9)]
        serves.append(serve("nc", served=100, old=None, reason="r"))
        g3b = gate.compute_g3b(serves)
        self.assertNotEqual(g3b["status"], "partial")


class TestEstimatedNeverSummed(unittest.TestCase):
    def test_estimated_stratum_separate(self):
        serves = [serve("r1", reported=1000),
                  serve("e1", estimated=777, estimator="char/4"),
                  serve("e2", estimated=223, estimator="char/4")]
        stratum = gate.estimated_stratum(serves)
        self.assertEqual(stratum["events"], 2)
        self.assertEqual(stratum["estimated_tokens_total"], 1000)
        self.assertEqual(stratum["estimators_named"], ["char/4"])
        # The reported serve's figures never absorb the estimates.
        self.assertEqual(serves[0].reported_tokens, 1000)
        self.assertIsNone(serves[0].estimated_tokens)

    def test_both_tokens_event_named_and_excluded_from_both_strata(self):
        # F5: reported + estimated on one event is out of schema. It is
        # named in the invalid-input list and excluded from BOTH strata:
        # the estimate never enters the estimated stratum and the
        # reported value never joins a brief for G1.
        both = serve("both1", brief_id="b0", reported=1000, estimated=777,
                     estimator="char/4")
        invalid = gate.invalid_token_events([both])
        self.assertEqual(len(invalid), 1)
        self.assertEqual(invalid[0]["event_id"], "both1")
        self.assertIn("both reported_tokens and estimated_tokens",
                      invalid[0]["reason"])
        stratum = gate.estimated_stratum([both])
        self.assertEqual(stratum["events"], 0)
        self.assertEqual(stratum["estimated_tokens_total"], 0)
        records = [brief("lane-brief-0", 100, ts="2026-11-02T00:00:00Z",
                         brief_id="b0")]
        g1 = gate.compute_g1(records, [both], GATE_START, GATE_END)
        self.assertEqual(g1["coverage"], 0.0)
        report = gate.build_gate_report(records, records, [both],
                                        (BASE_START, BASE_END),
                                        (GATE_START, GATE_END))
        self.assertEqual([i["event_id"] for i in
                          report["invalid_inputs_named"]], ["both1"])
        self.assertIn("both1", gate.render_markdown(report))

    def test_ledger_stream_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "usage-ledger.jsonl"
            rows = [
                {"event_id": "a", "event_type": "serve", "brief_id": "b1",
                 "context_tokens_served": 120,
                 "reported_tokens": {"provider": "codex", "input": 500,
                                     "output": 20, "cached_input": 100},
                 "old_path_equivalent_tokens": 900},
                {"event_id": "b", "event_type": "serve", "brief_id": "b2",
                 "context_tokens_served": 50,
                 "estimated_tokens": {"value": 42, "estimator": "char/4"},
                 "old_path_equivalent_tokens": None,
                 "not_computable_reason": "no baseline"},
                "garbage line",
            ]
            p.write_text("\n".join(
                r if isinstance(r, str) else json.dumps(r) for r in rows))
            serves = gate.load_ledger_stream(p)
            self.assertEqual(len(serves), 2)
            self.assertEqual(serves[0].reported_tokens, 520)
            self.assertIsNone(serves[1].reported_tokens)
            self.assertEqual(serves[1].estimated_tokens, 42)


class TestFullReport(unittest.TestCase):
    def test_report_flags_sign_disagreement_in_first_paragraph(self):
        base = [brief("x-review-1", 100)]
        base += [brief(f"prod-M-C11-{i}", 1000) for i in range(9)]
        gate_rows = [brief(f"x-review-{i}", 200, ts="2026-11-02T00:00:00Z")
                     for i in range(9)]
        gate_rows.append(brief("prod-M-C11-a", 1100,
                               ts="2026-11-02T00:00:00Z", brief_id="g1"))
        serves = [serve("s1", brief_id="g1", reported=9000)]
        report = gate.build_gate_report(base, gate_rows, serves,
                                        (BASE_START, BASE_END),
                                        (GATE_START, GATE_END))
        self.assertTrue(any("DISAGREE IN SIGN" in f
                            for f in report["first_paragraph_flags"]))
        md = gate.render_markdown(report)
        self.assertIn("DISAGREE IN SIGN", md)

    def test_g2_partial_blocks_overall_pass_and_is_flagged_first(self):
        # F1 at report level: everything else passes, G2 is partial =>
        # components_pass.G2 is False, the overall status is partial
        # (not pass), and the first paragraph states it.
        base = [brief("x-review-1", 100), brief("prod-M-C11-a", 1000)]
        gate_rows = [brief("prod-M-C11-a", 900, ts="2026-11-02T00:00:00Z",
                           brief_id="gprod")]
        serves = [serve("s1", brief_id="gprod", reported=100)]
        report = gate.build_gate_report(base, gate_rows, serves,
                                        (BASE_START, BASE_END),
                                        (GATE_START, GATE_END))
        self.assertEqual(report["G2_mix_adjusted"]["status"], "partial")
        self.assertFalse(report["components_pass"]["G2"])
        self.assertTrue(report["components_pass"]["G2_partial"])
        self.assertEqual(report["overall_status"], "partial")
        self.assertTrue(any("G2 MIX ADJUSTMENT IS PARTIAL" in f
                            for f in report["first_paragraph_flags"]))
        self.assertIn("G2 MIX ADJUSTMENT IS PARTIAL",
                      gate.render_markdown(report))

    def test_overall_status_precedence_fail_over_partial_over_pass(self):
        # F3a: a partial must never mask a fail in the overall label.
        self.assertEqual(gate.overall_status("pass", "partial", "fail"),
                         "fail")
        self.assertEqual(gate.overall_status("pass", "partial"), "partial")
        self.assertEqual(gate.overall_status("pass", "pass"), "pass")

    def test_markdown_includes_g3b_failure_and_noncomputable_lists(self):
        # F3b: the human report carries the same named lists as the
        # JSON — per-serve failures and non-computable serves, with
        # reasons — nothing named in JSON may vanish from Markdown.
        base = [brief("prod-M-C11-a", 1000)]
        gate_rows = [brief("prod-M-C11-a", 900, ts="2026-11-02T00:00:00Z",
                           brief_id="gprod")]
        serves = [serve("s1", brief_id="gprod", reported=100),
                  serve("badserve", served=1500, old=1000),
                  serve("ncserve", served=100, old=None,
                        reason="no old-path accounting")]
        report = gate.build_gate_report(base, gate_rows, serves,
                                        (BASE_START, BASE_END),
                                        (GATE_START, GATE_END))
        md = gate.render_markdown(report)
        self.assertIn("per-serve failures named", md)
        self.assertIn("badserve", md)
        self.assertIn("non-computable named", md)
        self.assertIn("ncserve", md)
        self.assertIn("no old-path accounting", md)


def raw_event(event_id, etype="serve", **fields):
    ev = {"event_id": event_id, "event_type": etype}
    ev.update(fields)
    return gate.ledger_event_to_serve(ev)


def raw_correction(event_id, target, cset):
    return raw_event(event_id, etype="correction",
                     corrects={"target_event_id": target, "set": cset},
                     corrects_event_id=target)


class TestDelta2FlagTruthfulness(unittest.TestCase):
    def _report(self, gate_tokens):
        base = [brief("x-review-1", 100), brief("prod-M-C11-a", 1000)]
        gate_rows = [brief("prod-M-C11-a", gate_tokens,
                           ts="2026-11-02T00:00:00Z", brief_id="gprod")]
        serves = [serve("s1", brief_id="gprod", reported=100)]
        return gate.build_gate_report(base, gate_rows, serves,
                                      (BASE_START, BASE_END),
                                      (GATE_START, GATE_END))

    def test_partial_adjustment_with_loss_flag_says_fail_not_partial(self):
        # N1 / the re-reviewer's case: partial adjustment + adjusted
        # loss => G2 status fail, and the first-paragraph flag must be
        # generated from that final status — it must NOT claim the
        # status "is partial".
        report = self._report(1200)
        self.assertTrue(report["G2_mix_adjusted"]["adjustment_partial"])
        self.assertEqual(report["G2_mix_adjusted"]["status"], "fail")
        flags = report["first_paragraph_flags"]
        partial_flags = [f for f in flags
                         if "G2 MIX ADJUSTMENT IS PARTIAL" in f]
        self.assertEqual(len(partial_flags), 1)
        self.assertIn("G2 status is fail", partial_flags[0])
        self.assertFalse(any("G2 status is partial" in f for f in flags))
        self.assertIn("G2 status is fail", gate.render_markdown(report))

    def test_partial_adjustment_partial_status_flag_says_partial(self):
        report = self._report(900)
        self.assertEqual(report["G2_mix_adjusted"]["status"], "partial")
        self.assertTrue(any("G2 status is partial" in f
                            for f in report["first_paragraph_flags"]))


class TestDelta2OverallPrecedence(unittest.TestCase):
    def test_invalid_dominates_full_combination_matrix(self):
        # N2: precedence invalid > fail > partial > not_computable >
        # pass, over every pair and triple of component labels.
        import itertools
        rank = {"invalid": 4, "fail": 3, "partial": 2,
                "not_computable": 1, "pass": 0}
        labels = list(rank)
        for size in (2, 3):
            for combo in itertools.product(labels, repeat=size):
                expected = max(combo, key=lambda s: rank[s])
                with self.subTest(combo=combo):
                    self.assertEqual(gate.overall_status(*combo), expected)

    def test_invalid_over_partial_and_fail_explicitly(self):
        self.assertEqual(gate.overall_status("invalid", "partial"),
                         "invalid")
        self.assertEqual(gate.overall_status("invalid", "fail"),
                         "invalid")

    def test_invalid_not_masked_by_partial_in_report(self):
        # Report level: G1 invalid + G3b partial => overall invalid
        # (under the pre-delta-2 precedence this reported "partial").
        base = [brief("prod-M-C11-a", 1000)]
        gate_rows = [brief(f"lane-brief-{i}", 100,
                           ts="2026-11-02T00:00:00Z", brief_id=f"b{i}")
                     for i in range(10)]
        serves = [serve(f"j{i}", brief_id=f"b{i}", reported=100)
                  for i in range(5)]
        serves += [serve(f"nc{i}", served=100, old=None,
                         reason="no old-path accounting")
                   for i in range(2)]
        report = gate.build_gate_report(base, gate_rows, serves,
                                        (BASE_START, BASE_END),
                                        (GATE_START, GATE_END))
        self.assertEqual(report["G1_coverage"]["status"], "invalid")
        self.assertEqual(report["G3b_serve_level"]["status"], "partial")
        self.assertEqual(report["overall_status"], "invalid")


class TestDelta2BothTokensServeStratum(unittest.TestCase):
    def test_both_tokens_event_invisible_to_g3b(self):
        # F5 leftover / the re-reviewer's probe shape: a both-token
        # serve (served 100 vs old-path 1000 — a computable win if it
        # were counted) contributes NOTHING to G3b: not a computable
        # serve, not a non-computable serve, nowhere in the math.
        both = serve("both1", reported=1000, estimated=777,
                     estimator="char/4", served=100, old=1000)
        g3b = gate.compute_g3b([both])
        self.assertEqual(g3b["serves_total"], 0)
        self.assertEqual(g3b["computable"], 0)
        self.assertEqual(g3b["noncomputable_named"], [])
        self.assertEqual(g3b["aggregate"]["served_tokens"], 0)
        self.assertEqual(g3b["aggregate"]["old_path_equivalent_tokens"], 0)
        mixed = gate.compute_g3b(
            [serve("ok", served=100, old=1000), both])
        self.assertEqual(mixed["serves_total"], 1)
        self.assertEqual(mixed["computable"], 1)
        self.assertEqual(mixed["status"], "pass")

    def test_both_tokens_event_named_exactly_once_in_report(self):
        both = serve("both1", brief_id="b0", reported=1000,
                     estimated=777, estimator="char/4")
        records = [brief("lane-brief-0", 100, ts="2026-11-02T00:00:00Z",
                         brief_id="b0")]
        report = gate.build_gate_report(records, records, [both],
                                        (BASE_START, BASE_END),
                                        (GATE_START, GATE_END))
        named = [i for i in report["invalid_inputs_named"]
                 if i["event_id"] == "both1"]
        self.assertEqual(len(named), 1)
        self.assertEqual(gate.render_markdown(report).count("both1"), 1)


class TestDelta2Corrections(unittest.TestCase):
    def test_correction_applies_before_g3b_math(self):
        bad = raw_event("s1", context_tokens_served=1500,
                        old_path_equivalent_tokens=1000)
        fix = raw_correction("c1", "s1", {"context_tokens_served": 500})
        self.assertEqual(gate.compute_g3b([bad])["status"], "fail")
        g3b = gate.compute_g3b([bad, fix])
        self.assertEqual(g3b["status"], "pass")
        self.assertEqual(g3b["aggregate"]["served_tokens"], 500)
        self.assertEqual(g3b["per_serve_failures_named"], [])

    def test_correction_applies_to_estimated_stratum(self):
        est = raw_event("e1", estimated_tokens={"value": 500,
                                                "estimator": "char/4"})
        fix = raw_correction("c1", "e1",
                             {"estimated_tokens": {"value": 250,
                                                   "estimator": "char/4"}})
        stratum = gate.estimated_stratum([est, fix])
        self.assertEqual(stratum["events"], 1)
        self.assertEqual(stratum["estimated_tokens_total"], 250)

    def test_correction_applies_to_reported_tokens_for_g1_join(self):
        est = raw_event("e1", brief_id="b0",
                        estimated_tokens={"value": 500,
                                          "estimator": "char/4"})
        fix = raw_correction("c1", "e1", {"estimated_tokens": None})
        records = [brief("lane-brief-0", 100, ts="2026-11-02T00:00:00Z",
                         brief_id="b0")]
        # Without the correction the event is estimated-only and
        # cannot join; clearing the estimate alone still leaves no
        # reported figure, so coverage stays 0 — the point asserted
        # here is that the fold happened (estimate gone everywhere).
        folded, named = gate.apply_corrections([est, fix])
        self.assertTrue(named[0]["applied"])
        self.assertIsNone(folded[0].estimated_tokens)
        g1 = gate.compute_g1(records, [est, fix], GATE_START, GATE_END)
        self.assertEqual(g1["coverage"], 0.0)

    def test_never_both_correction_named_not_applied(self):
        rep = raw_event("s1", reported_tokens={"provider": "codex",
                                               "input": 1000, "output": 0,
                                               "cached_input": 0})
        bad = raw_correction("c1", "s1",
                             {"estimated_tokens": {"value": 5,
                                                   "estimator": "char/4"}})
        folded, named = gate.apply_corrections([rep, bad])
        self.assertEqual(len(named), 1)
        self.assertFalse(named[0]["applied"])
        self.assertIn("both", named[0]["not_applied_reason"])
        self.assertEqual(folded[0].reported_tokens, 1000)
        self.assertIsNone(folded[0].estimated_tokens)
        report = gate.build_gate_report(
            [brief("prod-M-C11-a", 1000)],
            [brief("prod-M-C11-a", 900, ts="2026-11-02T00:00:00Z")],
            [rep, bad], (BASE_START, BASE_END), (GATE_START, GATE_END))
        self.assertEqual([c["event_id"] for c in
                          report["corrections_named"]], ["c1"])
        self.assertFalse(report["corrections_named"][0]["applied"])

    def test_unknown_target_correction_named_not_applied(self):
        rep = raw_event("s1", reported_tokens={"provider": "codex",
                                               "input": 1000, "output": 0,
                                               "cached_input": 0})
        lost = raw_correction("c9", "nope",
                              {"reported_tokens": {"provider": "codex",
                                                   "input": 1,
                                                   "output": 1}})
        folded, named = gate.apply_corrections([rep, lost])
        self.assertFalse(named[0]["target_found"])
        self.assertFalse(named[0]["applied"])
        self.assertEqual(folded[0].reported_tokens, 1000)

    def test_two_corrections_same_target_later_supersedes_per_field(self):
        # Mirrors rollup's deterministic-order case: later correction
        # wins per-field; fields it does not touch keep the earlier
        # correction's values.
        rep = raw_event(
            "s1", context_tokens_served=4200,
            reported_tokens={"provider": "codex", "input": 1000,
                             "output": 200, "cached_input": 300})
        c1 = raw_correction("c1", "s1", {
            "reported_tokens": {"provider": "codex", "input": 100,
                                "output": 200, "cached_input": 300},
            "context_tokens_served": 50})
        c2 = raw_correction("c2", "s1", {
            "reported_tokens": {"provider": "codex", "input": 7,
                                "output": 200, "cached_input": 300}})
        folded, named = gate.apply_corrections([rep, c1, c2])
        self.assertTrue(all(n["applied"] for n in named))
        self.assertEqual(folded[0].reported_tokens, 207)
        self.assertEqual(folded[0].context_tokens_served, 50)

    def test_correction_listed_before_target_still_applies(self):
        # Target resolution is order-independent (as in rollup).
        fix = raw_correction("c1", "s1", {"context_tokens_served": 500})
        bad = raw_event("s1", context_tokens_served=1500,
                        old_path_equivalent_tokens=1000)
        g3b = gate.compute_g3b([fix, bad])
        self.assertEqual(g3b["status"], "pass")


class TestCorrectionGoldenCrossModule(unittest.TestCase):
    def test_rollup_and_gate_fold_identical_corrected_figures(self):
        # MANDATORY cross-module golden test (delta-2, item 4): one
        # fixture ledger stream — serves + corrections, including a
        # never-both-violating correction and an unknown-target
        # correction — folded by BOTH rollup.rollup and gate.py must
        # yield identical corrected per-event figures.
        import ledger as L
        import rollup as R

        ts = "2026-11-06T10:00:00+00:00"
        hashset = "a" * 64

        def serve_base(**over):
            ev = {
                "ts": ts, "event_type": "serve", "host": "msi",
                "lane_id": "codex-cp", "run_id": "run-1",
                "brief_id": "brief-001", "consumer": "lane:codex-cp",
                "pack_id": "pack-cmm-basics", "pack_version": 1,
                "requested_key": {"domain": "cmm",
                                  "task_type": "nightly production"},
                "outcome": "hit", "derived_level": "house",
                "entitlement_result": "served_full",
                "context_tokens_served": 4200, "token_counter": "char/4",
                "reported_tokens": {"provider": "openai-codex",
                                    "input": 1000, "output": 200,
                                    "cached_input": 300},
                "old_path_equivalent_tokens": 9000,
                "sources_hash_set_hash": hashset,
            }
            ev.update(over)
            return ev

        def correction(target, cset):
            return {
                "ts": ts, "event_type": "correction", "host": "msi",
                "lane_id": "codex-cp", "run_id": "run-9",
                "corrects_event_id": target,
                "correction": "golden fixture correction",
                "corrects": {"target_event_id": target, "set": cset},
            }

        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "usage-ledger.jsonl")
            w = L.LedgerWriter(path, "msi")
            a = w.append(serve_base())
            b_ev = serve_base(brief_id="brief-002", outcome="cache_hit",
                              context_tokens_served=300,
                              old_path_equivalent_tokens=1000)
            del b_ev["reported_tokens"]
            b_ev["estimated_tokens"] = {"value": 500,
                                        "estimator": "char/4"}
            b = w.append(b_ev)
            rep = {"provider": "openai-codex", "output": 200,
                   "cached_input": 300}
            c1 = w.append(correction(a["event_id"], {
                "reported_tokens": dict(rep, input=10),
                "context_tokens_served": 50}))
            c2 = w.append(correction(a["event_id"], {
                "reported_tokens": dict(rep, input=7)}))
            c3 = w.append(correction(b["event_id"], {
                "reported_tokens": {"provider": "openai-codex",
                                    "input": 1, "output": 1,
                                    "cached_input": 0}}))
            c4 = w.append(correction("msi-999999", {
                "reported_tokens": {"provider": "openai-codex",
                                    "input": 1, "output": 1}}))
            # Delta-3 (D1): a correction targeting a CORRECTION (c1).
            # Rollup as settled by Slice 1 fix round 2 (R2) names it
            # target_is_correction and never applies it; gate's mirror
            # must produce the identical named entry and figures.
            c5 = w.append(correction(c1["event_id"], {
                "reported_tokens": {"provider": "openai-codex",
                                    "input": 999, "output": 1,
                                    "cached_input": 0},
                "context_tokens_served": 111}))

            summary = R.rollup([path])
            rcorr = {c["event_id"]: c for c in summary["corrections"]}
            folded, named = gate.apply_corrections(
                gate.load_ledger_stream(path))
            gcorr = {n["event_id"]: n for n in named}
            by_id = {s.event_id: s for s in folded}

            # Target A: two applied corrections in both folds; the
            # final corrected figures are identical (gate's reported
            # figure is the input+output total of rollup's dict).
            self.assertTrue(rcorr[c1["event_id"]]["applied"])
            self.assertTrue(rcorr[c2["event_id"]]["applied"])
            self.assertTrue(gcorr[c1["event_id"]]["applied"])
            self.assertTrue(gcorr[c2["event_id"]]["applied"])
            r_after = rcorr[c2["event_id"]]["after"]
            ga = by_id[a["event_id"]]
            self.assertEqual(
                ga.reported_tokens,
                r_after["reported_tokens"]["input"]
                + r_after["reported_tokens"]["output"])
            self.assertEqual(ga.context_tokens_served,
                             r_after["context_tokens_served"])
            self.assertIsNone(ga.estimated_tokens)
            self.assertIsNone(r_after["estimated_tokens"])
            # Gate's own after-figures for c2 equal rollup's, converted.
            self.assertEqual(gcorr[c2["event_id"]]["after"]
                             ["reported_tokens"], ga.reported_tokens)
            self.assertEqual(gcorr[c2["event_id"]]["after"]
                             ["context_tokens_served"], 50)

            # Target B: the never-both correction is named and NOT
            # applied by BOTH folds; B's figures are unchanged in both.
            self.assertFalse(rcorr[c3["event_id"]]["applied"])
            self.assertIn("both",
                          rcorr[c3["event_id"]]["not_applied_reason"])
            self.assertFalse(gcorr[c3["event_id"]]["applied"])
            self.assertIn("both",
                          gcorr[c3["event_id"]]["not_applied_reason"])
            gb = by_id[b["event_id"]]
            self.assertIsNone(gb.reported_tokens)
            self.assertEqual(gb.estimated_tokens, 500)
            totals = summary["gate_valid_totals"]
            self.assertEqual(totals["estimated"]["by_estimator"]
                             ["char/4"]["value"], 500)
            self.assertEqual(totals["reported"]["input"], 7)
            self.assertEqual(
                sum(s.reported_tokens or 0 for s in folded),
                totals["reported"]["input"] + totals["reported"]["output"])
            self.assertEqual(
                sum(s.context_tokens_served or 0 for s in folded),
                totals["context_tokens_served"])

            # Unknown target: named, not applied, by BOTH folds, with
            # the identical reason string.
            self.assertFalse(rcorr[c4["event_id"]]["target_found"])
            self.assertFalse(rcorr[c4["event_id"]]["applied"])
            self.assertFalse(gcorr[c4["event_id"]]["target_found"])
            self.assertFalse(gcorr[c4["event_id"]]["applied"])
            self.assertEqual(gcorr[c4["event_id"]]["not_applied_reason"],
                             rcorr[c4["event_id"]]["not_applied_reason"])

            # Never-both: the NAMED entries match too, not just the
            # figures (delta-3 tripwire extension).
            self.assertEqual(gcorr[c3["event_id"]]["not_applied_reason"],
                             rcorr[c3["event_id"]]["not_applied_reason"])

            # Correction-on-correction (D1): BOTH folds name c5
            # applied False / target_is_correction (identical reason),
            # target_found True, and A's corrected figures are exactly
            # as if c5 did not exist (reported 207, context 50 — the
            # fabricated 999/111 never land in either fold).
            for corr in (rcorr, gcorr):
                entry = corr[c5["event_id"]]
                self.assertTrue(entry["target_found"])
                self.assertFalse(entry["applied"])
                self.assertIn("target_is_correction",
                              entry["not_applied_reason"])
            self.assertEqual(gcorr[c5["event_id"]]["not_applied_reason"],
                             rcorr[c5["event_id"]]["not_applied_reason"])
            self.assertEqual(ga.reported_tokens, 207)
            self.assertEqual(ga.context_tokens_served, 50)


class TestDelta3CorrectionOnCorrection(unittest.TestCase):
    def test_correction_targeting_correction_named_not_applied(self):
        # D1 / the delta-2 re-reviewer's §5(a) shape: serve A
        # (reported 1000/200, ctx 4200); C1 corrects A -> reported
        # 10/200; C2 corrects C1, setting reported 999/1 + ctx 111.
        # Rollup (settled, R2): C2 applied False / target_is_correction,
        # totals reported 10/200, ctx 4200. Gate must now match the
        # NAMED entry as well as the figures.
        a = raw_event(
            "a", context_tokens_served=4200,
            reported_tokens={"provider": "codex", "input": 1000,
                             "output": 200, "cached_input": 0})
        c1 = raw_correction("c1", "a", {
            "reported_tokens": {"provider": "codex", "input": 10,
                                "output": 200, "cached_input": 0}})
        c2 = raw_correction("c2", "c1", {
            "reported_tokens": {"provider": "codex", "input": 999,
                                "output": 1, "cached_input": 0},
            "context_tokens_served": 111})
        folded, named = gate.apply_corrections([a, c1, c2])
        by_name = {n["event_id"]: n for n in named}
        self.assertTrue(by_name["c1"]["applied"])
        self.assertTrue(by_name["c2"]["target_found"])
        self.assertFalse(by_name["c2"]["applied"])
        self.assertIn("target_is_correction",
                      by_name["c2"]["not_applied_reason"])
        self.assertEqual(folded[0].reported_tokens, 210)
        self.assertEqual(folded[0].context_tokens_served, 4200)

    def test_self_targeting_correction_named_not_applied(self):
        # D1: the target_is_correction guard includes the correction
        # itself (a handcrafted self-target that bypassed the writer's
        # validator, mirroring rollup R2's stored-stream path).
        a = raw_event(
            "a", reported_tokens={"provider": "codex", "input": 1000,
                                  "output": 0, "cached_input": 0})
        selfish = raw_correction("c1", "c1", {
            "reported_tokens": {"provider": "codex", "input": 424242,
                                "output": 0, "cached_input": 0}})
        folded, named = gate.apply_corrections([a, selfish])
        self.assertFalse(named[0]["applied"])
        self.assertIn("target_is_correction",
                      named[0]["not_applied_reason"])
        self.assertEqual(folded[0].reported_tokens, 1000)

    def test_target_is_correction_precedes_never_both(self):
        # D1 precedence (rollup's order): target-not-found, then
        # target-is-correction, then never-both. Here the target is a
        # correction record carrying reported_tokens and the set would
        # add estimated_tokens — never-both would fire if it were
        # checked first; the named reason must be target_is_correction.
        a = raw_event(
            "a", reported_tokens={"provider": "codex", "input": 100,
                                  "output": 0, "cached_input": 0})
        c1 = raw_event(
            "c1", etype="correction",
            reported_tokens={"provider": "codex", "input": 5,
                             "output": 0, "cached_input": 0},
            corrects={"target_event_id": "a",
                      "set": {"context_tokens_served": 7}},
            corrects_event_id="a")
        c2 = raw_correction("c2", "c1", {
            "estimated_tokens": {"value": 5, "estimator": "char/4"}})
        folded, named = gate.apply_corrections([a, c1, c2])
        by_name = {n["event_id"]: n for n in named}
        self.assertFalse(by_name["c2"]["applied"])
        self.assertIn("target_is_correction",
                      by_name["c2"]["not_applied_reason"])
        self.assertNotIn("both", by_name["c2"]["not_applied_reason"])


class TestDelta3DuplicateEventIds(unittest.TestCase):
    def test_duplicate_serve_single_counted_and_named_with_stream_line(self):
        # D2 / the re-reviewer's shape: two serve records, same
        # event_id, reported 100 each. Gate must fold the first only
        # (rollup's single-count figures) and name the duplicate with
        # event_id + stream + line.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "usage-ledger.jsonl"
            row = {"event_id": "dup1", "event_type": "serve",
                   "brief_id": "b0", "context_tokens_served": 100,
                   "reported_tokens": {"provider": "codex", "input": 100,
                                       "output": 0, "cached_input": 0},
                   "old_path_equivalent_tokens": 1000}
            p.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
            serves = gate.load_ledger_stream(p)
            self.assertEqual(len(serves), 2)
            g3b = gate.compute_g3b(serves)
            self.assertEqual(g3b["serves_total"], 1)
            self.assertEqual(g3b["aggregate"]["served_tokens"], 100)
            self.assertEqual(
                g3b["aggregate"]["old_path_equivalent_tokens"], 1000)
            folded, _ = gate.apply_corrections(serves)
            self.assertEqual(sum(s.reported_tokens or 0 for s in folded),
                             100)
            dups = gate.duplicate_event_ids(serves)
            self.assertEqual(len(dups), 1)
            self.assertEqual(dups[0]["event_id"], "dup1")
            self.assertEqual(dups[0]["stream"], str(p))
            self.assertEqual(dups[0]["line"], 2)
            self.assertEqual(dups[0]["first_stream"], str(p))
            self.assertEqual(dups[0]["first_line"], 1)

    def test_duplicate_excluded_from_estimated_stratum_and_corrections(self):
        # D2: duplicates are excluded from ALL gate math — the
        # estimated stratum counts the first occurrence only, and a
        # duplicated correction event is folded once, not twice.
        e1 = raw_event("e1", estimated_tokens={"value": 500,
                                               "estimator": "char/4"})
        e1_dup = raw_event("e1", estimated_tokens={"value": 999,
                                                   "estimator": "char/4"})
        stratum = gate.estimated_stratum([e1, e1_dup])
        self.assertEqual(stratum["events"], 1)
        self.assertEqual(stratum["estimated_tokens_total"], 500)
        a = raw_event("a", context_tokens_served=1500,
                      old_path_equivalent_tokens=1000)
        fix = raw_correction("c1", "a", {"context_tokens_served": 500})
        fix_dup = raw_correction("c1", "a",
                                 {"context_tokens_served": 1})
        folded, named = gate.apply_corrections([a, fix, fix_dup])
        self.assertEqual(len(named), 1)
        self.assertEqual(folded[0].context_tokens_served, 500)

    def test_report_names_duplicates_in_json_and_markdown(self):
        # D2: the report's named lists carry the duplicate in both
        # renderings, and G1/G3b figures are the single-count ones.
        records = [brief("lane-brief-0", 100, ts="2026-11-02T00:00:00Z",
                         brief_id="b0")]
        serves = [serve("dup1", brief_id="b0", reported=100),
                  serve("dup1", brief_id="b0", reported=100)]
        report = gate.build_gate_report(records, records, serves,
                                        (BASE_START, BASE_END),
                                        (GATE_START, GATE_END))
        self.assertEqual(len(report["duplicate_event_ids"]), 1)
        dup = report["duplicate_event_ids"][0]
        self.assertEqual(dup["event_id"], "dup1")
        self.assertIn("stream", dup)
        self.assertEqual(dup["line"], 2)
        self.assertEqual(dup["first_line"], 1)
        self.assertEqual(report["G3b_serve_level"]["serves_total"], 1)
        md = gate.render_markdown(report)
        self.assertIn("Duplicate event_ids named", md)
        self.assertIn("dup1", md)

    def test_rollup_and_gate_single_count_identical_on_duplicate(self):
        # D2 cross-module: two chain-valid streams whose first events
        # share an event_id (separate writers, same host sequence).
        # Rollup folds the first occurrence only and names the second;
        # gate's figures must equal rollup's single-count figures and
        # its duplicate naming must carry the same event_id/stream/line.
        import ledger as L
        import rollup as R

        ts = "2026-11-06T10:00:00+00:00"

        def serve_ev():
            return {
                "ts": ts, "event_type": "serve", "host": "msi",
                "lane_id": "codex-cp", "run_id": "run-1",
                "brief_id": "brief-001", "consumer": "lane:codex-cp",
                "pack_id": "pack-cmm-basics", "pack_version": 1,
                "requested_key": {"domain": "cmm",
                                  "task_type": "nightly production"},
                "outcome": "hit", "derived_level": "house",
                "entitlement_result": "served_full",
                "context_tokens_served": 100, "token_counter": "char/4",
                "reported_tokens": {"provider": "openai-codex",
                                    "input": 100, "output": 0,
                                    "cached_input": 0},
                "old_path_equivalent_tokens": 1000,
                "sources_hash_set_hash": "a" * 64,
            }

        with tempfile.TemporaryDirectory() as td:
            p1 = str(Path(td) / "s1.jsonl")
            p2 = str(Path(td) / "s2.jsonl")
            e1 = L.LedgerWriter(p1, "msi").append(serve_ev())
            e2 = L.LedgerWriter(p2, "msi").append(serve_ev())
            self.assertEqual(e1["event_id"], e2["event_id"])

            summary = R.rollup([p1, p2])
            self.assertEqual(len(summary["duplicate_event_ids"]), 1)
            totals = summary["gate_valid_totals"]
            self.assertEqual(totals["reported"]["input"], 100)
            self.assertEqual(totals["context_tokens_served"], 100)

            serves = gate.load_ledger_stream(p1) \
                + gate.load_ledger_stream(p2)
            g3b = gate.compute_g3b(serves)
            self.assertEqual(g3b["serves_total"], 1)
            self.assertEqual(g3b["aggregate"]["served_tokens"],
                             totals["context_tokens_served"])
            folded, _ = gate.apply_corrections(serves)
            self.assertEqual(sum(s.reported_tokens or 0 for s in folded),
                             totals["reported"]["input"]
                             + totals["reported"]["output"])
            gdups = gate.duplicate_event_ids(serves)
            self.assertEqual(len(gdups), 1)
            rdup = summary["duplicate_event_ids"][0]
            for key in ("event_id", "stream", "line",
                        "first_stream", "first_line"):
                self.assertEqual(gdups[0][key], rdup[key])


class TestMethodWording(unittest.TestCase):
    def test_docstring_first_line_says_draft_not_frozen(self):
        # F6: the module's first line must not call the method frozen.
        first = gate.__doc__.strip().splitlines()[0]
        self.assertIn("Draft-method", first)
        self.assertNotIn("Frozen-method", first)
        self.assertIn("not frozen", gate.__doc__)


if __name__ == "__main__":
    unittest.main()
