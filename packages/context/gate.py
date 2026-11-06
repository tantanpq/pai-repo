"""Draft-method gate report generator — PAI Repo Phase 4, Slice 5 machinery.

The method implemented here is a DRAFT, not frozen: the freeze waits
for the baseline re-run plus the 2026-11-14 review.

Implements the gate protocol of PHASE4_DESIGN_DOSSIER_V1.md §3.3 from RAW
inputs only (codex-cp receipts + per-job stdout.log usage + usage-ledger
JSONL streams). The library's own rollup summaries are never an input
(dossier §2.4.5 / §3.4 guard 5).

Status: MACHINERY + REHEARSAL ONLY. The method is DRAFT — NOT FROZEN
(see GATE_METHOD_DRAFT.md in the Phase 4 programme folder). This module
computes G1/G2/G3 components; it does not freeze a baseline, run a gate
week, or declare a gate verdict on real data.

Method (identical definitions on both sides, per the TokenEconomizer
review prep brief, Measure 2):
  * finished brief  = a codex-cp receipt with status == "done"
  * tokens          = input + output summed over the job's stdout.log
                      ``turn.completed`` usage events; cached input is a
                      subset of input and is counted in full (never
                      subtracted, never double-added)
  * window membership = receipt ``started_at`` in [start, end) UTC

Token accounting discipline (contracts/context-package.md rule 4):
provider-reported tokens and locally estimated tokens live in separate
fields/strata and are NEVER summed — not here, not in any rollup.

Stdlib only. Python 3.10+.
"""

from __future__ import annotations

import copy
import json
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_VERSION = "gate.py 1.0.0 (Slice 5, method DRAFT — not frozen)"

# --- Pre-registered thresholds (dossier §3.3; ◈ CHOICE values, TQ1) ---
COVERAGE_THRESHOLD = 0.90          # G1: below => week INVALID, not failed
HARM_BOUND = 0.10                  # G3a: per-class mean may rise at most 10%
MIN_CLASS_N = 3                    # G3a applies only at n >= 3 on both sides
MICRO_CLASS_TOKENS = 500           # G3b: old-path < 500 => micro exception
NONCOMPUTABLE_PARTIAL_SHARE = 0.20  # G3b: >20% non-computable => PARTIAL

# --- Class taxonomy (dossier §3.2; derivation rules in GATE_METHOD_DRAFT.md)
CLASS_NIGHTLY_PRODUCTION = "nightly_recurring_production"
CLASS_REVIEW = "named_review_rereview"
CLASS_FIX = "named_fix"
CLASS_HASHED_DRIVE_DOC = "hashed_drive_doc_pipeline"
CLASS_CENSUS_BUILD = "census_build"
CLASS_OTHER_NAMED = "other_named_lane_brief"
CLASS_INTERACTIVE_SESSION = "interactive_same_repo_session"
EXCLUDED_NOTEBOOK_CP = "notebook_cp"

STRATUM_BRIEF = "brief"
STRATUM_SESSION = "session"
STRATUM_EXCLUDED = "excluded"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def parse_iso(ts):
    """Parse an ISO-8601 timestamp to an aware UTC datetime (or None)."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    s = str(ts).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(value):
    """Coerce a token count to int; anything else becomes 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


# --------------------------------------------------------------------------
# Usage extraction from stdout.log (the TE prep brief's meter)
# --------------------------------------------------------------------------

@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    turns: int = 0

    @property
    def total(self):
        # input already includes cached input; counting input in full IS
        # counting cached input in full. Never add cached on top.
        return self.input_tokens + self.output_tokens


def usage_from_event(event):
    """UsageTotals for one parsed stdout.log line, or None if not a
    ``turn.completed`` event carrying usage."""
    if not isinstance(event, dict) or event.get("type") != "turn.completed":
        return None
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None
    return UsageTotals(
        input_tokens=_num(usage.get("input_tokens", usage.get("input", 0))),
        output_tokens=_num(usage.get("output_tokens", usage.get("output", 0))),
        cached_input_tokens=_num(
            usage.get("cached_input_tokens", usage.get("cached_input", 0))),
        turns=1,
    )


def extract_usage_from_text(text):
    """Sum usage over all turn.completed lines in stdout.log text.

    Lines that are not JSON, or JSON without turn.completed usage, are
    ignored — exactly the prep brief scripts' behaviour.
    """
    total = UsageTotals()
    for line in text.splitlines():
        if '"turn.completed"' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        u = usage_from_event(event)
        if u is None:
            continue
        total.input_tokens += u.input_tokens
        total.output_tokens += u.output_tokens
        total.cached_input_tokens += u.cached_input_tokens
        total.turns += 1
    return total


def extract_usage_from_log(path):
    """UsageTotals for a stdout.log file; empty totals if absent/empty."""
    p = Path(path)
    if not p.is_file():
        return UsageTotals()
    return extract_usage_from_text(p.read_text(encoding="utf-8", errors="replace"))


# --------------------------------------------------------------------------
# Class taxonomy — deterministic rules over the receipt brief name
# --------------------------------------------------------------------------

_DRIVE_ID_RE = re.compile(r"^[01][0-9A-Za-z_-]{24,}")
_HEX_RE = re.compile(r"^[0-9a-fA-F]{24,}$")
_LONG_TOKEN_RE = re.compile(r"^[0-9A-Za-z_-]{28,}-[0-9a-fA-F]{8}$")


def classify_brief(name):
    """Classify a brief/job name -> (class_name, stratum, exclusion_reason).

    Deterministic, first-match-wins, in this priority order (documented
    in GATE_METHOD_DRAFT.md):
      1. notebook-cp            -> named exclusion (no Codex token accounting)
      2. interactive / session  -> interactive same-repo session stratum
      3. prod-* / nightly       -> nightly recurring production (incl. the
                                   prod-M-C11 series)
      4. Drive-ID-like / hex / long-token hash prefix -> hashed Drive-doc
                                   pipeline
      5. review / rereview      -> named review/rereview
      6. census / claimreg / build -> census/build
      7. fix                    -> named fix
      8. fallback               -> other named lane briefs
    """
    n = (name or "").strip()
    low = n.lower()
    if "notebook" in low:
        return (None, STRATUM_EXCLUDED,
                "notebook-cp: NotebookLM ask service, no Codex token accounting")
    if "interactive" in low or low.startswith("session") or "-session" in low:
        return (CLASS_INTERACTIVE_SESSION, STRATUM_SESSION, None)
    if re.match(r"(?i)^prod[-_]", n) or "nightly" in low:
        return (CLASS_NIGHTLY_PRODUCTION, STRATUM_BRIEF, None)
    head = n.split("/")[0]
    if (_DRIVE_ID_RE.match(head) or _HEX_RE.match(head)
            or _LONG_TOKEN_RE.match(head)):
        return (CLASS_HASHED_DRIVE_DOC, STRATUM_BRIEF, None)
    if "rereview" in low or "review" in low:
        return (CLASS_REVIEW, STRATUM_BRIEF, None)
    if "census" in low or "claimreg" in low or "build" in low:
        return (CLASS_CENSUS_BUILD, STRATUM_BRIEF, None)
    if "fix" in low:
        return (CLASS_FIX, STRATUM_BRIEF, None)
    return (CLASS_OTHER_NAMED, STRATUM_BRIEF, None)


# --------------------------------------------------------------------------
# Brief records (raw-input side)
# --------------------------------------------------------------------------

@dataclass
class BriefRecord:
    job_key: str
    name: str                       # name the taxonomy classifies (job_key)
    brief_id: str | None = None
    status: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    reported_tokens: int | None = None   # None => no metered usage found
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    turns: int = 0
    class_name: str | None = None
    stratum: str = STRATUM_BRIEF
    exclusion_reason: str | None = None

    def __post_init__(self):
        if self.class_name is None and self.stratum == STRATUM_BRIEF \
                and self.exclusion_reason is None:
            cls, stratum, reason = classify_brief(self.name)
            self.class_name, self.stratum, self.exclusion_reason = cls, stratum, reason

    @property
    def is_finished(self):
        return self.status == "done"

    @property
    def join_keys(self):
        keys = {self.job_key}
        if self.brief_id:
            keys.add(self.brief_id)
        return keys


def receipt_to_record(receipt, usage=None):
    """BriefRecord from one codex-cp receipt dict (+ optional UsageTotals
    already extracted from that job's stdout.log)."""
    job_key = str(receipt.get("job_key") or receipt.get("name") or "")
    rec = BriefRecord(
        job_key=job_key,
        name=job_key,
        brief_id=receipt.get("brief_id"),
        status=receipt.get("status"),
        started_at=parse_iso(receipt.get("started_at") or receipt.get("ts")),
        ended_at=parse_iso(receipt.get("ended_at") or receipt.get("finished_at")),
    )
    if usage is not None and usage.turns > 0:
        rec.reported_tokens = usage.total
        rec.input_tokens = usage.input_tokens
        rec.output_tokens = usage.output_tokens
        rec.cached_input_tokens = usage.cached_input_tokens
        rec.turns = usage.turns
    return rec


def load_receipt_dir(jobs_dir):
    """Load every ``<jobs_dir>/*/receipt.json`` + sibling ``stdout.log``."""
    root = Path(jobs_dir)
    records = []
    for job_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        rp = job_dir / "receipt.json"
        if not rp.is_file():
            continue
        try:
            receipt = json.loads(rp.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            continue
        usage = extract_usage_from_log(job_dir / "stdout.log")
        records.append(receipt_to_record(receipt, usage))
    return records


def load_snapshot(path):
    """Load a compact extraction snapshot (rehearsal form): JSON with a
    ``jobs`` list of {name, status, started_at, ended_at, brief_id,
    input_tokens, output_tokens, cached_input_tokens, turns}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    jobs = data["jobs"] if isinstance(data, dict) else data
    records = []
    for j in jobs:
        name = str(j.get("name") or j.get("job_key") or "")
        rec = BriefRecord(
            job_key=str(j.get("job_key") or name),
            name=name,
            brief_id=j.get("brief_id"),
            status=j.get("status"),
            started_at=parse_iso(j.get("started_at")),
            ended_at=parse_iso(j.get("ended_at")),
            input_tokens=_num(j.get("input_tokens")),
            output_tokens=_num(j.get("output_tokens")),
            cached_input_tokens=_num(j.get("cached_input_tokens")),
            turns=_num(j.get("turns")),
        )
        if rec.turns > 0 or rec.input_tokens or rec.output_tokens:
            rec.reported_tokens = rec.input_tokens + rec.output_tokens
        records.append(rec)
    return records


# --------------------------------------------------------------------------
# Window statistics
# --------------------------------------------------------------------------

def _stats(values):
    if not values:
        return {"n": 0, "total": 0, "mean": None, "median": None,
                "min": None, "max": None}
    return {
        "n": len(values),
        "total": sum(values),
        "mean": sum(values) / len(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def window_stats(records, start, end):
    """Per-window census stats over finished briefs with metered usage.

    Window membership: started_at in [start, end). Returns overall figures
    (tokens/brief rounded like the prep brief), per-class tables, the
    separate session stratum, named exclusions, and the named list of
    finished briefs without usage (never silently dropped).
    """
    start_dt, end_dt = parse_iso(start), parse_iso(end)
    in_window = [r for r in records if r.started_at is not None
                 and start_dt <= r.started_at < end_dt]
    finished = [r for r in in_window if r.is_finished]
    briefs = [r for r in finished if r.stratum == STRATUM_BRIEF]
    sessions = [r for r in finished if r.stratum == STRATUM_SESSION]
    excluded = [r for r in in_window if r.stratum == STRATUM_EXCLUDED]
    with_usage = [r for r in briefs if r.reported_tokens is not None]
    without_usage = [r for r in briefs if r.reported_tokens is None]

    per_class = {}
    for r in with_usage:
        per_class.setdefault(r.class_name, []).append(r.reported_tokens)
    class_table = {cls: _stats(vals) for cls, vals in sorted(per_class.items())}
    for cls, st in class_table.items():
        st["mean_rounded"] = round(st["mean"]) if st["mean"] is not None else None

    total = sum(r.reported_tokens for r in with_usage)
    n = len(with_usage)
    days = (end_dt - start_dt).total_seconds() / 86400.0
    return {
        "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat(),
                   "days": round(days, 2)},
        "finished_briefs": len(briefs),
        "finished_with_usage": n,
        "total_tokens": total,
        "tokens_per_finished_brief": round(total / n) if n else None,
        "briefs_per_day": round(len(briefs) / days, 1) if days else None,
        "classes": class_table,
        "session_stratum": _stats([r.reported_tokens for r in sessions
                                   if r.reported_tokens is not None]),
        "excluded_named": [{"name": r.name, "reason": r.exclusion_reason}
                           for r in excluded],
        "finished_without_usage_named": [r.name for r in without_usage],
    }


def class_shares(class_table):
    """Baseline class shares: share of finished-with-usage briefs per class."""
    total_n = sum(st["n"] for st in class_table.values())
    if not total_n:
        return {}
    return {cls: st["n"] / total_n for cls, st in class_table.items()}


def matched_series(records, pattern, start, end, exclude_first_run=False):
    """Like-for-like stats for one recurring series (name regex) in a window.

    ``exclude_first_run`` drops the chronologically first run of the whole
    series (all records, any window) — the prep brief's first-run outlier
    handling for prod-M-C11, made explicit rather than silent.
    """
    rx = re.compile(pattern)
    series = sorted((r for r in records if rx.search(r.name or "")
                     and r.is_finished and r.stratum == STRATUM_BRIEF
                     and r.reported_tokens is not None
                     and r.started_at is not None),
                    key=lambda r: r.started_at)
    if exclude_first_run and series:
        series = series[1:]
    start_dt, end_dt = parse_iso(start), parse_iso(end)
    vals = [r.reported_tokens for r in series if start_dt <= r.started_at < end_dt]
    st = _stats(vals)
    if st["mean"] is not None:
        st["mean_rounded"] = round(st["mean"])
    return st


# --------------------------------------------------------------------------
# Usage-ledger streams (serve side)
# --------------------------------------------------------------------------

@dataclass
class ServeRecord:
    event_id: str | None = None
    brief_id: str | None = None
    event_type: str | None = None
    outcome: str | None = None
    served_tokens: int | None = None        # context_tokens_served (new path)
    reported_tokens: int | None = None      # provider-reported, own field
    estimated_tokens: int | None = None     # local estimate, NEVER summed up
    estimator: str | None = None
    old_path_equivalent_tokens: int | None = None
    not_computable_reason: str | None = None
    # Raw fields kept so Slice 1's structured corrections can be folded
    # with rollup.py's semantics (delta-2, item 4): the raw
    # context_tokens_served (served_tokens above falls back to the
    # reported total when it is absent), the correction payload of a
    # correction event, and its free-standing target reference.
    context_tokens_served: int | None = None
    corrects: dict | None = None
    corrects_event_id: str | None = None
    # Provenance for duplicate naming (delta-3, D2): the stream label
    # and 1-based line the record was loaded from, when loaded via
    # load_ledger_stream; None for records built in memory.
    stream: str | None = None
    line: int | None = None


def _reported_total(obj):
    if isinstance(obj, dict):
        return _num(obj.get("input")) + _num(obj.get("output"))
    if isinstance(obj, (int, float)):
        return _num(obj)
    return None


def ledger_event_to_serve(event, stream=None, line=None):
    rep = event.get("reported_tokens")
    est = event.get("estimated_tokens")
    old = event.get("old_path_equivalent_tokens")
    cts = event.get("context_tokens_served")
    corrects = event.get("corrects")
    return ServeRecord(
        event_id=event.get("event_id"),
        brief_id=event.get("brief_id"),
        event_type=event.get("event_type"),
        outcome=event.get("outcome"),
        served_tokens=(cts if cts is not None else _reported_total(rep)),
        reported_tokens=_reported_total(rep) if rep is not None else None,
        estimated_tokens=(est.get("value") if isinstance(est, dict)
                          else (_num(est) if est is not None else None)),
        estimator=(est.get("estimator") if isinstance(est, dict) else None),
        old_path_equivalent_tokens=(_num(old) if old is not None else None),
        not_computable_reason=event.get("not_computable_reason"),
        context_tokens_served=(_num(cts) if cts is not None else None),
        corrects=(copy.deepcopy(corrects) if isinstance(corrects, dict)
                  else None),
        corrects_event_id=event.get("corrects_event_id"),
        stream=stream,
        line=line,
    )


def load_ledger_stream(path):
    """Load one append-only usage-ledger JSONL stream -> ServeRecords.

    Each record carries its provenance (stream label = the path as
    given, line = the 1-based file line, counting blank/unparseable
    lines exactly as rollup.py numbers stream lines) so duplicate
    event_ids can be named with event_id + stream + line (delta-3, D2).
    """
    serves = []
    raw_lines = Path(path).read_text(
        encoding="utf-8", errors="replace").splitlines()
    for lineno, line in enumerate(raw_lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            serves.append(ledger_event_to_serve(
                event, stream=str(path), line=lineno))
    return serves


# --------------------------------------------------------------------------
# Structured corrections — folded with Slice 1 rollup.py semantics
# (delta-2, item 4; rollup.py's F3 disposition, mirrored here because
# rollup's application logic is embedded in its stream fold and is not
# cleanly exposed as a reusable function). A correction event's
# ``corrects: {target_event_id, set}`` replaces the target's
# reported_tokens / estimated_tokens / context_tokens_served BEFORE
# any gate math. Target resolution is order-independent; multiple
# corrections to one target apply in stream order, later superseding
# earlier per-field. A correction whose application would leave its
# target carrying BOTH token fields is named and NOT applied;
# corrections to unknown targets are named, not applied. A
# cross-module golden test in test_gate.py folds one fixture stream
# through BOTH rollup.py and this module and requires identical
# corrected per-event figures.
#
# Delta-3 alignments with rollup.py as settled by Slice 1 fix round 2:
# (D1) corrections never target corrections (rollup R2): a correction
# whose target record is itself a correction event — including the
# correction itself — is named (reason ``target_is_correction``) and
# NOT applied, with rollup's precedence: target-not-found, then
# target-is-correction, then never-both.
# (D2) event_id uniqueness (rollup F2): the first occurrence of an
# event_id folds; later duplicates are excluded from ALL gate math
# (corrections included) and named with event_id + stream + line.
# --------------------------------------------------------------------------

CORRECTION_SET_FIELDS = ("reported_tokens", "estimated_tokens",
                         "context_tokens_served")

NEVER_BOTH_REASON = ("correction would leave the target carrying both "
                     "reported_tokens and estimated_tokens: an event is "
                     "metered or estimated, never both; correction "
                     "named, not applied")

UNKNOWN_TARGET_REASON = ("structured correction target not found among "
                         "folded events")

TARGET_IS_CORRECTION_REASON = (
    "target_is_correction: the correction's target is itself a "
    "correction event; corrections never target corrections — "
    "named, not applied")

DUPLICATE_EVENT_ID_REASON = (
    "duplicate event_id; first occurrence folds, this occurrence is "
    "excluded from all totals")


def _correction_target_id(rec):
    if isinstance(rec.corrects, dict):
        target = rec.corrects.get("target_event_id")
        if isinstance(target, str) and target:
            return target
    return rec.corrects_event_id


def _token_figures(rec):
    """A record's corrected per-event accounting figures, in this
    module's units (reported as the input+output total)."""
    return {"reported_tokens": rec.reported_tokens,
            "estimated_tokens": rec.estimated_tokens,
            "context_tokens_served": rec.context_tokens_served}


def _apply_correction_set(target, cset):
    """Apply one validated ``corrects.set`` mapping to a ServeRecord,
    replacing only the three accounting fields (rollup F3)."""
    for field_name in CORRECTION_SET_FIELDS:
        if field_name not in cset:
            continue
        value = cset[field_name]
        if field_name == "reported_tokens":
            target.reported_tokens = (_reported_total(value)
                                      if value is not None else None)
        elif field_name == "estimated_tokens":
            if value is None:
                target.estimated_tokens = None
                target.estimator = None
            elif isinstance(value, dict):
                target.estimated_tokens = _num(value.get("value"))
                target.estimator = value.get("estimator")
            else:
                target.estimated_tokens = _num(value)
                target.estimator = None
        else:  # context_tokens_served
            target.context_tokens_served = (_num(value)
                                            if value is not None else None)
    # served_tokens derives from the raw fields, exactly as in
    # ledger_event_to_serve: explicit context_tokens_served wins,
    # otherwise the (possibly corrected) reported total.
    target.served_tokens = (target.context_tokens_served
                            if target.context_tokens_served is not None
                            else target.reported_tokens)


def _stream_line(rec, fallback_index):
    """A record's (stream, line) for duplicate naming: the provenance
    captured by load_ledger_stream when present, else the record's
    1-based position in the list being folded (stream unknown)."""
    line = rec.line if rec.line is not None else fallback_index + 1
    return rec.stream, line


def duplicate_event_ids(serves):
    """Named duplicate event_ids in a ServeRecord list, with rollup.py's
    F2 semantics (delta-3, D2): the first occurrence of an event_id
    folds; every later occurrence is excluded from all gate math and
    named here with its event_id, stream and line (plus the first
    occurrence's stream/line). Records without an event_id cannot be
    duplicates and are never named here."""
    seen = {}
    named = []
    for i, rec in enumerate(serves):
        eid = rec.event_id
        if eid is None:
            continue
        stream, line = _stream_line(rec, i)
        if eid in seen:
            first_stream, first_line = seen[eid]
            named.append({
                "event_id": eid, "stream": stream, "line": line,
                "first_stream": first_stream, "first_line": first_line,
                "reason": DUPLICATE_EVENT_ID_REASON})
        else:
            seen[eid] = (stream, line)
    return named


def _dedupe(records):
    """Split records into (first occurrences, duplicate-named entries),
    rollup F2: later duplicates of an event_id are dropped entirely —
    a duplicate correction is not folded either, exactly as rollup
    excludes duplicates before its correction pass."""
    named = duplicate_event_ids(records)
    seen, unique = set(), []
    for rec in records:
        if rec.event_id is not None:
            if rec.event_id in seen:
                continue
            seen.add(rec.event_id)
        unique.append(rec)
    return unique, named


def apply_corrections(serves):
    """Fold structured corrections over a ServeRecord list.

    Returns ``(folded_serves, corrections_named)``: the non-correction
    records with every applicable correction applied (input records
    are not mutated), and one named entry per correction event —
    applied (with before/after figures) or not applied (with the
    reason). Mirrors rollup.py's F3 semantics, plus its R2 guard
    (delta-3, D1) and F2 duplicate exclusion (delta-3, D2): duplicate
    event_ids are removed before folding (first occurrence counts);
    the duplicate naming itself is surfaced by
    ``duplicate_event_ids`` / the report builder."""
    records = copy.deepcopy(list(serves))
    records, _dup_named = _dedupe(records)
    by_id = {}
    for rec in records:
        if rec.event_id is not None and rec.event_id not in by_id:
            by_id[rec.event_id] = rec
    folded, named = [], []
    for rec in records:
        if rec.event_type != "correction":
            folded.append(rec)
            continue
        target_id = _correction_target_id(rec)
        entry = {"event_id": rec.event_id,
                 "target_event_id": target_id,
                 "target_found": target_id in by_id}
        cset = rec.corrects.get("set") if isinstance(rec.corrects, dict) \
            else None
        if isinstance(cset, dict) and cset:
            if target_id not in by_id:
                entry["applied"] = False
                entry["not_applied_reason"] = UNKNOWN_TARGET_REASON
            else:
                target = by_id[target_id]
                if target.event_type == "correction":
                    # D1 / rollup R2: corrections never target
                    # corrections — including this correction itself
                    # (a self-target resolves to its own record).
                    # Checked BEFORE never-both, rollup's precedence:
                    # applying the set to a correction record would
                    # mint figures no serve ever carried.
                    entry["applied"] = False
                    entry["not_applied_reason"] = \
                        TARGET_IS_CORRECTION_REASON
                    named.append(entry)
                    continue
                new_reported = (cset["reported_tokens"]
                                if "reported_tokens" in cset
                                else target.reported_tokens)
                new_estimated = (cset["estimated_tokens"]
                                 if "estimated_tokens" in cset
                                 else target.estimated_tokens)
                # Presence after application, in raw set terms for the
                # replaced field and record terms for the kept field:
                # a set value of None clears the field.
                rep_present = new_reported is not None
                est_present = new_estimated is not None
                if rep_present and est_present:
                    entry["applied"] = False
                    entry["not_applied_reason"] = NEVER_BOTH_REASON
                else:
                    before = _token_figures(target)
                    _apply_correction_set(target, cset)
                    entry["applied"] = True
                    entry["before"] = before
                    entry["after"] = _token_figures(target)
        named.append(entry)
    return folded, named


def _folded(serves):
    """The correction-folded serve list (naming discarded; the report
    builder surfaces the named entries via apply_corrections)."""
    return apply_corrections(serves)[0]


BOTH_TOKENS_REASON = ("both reported_tokens and estimated_tokens present "
                      "— out of schema; excluded from both strata")


def invalid_token_events(serves):
    """Ledger events carrying BOTH reported_tokens and estimated_tokens.

    Such an event is out of schema (Slice 1's validator rejects it):
    it is named here and excluded from BOTH token strata — its reported
    value never joins or totals, its estimated value never enters the
    estimated stratum — instead of silently using one field and
    dropping the other. Naming is over the RAW stream (an out-of-schema
    event is named as written, even if a correction elsewhere in the
    stream would change its fields)."""
    return [{"event_id": s.event_id, "reason": BOTH_TOKENS_REASON}
            for s in serves if s.reported_tokens is not None
            and s.estimated_tokens is not None]


def estimated_stratum(serves):
    """The estimated-token stratum, reported separately and never summed
    into any reported-token figure (contract rule 4). Events carrying
    both reported and estimated tokens are out of schema: they are
    excluded here too and named via ``invalid_token_events``.
    Structured corrections are folded first (delta-2, item 4)."""
    est = [s for s in _folded(serves) if s.estimated_tokens is not None
           and s.reported_tokens is None]
    return {
        "events": len(est),
        "estimated_tokens_total": sum(s.estimated_tokens for s in est),
        "estimators_named": sorted({s.estimator or "UNNAMED" for s in est}),
        "event_ids": [s.event_id for s in est],
    }


# --------------------------------------------------------------------------
# G1 — coverage
# --------------------------------------------------------------------------

def compute_g1(gate_records, serves, start, end):
    """Coverage: share of the window's finished briefs that join to >= 1
    ledger event carrying reported_tokens. Below threshold => INVALID."""
    start_dt, end_dt = parse_iso(start), parse_iso(end)
    finished = [r for r in gate_records if r.is_finished
                and r.stratum == STRATUM_BRIEF and r.started_at is not None
                and start_dt <= r.started_at < end_dt]
    joined_keys = set()
    for s in _folded(serves):
        # Out-of-schema events (both token fields present) are excluded
        # from the reported stratum: they cannot join a brief (F5).
        if s.brief_id and s.reported_tokens is not None \
                and s.estimated_tokens is None:
            joined_keys.add(s.brief_id)
    joined, unjoined = [], []
    for r in finished:
        (joined if r.join_keys & joined_keys else unjoined).append(r)
    coverage = len(joined) / len(finished) if finished else 0.0
    return {
        "finished_briefs": len(finished),
        "joined_with_reported_tokens": len(joined),
        "coverage": round(coverage, 4),
        "threshold": COVERAGE_THRESHOLD,
        "status": "pass" if coverage >= COVERAGE_THRESHOLD else "invalid",
        "unjoined_named": [r.name for r in unjoined],
    }


# --------------------------------------------------------------------------
# G2 — aggregate win, mix-adjusted (Laspeyres, baseline class shares)
# --------------------------------------------------------------------------

def compute_g2(baseline_table, gate_table):
    """Both sides weighted by BASELINE class shares. Raw figure beside the
    adjusted one; a sign disagreement between them is flagged, never hidden.

    Classes present on only one side are named in both directions. The
    adjusted means are computed over the common classes with baseline
    shares renormalised over that intersection; if the intersection does
    not cover all baseline classes the adjustment is flagged PARTIAL.

    Pass semantics (coordinator disposition of review finding F1): a
    PARTIAL adjustment is NOT pass-eligible — its status is ``partial``,
    never ``pass`` — because renormalising over the intersection can by
    itself manufacture an adjusted win when a cheap baseline class
    vanishes. Label precedence is fail > partial > pass: an adjusted
    loss is ``fail`` even when the adjustment is also partial.
    """
    b_cls, g_cls = baseline_table["classes"], gate_table["classes"]
    shares = class_shares(b_cls)
    common = sorted(set(b_cls) & set(g_cls))
    only_baseline = sorted(set(b_cls) - set(g_cls))
    only_gate = sorted(set(g_cls) - set(b_cls))
    share_sum = sum(shares[c] for c in common)
    adjusted = {}
    if common and share_sum > 0:
        for label, table in (("baseline", b_cls), ("gate", g_cls)):
            adjusted[label] = sum(
                (shares[c] / share_sum) * table[c]["mean"] for c in common)
    raw_b = baseline_table["tokens_per_finished_brief"]
    raw_g = gate_table["tokens_per_finished_brief"]
    result = {
        "classes_common": common,
        "classes_only_in_baseline_named": only_baseline,
        "classes_only_in_gate_named": only_gate,
        "adjustment_partial": bool(only_baseline),
        "baseline_shares": {c: round(shares[c], 4) for c in sorted(shares)},
        "raw": {"baseline_tokens_per_brief": raw_b,
                "gate_tokens_per_brief": raw_g,
                "raw_change": (raw_g - raw_b) if (raw_b is not None and raw_g is not None) else None},
        "adjusted": None,
        "sign_disagreement": False,
        "status": "not_computable",
    }
    if len(adjusted) == 2:
        adj_change = adjusted["gate"] - adjusted["baseline"]
        result["adjusted"] = {
            "baseline_tokens_per_brief": round(adjusted["baseline"], 1),
            "gate_tokens_per_brief": round(adjusted["gate"], 1),
            "adjusted_change": round(adj_change, 1),
        }
        if adj_change < 0:
            # F1: a partial (renormalised) adjustment cannot pass.
            result["status"] = "partial" if result["adjustment_partial"] \
                else "pass"
        else:
            # fail takes precedence over partial (F3a).
            result["status"] = "fail"
        raw_change = result["raw"]["raw_change"]
        if raw_change is not None and raw_change != 0 and adj_change != 0:
            result["sign_disagreement"] = (raw_change < 0) != (adj_change < 0)
    return result


# --------------------------------------------------------------------------
# G3a — per-class harm bound
# --------------------------------------------------------------------------

def compute_g3a(baseline_table, gate_table):
    """For every class with n >= MIN_CLASS_N on BOTH sides, the gate mean
    must not exceed the baseline mean by more than HARM_BOUND."""
    b_cls, g_cls = baseline_table["classes"], gate_table["classes"]
    checked, breaches, skipped_small, one_side = [], [], [], []
    for cls in sorted(set(b_cls) | set(g_cls)):
        if cls not in b_cls or cls not in g_cls:
            side = "baseline_only" if cls in b_cls else "gate_only"
            one_side.append({"class": cls, "side": side})
            continue
        b, g = b_cls[cls], g_cls[cls]
        if b["n"] < MIN_CLASS_N or g["n"] < MIN_CLASS_N:
            skipped_small.append({"class": cls, "baseline_n": b["n"],
                                  "gate_n": g["n"]})
            continue
        limit = b["mean"] * (1 + HARM_BOUND)
        row = {"class": cls, "baseline_mean": round(b["mean"], 1),
               "gate_mean": round(g["mean"], 1), "limit": round(limit, 1),
               "change_ratio": round(g["mean"] / b["mean"], 4)
               if b["mean"] else None}
        checked.append(row)
        if g["mean"] > limit:
            breaches.append(row)
    return {"checked": checked, "breaches": breaches,
            "skipped_below_min_n_named": skipped_small,
            "classes_on_one_side_only_named": one_side,
            "status": "fail" if breaches else "pass"}


# --------------------------------------------------------------------------
# G3b — serve-level win vs old-path equivalent (Phase 2 micro rule)
# --------------------------------------------------------------------------

def compute_g3b(serves):
    """Serves win in aggregate and per serve where old-path >= 500 tokens.
    Micro serves (< 500) are named exceptions, never failures. Serves with
    no computable old-path equivalent are named exclusions; if they exceed
    20% of serves the result is PARTIAL. A serve whose old-path equivalent
    IS present but whose served/context tokens are missing is likewise
    non-computable, named with reason ``served_tokens_missing`` — never
    silently dropped (F2). Status precedence: fail > partial > pass —
    a partial never masks a fail (F3a). Structured corrections are
    folded before any serve math (delta-2, item 4), and an event
    carrying BOTH reported_tokens and estimated_tokens is out of
    schema: it is excluded from the serve stratum entirely — not a
    computable serve, not a non-computable serve, nowhere in the
    serve math — and is named exactly once, in the report's
    invalid-inputs list (delta-2, item 3 / F5 leftover)."""
    serve_events = [s for s in _folded(serves)
                    if s.event_type in (None, "serve", "resume")
                    and not (s.reported_tokens is not None
                             and s.estimated_tokens is not None)]
    computable = [s for s in serve_events
                  if s.old_path_equivalent_tokens is not None
                  and s.served_tokens is not None]
    noncomputable = [s for s in serve_events
                     if s.old_path_equivalent_tokens is None
                     or s.served_tokens is None]
    micro, regular = [], []
    for s in computable:
        (micro if s.old_path_equivalent_tokens < MICRO_CLASS_TOKENS
         else regular).append(s)
    per_serve_failures = [
        {"event_id": s.event_id, "served_tokens": s.served_tokens,
         "old_path_equivalent_tokens": s.old_path_equivalent_tokens}
        for s in regular if not s.served_tokens < s.old_path_equivalent_tokens]
    agg_served = sum(s.served_tokens for s in computable)
    agg_old = sum(s.old_path_equivalent_tokens for s in computable)
    share_nc = (len(noncomputable) / len(serve_events)) if serve_events else 0.0
    result = {
        "serves_total": len(serve_events),
        "computable": len(computable),
        "aggregate": {"served_tokens": agg_served,
                      "old_path_equivalent_tokens": agg_old,
                      "win": agg_served < agg_old if computable else None},
        "per_serve_failures_named": per_serve_failures,
        "micro_class_serves_named": [
            {"event_id": s.event_id, "served_tokens": s.served_tokens,
             "old_path_equivalent_tokens": s.old_path_equivalent_tokens}
            for s in micro],
        "noncomputable_named": [
            {"event_id": s.event_id,
             "reason": (s.not_computable_reason or "not_computable_reason missing")
             if s.old_path_equivalent_tokens is None
             else "served_tokens_missing"}
            for s in noncomputable],
        "noncomputable_share": round(share_nc, 4),
        "status": "pass",
    }
    # Precedence fail > partial > pass (F3a): an aggregate loss or a
    # per-serve failure is a fail even when the non-computable share
    # also exceeds the PARTIAL threshold.
    if per_serve_failures or (computable and not result["aggregate"]["win"]):
        result["status"] = "fail"
    elif share_nc > NONCOMPUTABLE_PARTIAL_SHARE:
        result["status"] = "partial"
    elif not computable:
        result["status"] = "fail"
    return result


# --------------------------------------------------------------------------
# Full gate report (components; ``overall_status`` is only the precedence
# roll-up of the component labels — no verdict is declared by this
# machinery on rehearsal data; verdict assembly is for a real gate week
# under a frozen method)
# --------------------------------------------------------------------------

def overall_status(*component_statuses):
    """Roll component labels into one label with precedence
    invalid > fail > partial > not_computable > pass (delta-2, N2).
    ``invalid`` dominates (dossier §3.3: G1 coverage is checked first;
    below threshold the week is INVALID — neither pass nor fail — and
    must not be masked by a partial/fail roll-up of the other
    components). Below it, a partial never masks a fail (F3a), and a
    pass requires every component to pass."""
    for label in ("invalid", "fail", "partial", "not_computable"):
        if label in component_statuses:
            return label
    return "pass"


def build_gate_report(baseline_records, gate_records, serves,
                      baseline_window, gate_window):
    """Assemble the §3.3 component report from raw inputs.

    baseline_window / gate_window = (start_iso, end_iso)."""
    baseline_table = window_stats(baseline_records, *baseline_window)
    gate_table = window_stats(gate_records, *gate_window)
    # Fold Slice 1's structured corrections once, with rollup.py's
    # semantics, before any gate math (delta-2, item 4) — the fold
    # also enforces rollup's duplicate event_id exclusion (delta-3,
    # D2). The component functions fold again internally, which is a
    # no-op on this list.
    folded_serves, corrections_named = apply_corrections(serves)
    g1 = compute_g1(gate_records, folded_serves, *gate_window)
    g2 = compute_g2(baseline_table, gate_table)
    g3a = compute_g3a(baseline_table, gate_table)
    g3b = compute_g3b(folded_serves)
    first_paragraph_flags = []
    if g2["adjustment_partial"]:
        # N1 (delta-2): the flag's status word is generated from the
        # FINAL computed G2 status — a partial adjustment whose
        # adjusted figure loses is fail, and the flag must say so.
        first_paragraph_flags.append(
            "G2 MIX ADJUSTMENT IS PARTIAL: pre-registered class(es) "
            f"{g2['classes_only_in_baseline_named']} present on the "
            "baseline side only, so shares renormalise over the "
            f"intersection. G2 status is {g2['status']} and CANNOT "
            "pass (F1).")
    if g2["sign_disagreement"]:
        first_paragraph_flags.append(
            "RAW AND MIX-ADJUSTED FIGURES DISAGREE IN SIGN "
            f"(raw change {g2['raw']['raw_change']}, adjusted change "
            f"{g2['adjusted']['adjusted_change']}).")
    if g1["status"] == "invalid":
        first_paragraph_flags.append(
            f"COVERAGE {g1['coverage']} BELOW {COVERAGE_THRESHOLD}: "
            "the week is INVALID, neither pass nor fail.")
    return {
        "script_version": SCRIPT_VERSION,
        "method_status": "DRAFT — NOT FROZEN",
        "first_paragraph_flags": first_paragraph_flags,
        "baseline_window_table": baseline_table,
        "gate_window_table": gate_table,
        "G1_coverage": g1,
        "G2_mix_adjusted": g2,
        "G3a_per_class_harm_bound": g3a,
        "G3b_serve_level": g3b,
        "estimated_stratum_reported_separately":
            estimated_stratum(folded_serves),
        "invalid_inputs_named": invalid_token_events(serves),
        "corrections_named": corrections_named,
        "duplicate_event_ids": duplicate_event_ids(serves),
        "overall_status": overall_status(g1["status"], g2["status"],
                                         g3a["status"], g3b["status"]),
        "components_pass": {
            "G1": g1["status"] == "pass",
            "G2": g2["status"] == "pass",
            "G2_partial": g2["status"] == "partial",
            "G3a": g3a["status"] == "pass",
            "G3b": g3b["status"] == "pass",
            "G3b_partial": g3b["status"] == "partial",
        },
    }


def render_markdown(report):
    lines = ["# Gate report (machinery output — method DRAFT, not frozen)",
             f"Script: {report['script_version']}", ""]
    for flag in report["first_paragraph_flags"]:
        lines.append(f"**{flag}**")
    if report["first_paragraph_flags"]:
        lines.append("")
    for label, key in (("Baseline", "baseline_window_table"),
                       ("Gate", "gate_window_table")):
        t = report[key]
        lines += [f"## {label} window {t['window']['start']} → {t['window']['end']}",
                  f"Finished briefs: {t['finished_briefs']} "
                  f"(with usage {t['finished_with_usage']}); total tokens "
                  f"{t['total_tokens']}; tokens/brief "
                  f"{t['tokens_per_finished_brief']}; briefs/day "
                  f"{t['briefs_per_day']}", ""]
        for cls, st in t["classes"].items():
            lines.append(f"- {cls}: n={st['n']} mean={st['mean_rounded']} "
                         f"median={st['median']} range={st['min']}–{st['max']}")
        lines.append("")
    g1, g2 = report["G1_coverage"], report["G2_mix_adjusted"]
    g3b = report["G3b_serve_level"]
    lines += [f"Overall status: {report['overall_status']}",
              f"G1 coverage: {g1['coverage']} (status {g1['status']}); "
              f"unjoined named: {g1['unjoined_named']}",
              f"G2 status: {g2['status']}; adjusted: {g2['adjusted']} "
              f"raw: {g2['raw']} "
              f"sign_disagreement={g2['sign_disagreement']} "
              f"adjustment_partial={g2['adjustment_partial']}",
              f"G3a breaches: {report['G3a_per_class_harm_bound']['breaches']}",
              f"G3b status: {g3b['status']}; "
              f"micro serves named: {g3b['micro_class_serves_named']}",
              f"G3b per-serve failures named: "
              f"{g3b['per_serve_failures_named']}",
              f"G3b non-computable named: {g3b['noncomputable_named']} "
              f"(share {g3b['noncomputable_share']})",
              f"Invalid inputs named: {report['invalid_inputs_named']}",
              f"Corrections named: "
              f"{report.get('corrections_named', [])}",
              f"Duplicate event_ids named: "
              f"{report.get('duplicate_event_ids', [])}",
              f"Estimated stratum (separate, never summed): "
              f"{report['estimated_stratum_reported_separately']}"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _load_source(spec):
    """A source is a jobs dir (receipts) or a snapshot JSON file."""
    p = Path(spec)
    if p.is_dir():
        return load_receipt_dir(p)
    return load_snapshot(p)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline-source", required=True,
                    help="baseline jobs dir or snapshot JSON")
    ap.add_argument("--gate-source", required=True,
                    help="gate-week jobs dir or snapshot JSON")
    ap.add_argument("--ledger", action="append", default=[],
                    help="usage-ledger JSONL stream (repeatable)")
    ap.add_argument("--baseline-window", nargs=2, required=True,
                    metavar=("START", "END"))
    ap.add_argument("--gate-window", nargs=2, required=True,
                    metavar=("START", "END"))
    ap.add_argument("--out", help="write JSON report here")
    args = ap.parse_args(argv)
    serves = []
    for lp in args.ledger:
        serves.extend(load_ledger_stream(lp))
    report = build_gate_report(_load_source(args.baseline_source),
                               _load_source(args.gate_source), serves,
                               tuple(args.baseline_window),
                               tuple(args.gate_window))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
