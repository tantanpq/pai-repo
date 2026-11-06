#!/usr/bin/env python3
"""Deterministic rollup for usage-ledger streams — Phase 4, Slice 1.

Folds raw append-only JSONL streams (see ledger.py) into per-pack,
per-class, and per-brief-join summaries. The rollup is a derived
catalog: rebuildable from the raw streams at any time, and rebuilding
the same streams yields a byte-identical report (no wall-clock, no
host-dependent data anywhere in the output).

Input identity (F7): the byte-identical guarantee covers the ORDERED
stream paths exactly as given. The path labels are embedded verbatim
in the report and `streams[]` follows argument order, so the same
streams in a different order — or spelled relatively vs absolutely —
produce different report bytes (with identical gate totals). Ordered
stream paths are therefore part of the report's input identity
wherever the byte-identical property is cited for the gate.

Honesty rules (dossier §2.2, §2.4; context-package rule 4):

- `reported_tokens` and `estimated_tokens` are aggregated in separate
  strata, always. Estimated strata are keyed by the estimator name.
  No combined token figure exists anywhere in the output.
- A stream with a broken hash chain is EXCLUDED from gate-valid
  totals; the break and the affected rows (the events either side of
  each break) are NAMED in the report — never silently dropped.
- Schema-invalid or unparseable rows are likewise named (stream,
  line, event_id where recoverable, reasons) and excluded from
  totals, without condemning the rest of their stream.
- Unjoined rows (brief_id null) are listed with their named
  unjoined_reason; corrections are listed with whether their target
  event was found.
- Head commitment (F1): when a stream has a head-commitment sidecar
  (ledger.py), the folded stream's head hash and line count are
  verified against it; a mismatch EXCLUDES the stream from gate-valid
  totals, named with reason `head_commitment_mismatch` and the
  expected vs actual values. A stream with NO sidecar still folds,
  but is named in `tail_uncommitted` — its tail is uncommitted and
  tail tampering on it is undetectable (residual limit, see
  ledger.py's docstring). Never silent either way.
- Adopted streams (R1): a sidecar carrying `adopted: true` records
  that a writer adopted a previously sidecar-less stream
  (adopt_uncommitted=True). The stream folds and its post-adoption
  appends verify against the adopted head like any committed head,
  but the stream is ALSO named in `tail_uncommitted` with reason
  `adopted history`: its pre-adoption lines were never committed by
  any writer and stay honestly uncommitted.
- Healed streams (fix round 3): a sidecar carrying a non-empty
  `heals` list records that a writer healed a stale-but-exact-prefix
  sidecar (the crash window — or a chain-valid hand-append over a
  stale sidecar, which is indistinguishable from it). Healing is
  legitimate recovery and the stream still folds, but it is never
  silent: every such stream is named in `healed_streams` (stream,
  heal count, the heal entries with their line counts) in both the
  summary object and the rendered report.
- Sidecar `last_event_id` (R5): the commitment check also compares
  the sidecar's `last_event_id` (when it carries one) against the
  folded stream's last event — a sidecar whose hash and count match
  but whose named last event does not is a mismatch. (`host` in the
  sidecar remains naming metadata only: the rollup has no
  independent expectation of a stream's host to check it against.)
- Corrections never target corrections (R2): a structured correction
  whose target event is itself a correction event (including the
  correction itself, in a handcrafted stream that bypassed the
  writer's validator) is named in corrections[] with `applied:
  false` and reason `target_is_correction` — never applied, so no
  token figure can be minted by rewriting a correction.
- Per-brief view (R3): the per-brief slot carries
  `context_tokens_served` alongside its reported/estimated strata,
  so a correction to context_tokens_served is visible in EVERY
  token-carrying view (gate totals, per-pack, per-class, per-brief),
  not just three of them.
- `event_id` uniqueness is enforced across the WHOLE fold (F2):
  the first occurrence folds; later duplicates are excluded from
  all totals and named in `duplicate_event_ids`. A non-monotonic
  sequence within one host's stream is named in
  `sequence_warnings` (those rows still fold).
- Structured corrections (F3): a correction carrying
  `corrects: {target_event_id, set: {...}}` is APPLIED — the target
  event's contribution is recomputed with the corrected accounting
  fields and the corrections[] entry shows before/after token
  figures. A correction whose application would leave its target
  carrying BOTH reported_tokens and estimated_tokens is named and
  never applied. Multiple corrections to one target apply in
  (stream, line) fold order, later superseding earlier per-field.
- Corrections completeness (F8): corrections[] contains only
  corrections from streams that folded. Corrections inside an
  EXCLUDED stream are not in corrections[]; they are named in that
  stream's excluded_streams entry (event_ids / excluded_totals).
  render_report says so explicitly whenever excluded_streams is
  non-empty.

Stdlib only; Python 3.11+.
"""
import copy
import json
import os
import re
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ledger as L  # noqa: E402


def _new_bucket():
    return {
        "events": 0,
        "by_event_type": {},
        "by_outcome": {},
        # Provider-reported stratum — never merged with estimated.
        "reported": {"events": 0, "input": 0, "output": 0,
                     "cached_input": 0, "by_provider": {}},
        # Estimated stratum — keyed by named estimator, always.
        "estimated": {"events": 0, "by_estimator": {}},
        "context_tokens_served": 0,
        "old_path_equivalent_tokens": 0,
        "old_path_not_computable": 0,
    }


def _fold(bucket, ev):
    bucket["events"] += 1
    et = ev.get("event_type")
    bucket["by_event_type"][et] = bucket["by_event_type"].get(et, 0) + 1
    oc = ev.get("outcome")
    if oc is not None:
        bucket["by_outcome"][oc] = bucket["by_outcome"].get(oc, 0) + 1
    rt = ev.get("reported_tokens")
    if isinstance(rt, dict):
        rep = bucket["reported"]
        rep["events"] += 1
        rep["input"] += rt.get("input", 0)
        rep["output"] += rt.get("output", 0)
        rep["cached_input"] += rt.get("cached_input", 0)
        prov = rep["by_provider"].setdefault(
            rt.get("provider"), {"events": 0, "input": 0, "output": 0,
                                 "cached_input": 0})
        prov["events"] += 1
        prov["input"] += rt.get("input", 0)
        prov["output"] += rt.get("output", 0)
        prov["cached_input"] += rt.get("cached_input", 0)
    est = ev.get("estimated_tokens")
    if isinstance(est, dict):
        es = bucket["estimated"]
        es["events"] += 1
        name = est.get("estimator")
        slot = es["by_estimator"].setdefault(name, {"events": 0,
                                                    "value": 0})
        slot["events"] += 1
        slot["value"] += est.get("value", 0)
    cts = ev.get("context_tokens_served")
    if isinstance(cts, int) and not isinstance(cts, bool):
        bucket["context_tokens_served"] += cts
    ope = ev.get("old_path_equivalent_tokens")
    if isinstance(ope, int) and not isinstance(ope, bool):
        bucket["old_path_equivalent_tokens"] += ope
    elif "old_path_equivalent_tokens" in ev and ope is None:
        bucket["old_path_not_computable"] += 1


def _class_key(ev):
    rk = ev.get("requested_key")
    if isinstance(rk, dict):
        return f"{rk.get('domain')}/{rk.get('task_type')}"
    return "(no requested_key)"


def _affected_ids(events, breaks):
    """Event IDs either side of each break point: the row whose
    prev_hash mismatches, plus the preceding row (whose bytes the
    mismatched hash was computed over — the tamper suspect)."""
    ids = []
    for br in breaks:
        for idx in (br["line"] - 2, br["line"] - 1):  # 0-based
            if 0 <= idx < len(events):
                ev = events[idx]
                if isinstance(ev, dict) and ev.get("event_id"):
                    if ev["event_id"] not in ids:
                        ids.append(ev["event_id"])
    return ids


def _seq_of(event_id):
    m = re.match(r"^[a-z]+-(\d{4,})$", event_id or "")
    return int(m.group(1)) if m else None


def _token_snapshot(ev):
    """The accounting fields a structured correction may change —
    used for corrections[] before/after figures (F3). Copies, never
    a combined figure."""
    return {
        "reported_tokens": copy.deepcopy(ev.get("reported_tokens")),
        "estimated_tokens": copy.deepcopy(ev.get("estimated_tokens")),
        "context_tokens_served": ev.get("context_tokens_served"),
    }


def _correction_target(ev):
    corrects = ev.get("corrects")
    if isinstance(corrects, dict) \
            and isinstance(corrects.get("target_event_id"), str):
        return corrects["target_event_id"]
    return ev.get("corrects_event_id")


def rollup(stream_paths):
    """Fold the given streams into a summary dict. Pure function of
    the stream bytes (and the path labels given), so two runs over
    the same streams produce identical summaries. The ordered path
    labels are part of the input identity (F7, see module docstring).
    """
    summary = {
        "streams": [],
        "gate_valid_totals": _new_bucket(),
        "per_pack": {},
        "per_class": {},
        "per_brief": {},
        "unjoined": [],
        "corrections": [],
        "excluded_streams": [],
        "duplicate_event_ids": [],
        "sequence_warnings": [],
        "tail_uncommitted": [],
        "healed_streams": [],
    }
    seen_ids = {}          # event_id -> (stream label, line)
    fold_records = []      # (label, effective event) in fold order
    pending_corrections = []  # correction events, in fold order

    for path in stream_paths:
        label = str(path)
        stream = L.read_stream(label)
        lines, events = stream["lines"], stream["events"]
        breaks = L.verify_chain(lines, events)

        # Head commitment (F1): verify the folded stream's head hash
        # + line count against the writer's sidecar when one exists.
        commitment = L.read_head_commitment(label)
        actual_head = {
            "head_hash": (L.line_hash(lines[-1]) if lines
                          else L.GENESIS_HASH),
            "line_count": len(lines),
            "last_event_id": None,
        }
        for ev in reversed(events):
            if isinstance(ev, dict) and ev.get("event_id"):
                actual_head["last_event_id"] = ev["event_id"]
                break
        if commitment is None:
            head_status = "missing"
            head_mismatch = False
        else:
            # R5: last_event_id is compared too, when the sidecar
            # carries one — hash+count alone left it forgeable.
            head_mismatch = (
                commitment.get("head_hash") != actual_head["head_hash"]
                or commitment.get("line_count")
                != actual_head["line_count"]
                or (commitment.get("last_event_id") is not None
                    and commitment.get("last_event_id")
                    != actual_head["last_event_id"]))
            head_status = "mismatch" if head_mismatch else "ok"

        invalid_rows = []
        valid_events = []  # (lineno, event)
        for i, ev in enumerate(events):
            lineno = i + 1
            if ev is None:
                invalid_rows.append({
                    "line": lineno, "event_id": None,
                    "reasons": [stream["parse_errors"][lineno]]})
                continue
            reasons = L.validate_event(ev, stored=True)
            if reasons:
                invalid_rows.append({
                    "line": lineno,
                    "event_id": ev.get("event_id"),
                    "reasons": reasons})
                continue
            valid_events.append((lineno, ev))

        gate_valid = not breaks and not head_mismatch
        s_entry = {
            "path": label,
            "lines": len(lines),
            "valid_events": len(valid_events),
            "invalid_rows": invalid_rows,
            "chain_ok": not breaks,
            "chain_breaks": breaks,
            "head_commitment": head_status,
            "gate_valid": gate_valid,
        }
        summary["streams"].append(s_entry)

        # Healed streams (fix round 3): a sidecar carrying a
        # non-empty `heals` list means a writer healed a stale
        # exact-prefix sidecar. The stream still folds when it is
        # gate-valid (healing is legitimate recovery), but the heal
        # is named here — never silent — in both the summary and,
        # via render_report, the rendered report.
        heals = commitment.get("heals") if isinstance(
            commitment, dict) else None
        if isinstance(heals, list) and heals:
            summary["healed_streams"].append({
                "path": label,
                "stream": label,
                "heal_count": len(heals),
                "heals": copy.deepcopy(heals),
                "healed_at_line_counts": [
                    h.get("healed_at_line_count")
                    if isinstance(h, dict) else None for h in heals],
                "stream_lines_at_heal": [
                    h.get("stream_lines_at_heal")
                    if isinstance(h, dict) else None for h in heals],
                "reason": "healed: this stream's writer healed a "
                          "stale exact-prefix head-commitment "
                          "sidecar; the heal(s) are recorded "
                          "durably in the sidecar's heals list — "
                          "the stream folds, but the heal is "
                          "named, never silent",
            })

        if not gate_valid:
            # Whole stream excluded from gate-valid totals (§2.2);
            # affected rows named, stream's own strata shown here so
            # nothing vanishes. Corrections in an excluded stream stay
            # excluded with it (F8): they are named here via
            # event_ids / excluded_totals, not in corrections[].
            excluded_bucket = _new_bucket()
            all_ids = []
            for _, ev in valid_events:
                _fold(excluded_bucket, ev)
                all_ids.append(ev.get("event_id"))
            if breaks:
                entry = {
                    "path": label,
                    "reason": ("hash chain broken at line(s) "
                               + ", ".join(str(b["line"])
                                           for b in breaks)
                               + "; stream excluded from gate-valid "
                               "totals"),
                    "affected_event_ids": _affected_ids(events,
                                                        breaks),
                    "event_ids": all_ids,
                    "excluded_totals": excluded_bucket,
                }
            else:
                entry = {
                    "path": label,
                    "reason": "head_commitment_mismatch",
                    "reason_detail": (
                        "folded stream head does not match the "
                        "writer's head-commitment sidecar; stream "
                        "excluded from gate-valid totals"),
                    "expected": {
                        "head_hash": commitment.get("head_hash"),
                        "line_count": commitment.get("line_count"),
                        "last_event_id": commitment.get(
                            "last_event_id"),
                    },
                    "actual": actual_head,
                    "affected_event_ids": (
                        [actual_head["last_event_id"]]
                        if actual_head["last_event_id"] else []),
                    "event_ids": all_ids,
                    "excluded_totals": excluded_bucket,
                }
            summary["excluded_streams"].append(entry)
            continue

        if commitment is None:
            # No sidecar: the stream folds, but its tail is
            # uncommitted — named, never silent (F1 residual limit).
            summary["tail_uncommitted"].append({
                "path": label,
                "reason": "no head-commitment sidecar exists for "
                          "this stream; its tail is uncommitted",
            })
        elif commitment.get("adopted"):
            # Adopted stream (R1): it folds and its head verifies,
            # but the history before adoption was never committed by
            # any writer — named, never silent.
            summary["tail_uncommitted"].append({
                "path": label,
                "adopted": True,
                "adopted_at_line_count": commitment.get(
                    "adopted_at_line_count"),
                "reason": "adopted history: this stream was adopted "
                          "by a writer (adopt_uncommitted=True) at "
                          "the line_count named in "
                          "adopted_at_line_count, without a prior "
                          "head commitment; pre-adoption history is "
                          "uncommitted, post-adoption appends verify "
                          "against the adopted head",
            })

        last_seq = None
        for lineno, ev in valid_events:
            seq = _seq_of(ev.get("event_id"))
            if seq is not None:
                if last_seq is not None and seq < last_seq:
                    summary["sequence_warnings"].append({
                        "event_id": ev["event_id"], "stream": label,
                        "line": lineno, "sequence": seq,
                        "previous_sequence": last_seq,
                        "reason": "event_id sequence is "
                                  "non-monotonic within this "
                                  "stream"})
                last_seq = seq
            eid = ev["event_id"]
            if eid in seen_ids:
                first_stream, first_line = seen_ids[eid]
                summary["duplicate_event_ids"].append({
                    "event_id": eid, "stream": label, "line": lineno,
                    "first_stream": first_stream,
                    "first_line": first_line,
                    "reason": "duplicate event_id; first occurrence "
                              "folds, this occurrence is excluded "
                              "from all totals"})
                continue
            seen_ids[eid] = (label, lineno)
            effective = copy.deepcopy(ev)
            fold_records.append((label, effective))
            if effective.get("event_type") == "correction":
                pending_corrections.append((effective, label))

    # ---- structured corrections (F3): applied after the whole fold,
    # so target resolution is order-independent (as before). Multiple
    # corrections to one target apply in fold order; later supersedes
    # earlier per-field. A correction whose application would leave
    # the target carrying BOTH token fields is named, never applied.
    effective_by_id = {ev["event_id"]: ev for _, ev in fold_records}
    for ev, label in pending_corrections:
        target_id = _correction_target(ev)
        # Slice 4 fix F2 (additive surfacing only): surface the
        # correction kind, defaulting an absent kind to error_fix.
        _kind = None
        if isinstance(ev.get("corrects"), dict):
            _kind = ev["corrects"].get("kind")
        entry = {
            "event_id": ev["event_id"], "stream": label,
            "corrects_event_id": target_id,
            "target_found": target_id in effective_by_id,
            "correction": ev.get("correction"),
            "kind": _kind if _kind in L.CORRECTION_KINDS
                    else L.DEFAULT_CORRECTION_KIND,
        }
        if isinstance(ev.get("corrects"), dict):
            entry["corrects"] = copy.deepcopy(ev["corrects"])
        cset = None
        if isinstance(ev.get("corrects"), dict):
            cset = ev["corrects"].get("set")
        if isinstance(cset, dict) and cset:
            if target_id not in effective_by_id:
                entry["applied"] = False
                entry["not_applied_reason"] = (
                    "structured correction target not found among "
                    "folded events")
            else:
                target = effective_by_id[target_id]
                before = _token_snapshot(target)
                new_reported = cset.get(
                    "reported_tokens", target.get("reported_tokens"))
                new_estimated = cset.get(
                    "estimated_tokens",
                    target.get("estimated_tokens"))
                if target.get("event_type") == "correction":
                    # R2: corrections never target corrections —
                    # including this correction itself (target_id ==
                    # its own event_id in a handcrafted stream).
                    # Applying the set to a correction event would
                    # mint token figures no serve ever carried.
                    entry["applied"] = False
                    entry["not_applied_reason"] = (
                        "target_is_correction: the correction's "
                        "target is itself a correction event; "
                        "corrections never target corrections — "
                        "named, not applied")
                elif new_reported is not None \
                        and new_estimated is not None:
                    entry["applied"] = False
                    entry["not_applied_reason"] = (
                        "correction would leave the target carrying "
                        "both reported_tokens and estimated_tokens: "
                        "an event is metered or estimated, never "
                        "both; correction named, not applied")
                else:
                    for field, value in cset.items():
                        target[field] = copy.deepcopy(value)
                    entry["applied"] = True
                    entry["before"] = before
                    entry["after"] = _token_snapshot(target)
        summary["corrections"].append(entry)

    # ---- fold the effective (post-correction) events into totals.
    for label, ev in fold_records:
        _fold(summary["gate_valid_totals"], ev)
        if ev.get("pack_id"):
            key = f"{ev['pack_id']}@v{ev.get('pack_version')}"
            _fold(summary["per_pack"].setdefault(
                key, _new_bucket()), ev)
        _fold(summary["per_class"].setdefault(
            _class_key(ev), _new_bucket()), ev)
        bid = ev.get("brief_id")
        if bid:
            slot = summary["per_brief"].setdefault(
                bid, {"events": 0, "event_ids": [],
                      "reported": {"events": 0, "input": 0,
                                   "output": 0, "cached_input": 0},
                      "estimated": {"events": 0,
                                    "by_estimator": {}},
                      "context_tokens_served": 0})
            slot["events"] += 1
            slot["event_ids"].append(ev["event_id"])
            # R3: per-brief carries context_tokens_served too, so a
            # correction to it shows in this view like every other.
            cts = ev.get("context_tokens_served")
            if isinstance(cts, int) and not isinstance(cts, bool):
                slot["context_tokens_served"] += cts
            rt = ev.get("reported_tokens")
            if isinstance(rt, dict):
                r = slot["reported"]
                r["events"] += 1
                r["input"] += rt.get("input", 0)
                r["output"] += rt.get("output", 0)
                r["cached_input"] += rt.get("cached_input", 0)
            est = ev.get("estimated_tokens")
            if isinstance(est, dict):
                es = slot["estimated"]
                es["events"] += 1
                s2 = es["by_estimator"].setdefault(
                    est.get("estimator"), {"events": 0, "value": 0})
                s2["events"] += 1
                s2["value"] += est.get("value", 0)
        elif bid is None and ev.get("event_type") != "correction":
            summary["unjoined"].append({
                "event_id": ev["event_id"], "stream": label,
                "unjoined_reason": ev.get("unjoined_reason")})
    return summary


def render_report(summary):
    """Byte-stable text form of a summary: sorted keys, fixed
    indentation, single trailing newline, no timestamps.

    F8: when excluded_streams is non-empty, an explicit note line is
    added (as a `note` field, keeping the report valid JSON): the
    corrections[] list does not include events from excluded streams
    — those events are named in excluded_streams instead."""
    out = summary
    if summary.get("excluded_streams"):
        out = dict(summary)
        out["note"] = (
            "corrections[] does not include events from excluded "
            "streams; events from excluded streams are named in "
            "excluded_streams[].event_ids")
    return json.dumps(out, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def rollup_report(stream_paths):
    """Convenience: fold streams and render the report text."""
    return render_report(rollup(stream_paths))
