#!/usr/bin/env python3
"""Lane instrumentation + shadow mode — Phase 4, Slice 4.

The library OBSERVES real MSI codex-cp lane traffic: for each lane
run it assembles/serves a context pack through pack.py for the run's
(domain, task-type) key and accounts the serve in the usage ledger —
but the pack is NEVER handed to the lane as its context (shadow
mode; dossier §5 Slice 4). The lane's real context path is
untouched. Fallback/miss accounting is live: a key with no pack, or
a serve the read API denies, produces a first-class `fallback`
ledger event carrying the requested key, not a hidden error.

Join key — brief_id, defined exactly (dossier §2.3, §2.4.1; gate
method §2/§4): one *finished brief* is one codex-cp JOB — one
`jobs/<job_key>/receipt.json` with `status == "done"` (the TE prep
brief's Measure-2 unit). The ledger `brief_id` is therefore the
JOB/RECEIPT IDENTITY: the `job_key`, which is also the job
directory name. The receipt's own `brief_id` field is NOT the join
key: it is the Drive source-brief ID, shared by every re-run /
retry of the same source brief (runtime-verified on MSI
2026-11-06: the snapshot carries 266 job records in total, of
which 240 are finished briefs; those 240 finished jobs carry
only 174 distinct receipt `brief_id`s — among all 266 jobs the
receipt field has 187 distinct values — while every `job_key`
is unique; the codex-cp spec mints job-key =
`<briefId>-<sha8 of brief>` by default, or an explicit
`--job-key`). gate.py already accepts the
job_key as a join key (`BriefRecord.join_keys` = {job_key,
brief_id}); keying ledger events by job_key joins each finished
brief exactly once and makes per-brief token reconciliation
well-defined. The receipt `brief_id` is preserved as provenance
(`receipt_brief_id`) in replay reporting, never as the key.

Reported usage — REUSED, never reimplemented: extraction is
gate.py's frozen method (`extract_usage_from_log` /
`load_receipt_dir` / `load_snapshot`): tokens = input + output
summed over the job's stdout.log `turn.completed` events, cached
input a subset of input and counted in full.

Accounting discipline (dossier §2.4; contract rule 4):
- A serve/fallback event is written when the run happens, WITHOUT
  reported tokens (the receipt does not exist yet). It carries the
  counted context size (`context_tokens_served` + the named
  `token_counter` from pack.py's footer) and no `estimated_tokens`:
  the serve row must stay correctable, and the ledger's structured
  correction mechanism (Slice 1, F3) refuses — by design — to leave
  a target carrying both token fields. The counted size is not an
  estimated_tokens figure and is never summed with reported ones.
- Late accounting is an EVENT, never an edit (§2.4.2): when the
  receipt lands, a `correction` event referencing the serve
  event_id carries `corrects.set.reported_tokens` with the
  gate-extracted usage, and `corrects.kind="late_accounting"`
  (Slice 4 fix F2) as its structured discriminator. The raw
  serve row is byte-unchanged; rollup.py and gate.py fold the
  correction identically (kind does not change application).
- Every serve/fallback event either joins a `brief_id` or carries
  a named `unjoined_reason` (§2.3). A finished brief whose receipt
  has no usage events is named unjoined in the replay report with
  its reason — never zero-filled.
- Reported and estimated are never mixed: shadow events for
  metered briefs carry `reported_tokens` (via the accounting
  correction) and never `estimated_tokens`.

MSI scope only (dossier §3.2, TQ2): host `msi`, codex-cp lanes.
This module writes ONLY to the ledger stream path it is handed —
never to the claim register, the Registrar registry, receipts, or
any production store.

Stdlib only; Python 3.11+.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import gate  # noqa: E402
import ledger as L  # noqa: E402
import rollup as R  # noqa: E402

try:
    import pack as P
except Exception:  # noqa: BLE001 — provider is optional
    P = None

PROVIDER = "codex"
REPLAY_DOMAIN = "msi-codex-cp"

REASON_NO_USAGE = (
    "no_usage_events_in_stdout_log: receipt status is done but the "
    "job's stdout.log carries no turn.completed usage events, so no "
    "provider-reported tokens exist to join (named, not zero-filled)")
REASON_NO_IDENTITY = (
    "receipt_missing_job_identity: the record carries no job_key, "
    "so there is no job/receipt identity to join a ledger event to")
REASON_NO_BRIEF = (
    "no_codex_cp_brief_for_run: this shadow run is not tied to a "
    "codex-cp job, so it has no brief_id to join")
NOT_COMPUTABLE_REASON = (
    "shadow_mode_no_old_path_accounting: the shadow observer does "
    "not measure an old-path equivalent for the serve")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------- receipt side

def usage_of(record):
    """gate.UsageTotals for a record, or None when it has no usage.

    Accepts a gate.BriefRecord, a dict from finished_briefs_* below
    (token fields or a `usage` UsageTotals), or a UsageTotals. A
    record with zero turn.completed events has NO usage — None,
    never a zero total (§2.4.3)."""
    if record is None:
        return None
    if isinstance(record, gate.UsageTotals):
        u = record
    elif isinstance(record, gate.BriefRecord):
        if record.reported_tokens is None:
            return None
        u = gate.UsageTotals(
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            cached_input_tokens=record.cached_input_tokens,
            turns=record.turns)
    elif isinstance(record, dict):
        if isinstance(record.get("usage"), gate.UsageTotals):
            u = record["usage"]
        else:
            u = gate.UsageTotals(
                input_tokens=gate._num(record.get("input_tokens")),
                output_tokens=gate._num(record.get("output_tokens")),
                cached_input_tokens=gate._num(
                    record.get("cached_input_tokens")),
                turns=gate._num(record.get("turns")))
    else:
        return None
    return u if u.turns > 0 else None


def reported_dict(usage):
    """The ledger reported_tokens object for extracted usage."""
    return {"provider": PROVIDER, "input": usage.input_tokens,
            "output": usage.output_tokens,
            "cached_input": usage.cached_input_tokens}


def _record_dict(rec):
    """One gate.BriefRecord as a plain dict. `brief_id` is the join
    key (the job/receipt identity = job_key); the receipt's own
    brief_id field is kept as `receipt_brief_id` provenance."""
    return {
        "brief_id": rec.job_key or None,
        "job_key": rec.job_key,
        "receipt_brief_id": rec.brief_id,
        "name": rec.name,
        "status": rec.status,
        "started_at": rec.started_at.isoformat()
        if rec.started_at else None,
        "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
        "input_tokens": rec.input_tokens,
        "output_tokens": rec.output_tokens,
        "cached_input_tokens": rec.cached_input_tokens,
        "turns": rec.turns,
        "reported_tokens": rec.reported_tokens,
        "class_name": rec.class_name,
        "stratum": rec.stratum,
        "exclusion_reason": rec.exclusion_reason,
    }


def records_from_source(source):
    """All codex-cp records from a jobs directory (receipt.json +
    stdout.log per job) or a Slice-5 snapshot JSON — extraction is
    gate.py's either way (load_receipt_dir / load_snapshot)."""
    if os.path.isdir(str(source)):
        records = gate.load_receipt_dir(source)
    else:
        records = gate.load_snapshot(source)
    return [_record_dict(r) for r in records]


def finished_briefs(source):
    """The finished briefs of a source: records with status done
    (one per job/receipt — the prep-brief unit)."""
    return [r for r in records_from_source(source)
            if r["status"] == "done"]


# ------------------------------------------------------- pack provider

class PackAssemblerProvider:
    """Adapt a pack.PackAssembler to the emitter's provider shape:
    callable(domain, task_type, consumer) -> serve-result dict, or
    None when no live pack is keyed (domain, task_type) (a miss).
    A retired pack is a miss (its serve would be denied anyway);
    a serve that comes back denied is returned as-is and the
    emitter turns it into a fallback event."""

    def __init__(self, assembler):
        self.assembler = assembler

    def __call__(self, domain, task_type, consumer):
        packs = self.assembler._fold_manifest()
        candidates = []
        for pack_id, slot in packs.items():
            if slot["retired"] or not slot["versions"]:
                continue
            desc = slot["versions"][slot["latest"]]
            if desc.get("domain") == domain \
                    and desc.get("task_type") == task_type:
                candidates.append(pack_id)
        if not candidates:
            return None
        return self.assembler.serve(sorted(candidates)[0], consumer)


# ------------------------------------------------------------- emitter

class ShadowEmitter:
    """Writes shadow ledger events for lane runs to one stream.

    Constructed with (ledger stream path, host, lane identity).
    `pack_provider` is optional: with none, every run is an honest
    miss (fallback event) — the posture for historical replay,
    where no packs exist for the historical keys. `consumer` is
    the pack-layer consumer the shadow serve is evaluated for;
    it defaults to the least-privilege `house` level.
    """

    def __init__(self, ledger_path, host, lane_id, pack_provider=None,
                 consumer=None):
        self.path = str(ledger_path)
        self.host = host
        self.lane_id = lane_id
        self.provider = pack_provider
        self.consumer = dict(consumer or {
            "identity": lane_id, "max_level": "house"})
        self.writer = L.LedgerWriter(self.path, host)
        self._seq = 0

    # ---------------------------------------------------------- serve

    def _serve_for(self, domain, task_type):
        if self.provider is None:
            return None
        if P is not None:
            try:
                return self.provider(domain, task_type, self.consumer)
            except P.PackNotFoundError:
                return None
        return self.provider(domain, task_type, self.consumer)

    def emit_run(self, domain, task_type, brief_id=None, run_id=None,
                 receipt=None, ts=None, accounting_ts=None):
        """Shadow-observe one lane run: assemble/serve a pack for
        (domain, task_type) WITHOUT handing it to the lane, append
        the honest ledger event, and — when `receipt` (a record as
        produced by finished_briefs_*, a BriefRecord, or a
        UsageTotals) is already available — the late-accounting
        correction for it.

        Returns an ACCOUNTING SUMMARY only (Slice 4 fix F3): the
        stored ledger event and accounting correction, plus flat
        summary fields and a nested `summary` dict carrying the
        event ids, outcome, entitlement result, derived level,
        context tokens served, and brief join state. The full
        serve result (sections / bodies) stays internal to this
        method — a caller cannot obtain lane-consumable bodies
        from the shadow path. `accounting` is None (and
        `unjoined_reason` named) when the receipt carries no
        usage."""
        self._seq += 1
        ts = ts or _now_iso()
        run_id = run_id or f"shadow-{self._seq:04d}"
        serve_result = self._serve_for(domain, task_type)
        base = {"ts": ts, "host": self.host, "lane_id": self.lane_id,
                "run_id": run_id, "consumer": self.lane_id}
        if brief_id:
            base["brief_id"] = brief_id
        else:
            base["brief_id"] = None
            base["unjoined_reason"] = REASON_NO_BRIEF
        if serve_result is not None \
                and serve_result.get("status") != "denied":
            footer = serve_result.get("footer") or {}
            usage = footer.get("usage") or {}
            outcome = "partial" \
                if serve_result.get("status") == "partial" else (
                    "cache_hit" if footer.get("cache") == "hit"
                    else "hit")
            ev = dict(base)
            ev.update({
                "event_type": "serve",
                "pack_id": serve_result.get("pack_id"),
                "pack_version": serve_result.get("version"),
                "requested_key": {"domain": domain,
                                  "task_type": task_type},
                "outcome": outcome,
                "context_tokens_served":
                    usage.get("context_tokens_served", 0),
                "token_counter": usage.get(
                    "token_counter",
                    P.TOKEN_ESTIMATOR if P else "char/4"),
                "old_path_equivalent_tokens": None,
                "not_computable_reason": NOT_COMPUTABLE_REASON,
            })
            if serve_result.get("derived_level") in L.DERIVED_LEVELS:
                ev["derived_level"] = serve_result["derived_level"]
            if serve_result.get("entitlement_result") \
                    in L.ENTITLEMENT_RESULTS:
                ev["entitlement_result"] = \
                    serve_result["entitlement_result"]
            excluded = serve_result.get("exclusions") or []
            if ev.get("entitlement_result") == \
                    "served_with_exclusions" and excluded:
                ev["excluded"] = [
                    {"system": e["system"], "id": e["id"]}
                    for e in excluded]
            if footer.get("sources_hash_set_hash"):
                ev["sources_hash_set_hash"] = \
                    footer["sources_hash_set_hash"]
        else:
            ev = dict(base)
            ev.update({
                "event_type": "fallback",
                "requested_key": {"domain": domain,
                                  "task_type": task_type},
                "outcome": "miss",
                "old_path_equivalent_tokens": None,
                "not_computable_reason": NOT_COMPUTABLE_REASON,
            })
            if serve_result is not None:  # a denied serve
                ev["entitlement_result"] = "denied"
                if serve_result.get("derived_level") \
                        in L.DERIVED_LEVELS:
                    ev["derived_level"] = serve_result["derived_level"]
        stored = self.writer.append(ev)
        accounting, unjoined_reason = None, None
        if receipt is not None:
            accounting = self.join_receipt(
                stored["event_id"], receipt,
                brief_id=brief_id, run_id=run_id,
                ts=accounting_ts or ts)
            if accounting is None:
                unjoined_reason = REASON_NO_USAGE
        # F3: serve_result is deliberately NOT returned — it holds
        # section bodies. Only the accounting summary below leaves
        # this method.
        effective_unjoined = unjoined_reason \
            or stored.get("unjoined_reason")
        summary = {
            "event_id": stored["event_id"],
            "accounting_event_id": accounting["event_id"]
            if accounting else None,
            "event_type": stored.get("event_type"),
            "outcome": stored.get("outcome"),
            "entitlement_result": stored.get("entitlement_result"),
            "derived_level": stored.get("derived_level"),
            "context_tokens_served":
                stored.get("context_tokens_served"),
            "brief_id": brief_id,
            "brief_joined": brief_id is not None,
            "accounting_joined": accounting is not None,
            "unjoined_reason": effective_unjoined,
        }
        return {"event": stored, "accounting": accounting,
                "unjoined_reason": unjoined_reason,
                "summary": summary,
                "event_id": summary["event_id"],
                "accounting_event_id": summary["accounting_event_id"],
                "outcome": summary["outcome"],
                "entitlement_result": summary["entitlement_result"],
                "derived_level": summary["derived_level"],
                "context_tokens_served":
                    summary["context_tokens_served"],
                "brief_id": brief_id,
                "brief_joined": summary["brief_joined"],
                "accounting_joined": summary["accounting_joined"]}

    # ----------------------------------------------------- accounting

    def join_receipt(self, target_event_id, receipt, brief_id=None,
                     run_id=None, ts=None):
        """Late accounting (§2.4.2): append a correction event that
        references the serve/fallback event `target_event_id` and
        carries the receipt's gate-extracted reported_tokens. The
        target row is never edited. Returns the stored correction,
        or None when the receipt has no usage (nothing honest to
        account — the caller names the brief unjoined instead)."""
        usage = usage_of(receipt)
        if usage is None:
            return None
        if brief_id is None and isinstance(receipt, dict):
            brief_id = receipt.get("brief_id")
        if brief_id is None and isinstance(receipt, gate.BriefRecord):
            brief_id = receipt.job_key
        ev = {
            "event_type": "correction",
            "ts": ts or _now_iso(),
            "host": self.host,
            "lane_id": self.lane_id,
            "run_id": run_id or f"accounting-{target_event_id}",
            "consumer": self.lane_id,
            "corrects_event_id": target_event_id,
            "corrects": {
                "target_event_id": target_event_id,
                "kind": "late_accounting",
                "set": {"reported_tokens": reported_dict(usage)}},
            "correction": (
                "late accounting (dossier 2.4.2): codex-cp receipt "
                f"joined by brief_id={brief_id}; reported usage "
                "extracted from the job's stdout.log turn.completed "
                "events via gate.py (input+output, cached input "
                "counted in full); the serve row is unchanged"),
        }
        if brief_id:
            ev["brief_id"] = brief_id
        return self.writer.append(ev)

    def join_pass(self, receipts):
        """Join receipts that landed after their runs were emitted:
        for each finished-brief record with usage whose primary
        (first non-correction) ledger event is not yet accounted,
        append its late-accounting correction. Returns one entry
        per receipt: {brief_id, target_event_id, accounting_event_id
        or None, reason or None}."""
        stream = L.read_stream(self.path)
        events = [e for e in stream["events"] if isinstance(e, dict)]
        accounted = set()
        primary = {}
        for e in events:
            if e.get("event_type") == "correction":
                corr = e.get("corrects") or {}
                tgt = corr.get("target_event_id") \
                    or e.get("corrects_event_id")
                if tgt:
                    accounted.add(tgt)
            elif e.get("brief_id") and e["brief_id"] not in primary:
                primary[e["brief_id"]] = e["event_id"]
        out = []
        for rec in receipts:
            bid = rec.get("brief_id") if isinstance(rec, dict) \
                else getattr(rec, "job_key", None)
            entry = {"brief_id": bid, "target_event_id":
                     primary.get(bid), "accounting_event_id": None,
                     "reason": None}
            if not bid:
                entry["reason"] = REASON_NO_IDENTITY
            elif bid not in primary:
                entry["reason"] = (
                    "no_ledger_event_for_brief: no serve/fallback "
                    "event carries this brief_id in the stream")
            elif primary[bid] in accounted:
                entry["reason"] = "already_accounted"
                entry["accounting_event_id"] = "already_accounted"
            else:
                acc = self.join_receipt(primary[bid], rec,
                                        brief_id=bid)
                if acc is None:
                    entry["reason"] = REASON_NO_USAGE
                else:
                    entry["accounting_event_id"] = acc["event_id"]
            out.append(entry)
        return out


# ---------------------------------------------------------------- replay

PILOT_WINDOW = ("pilot", "2026-10-31T17:35:00Z", "2026-11-05T04:00:00Z")
PRE_WINDOW = ("pre-window", "2026-10-27T18:17:00Z",
              "2026-10-31T17:35:00Z")


def _in_window(rec, start, end):
    ts = rec.get("started_at")
    if not ts:
        return False
    dt = gate.parse_iso(ts)
    return dt is not None and gate.parse_iso(start) <= dt \
        < gate.parse_iso(end)


def _totals(records):
    with_usage = [r for r in records if usage_of(r) is not None]
    return {
        "input": sum(r["input_tokens"] for r in with_usage),
        "output": sum(r["output_tokens"] for r in with_usage),
        "cached_input": sum(r["cached_input_tokens"]
                            for r in with_usage),
        "total": sum(r["input_tokens"] + r["output_tokens"]
                     for r in with_usage),
    }


def replay(source, ledger_path, host="msi", lane_id="shadow-replay",
           windows=None, pack_provider=None):
    """Replay a historical window of receipts through the shadow
    path and reconcile. For each finished brief (brief stratum) in
    the windows: emit the shadow serve/fallback event for its
    derived key (domain REPLAY_DOMAIN, task_type = the gate
    taxonomy class of its job name — historical keys have no packs,
    so fallback events are the honest expected outcome), join its
    receipt as late accounting where usage exists, then fold the
    produced stream through rollup.py and cross-check it through
    gate.py's correction fold. The ledger stream must be FRESH
    (a replay never appends to an existing stream). Returns the
    reconciliation report dict."""
    if os.path.exists(str(ledger_path)) \
            and os.path.getsize(str(ledger_path)) > 0:
        raise ValueError(
            f"replay ledger {ledger_path} already exists and is "
            "non-empty; a replay writes a fresh stream (point it "
            "at a new temp/runtime path)")
    windows = list(windows) if windows else [
        ("all", "1970-01-01T00:00:00Z", "2999-01-01T00:00:00Z")]
    records = records_from_source(source)
    finished = [r for r in records if r["status"] == "done"]
    emitter = ShadowEmitter(ledger_path, host, lane_id,
                            pack_provider=pack_provider)
    unjoined, skipped, emitted = [], [], {}
    for rec in sorted(finished, key=lambda r: r.get("started_at") or ""):
        label = next((w[0] for w in windows
                      if _in_window(rec, w[1], w[2])), None)
        if label is None:
            skipped.append({"brief_id": rec["brief_id"],
                            "name": rec["name"],
                            "reason": "outside_replay_windows"})
            continue
        if rec["stratum"] != gate.STRATUM_BRIEF:
            skipped.append({
                "brief_id": rec["brief_id"], "name": rec["name"],
                "reason": rec["exclusion_reason"]
                or f"stratum {rec['stratum']}: not a brief-stratum "
                     "finished brief (gate method section 4)"})
            continue
        if not rec["brief_id"]:
            unjoined.append({"brief_id": None, "name": rec["name"],
                             "window": label,
                             "reason": REASON_NO_IDENTITY})
            continue
        result = emitter.emit_run(
            REPLAY_DOMAIN, rec["class_name"] or "other_named_lane_brief",
            brief_id=rec["brief_id"], run_id=f"replay-{rec['brief_id']}",
            receipt=rec, ts=rec["started_at"],
            accounting_ts=rec["ended_at"] or rec["started_at"])
        emitted[rec["brief_id"]] = result["event"]["event_id"]
        if result["accounting"] is None:
            unjoined.append({
                "brief_id": rec["brief_id"],
                "receipt_brief_id": rec["receipt_brief_id"],
                "name": rec["name"], "window": label,
                "reason": result["unjoined_reason"] or REASON_NO_USAGE})

    summary = R.rollup([str(ledger_path)])
    per_brief_rollup = {}
    for bid, slot in summary["per_brief"].items():
        rep = slot["reported"]
        if rep["events"] == 0:
            continue  # observed but unaccounted != joined
        per_brief_rollup[bid] = {
            "input": rep["input"], "output": rep["output"],
            "cached_input": rep["cached_input"],
            "total": rep["input"] + rep["output"]}
    # Independent cross-check: fold the same stream through
    # gate.py's correction machinery (never the emitter's own view).
    serves = gate.load_ledger_stream(str(ledger_path))
    folded, _named = gate.apply_corrections(serves)
    per_brief_gate = {}
    for s in folded:
        if s.brief_id and s.reported_tokens is not None:
            per_brief_gate[s.brief_id] = \
                per_brief_gate.get(s.brief_id, 0) + s.reported_tokens

    def window_report(label, start, end):
        in_win = [r for r in finished
                  if r["stratum"] == gate.STRATUM_BRIEF
                  and _in_window(r, start, end)]
        joined = [r for r in in_win
                  if r["brief_id"] in per_brief_rollup]
        deltas = []
        for r in joined:
            receipt_total = r["input_tokens"] + r["output_tokens"]
            ledger_total = per_brief_rollup[r["brief_id"]]["total"]
            gate_total = per_brief_gate.get(r["brief_id"])
            if ledger_total != receipt_total or gate_total != receipt_total:
                deltas.append({
                    "brief_id": r["brief_id"], "name": r["name"],
                    "receipt_total": receipt_total,
                    "ledger_total": ledger_total,
                    "gate_fold_total": gate_total,
                    "delta": ledger_total - receipt_total})
        n = len(in_win)
        return {
            "window": {"label": label, "start": start, "end": end},
            "finished_briefs": n,
            "joined": len(joined),
            "coverage": round(len(joined) / n, 4) if n else 0.0,
            "coverage_vs_g1_90pct": (
                "meets" if n and len(joined) / n >= 0.90 else "below"),
            "receipt_totals": _totals(in_win),
            "ledger_joined_reported_totals": {
                "input": sum(per_brief_rollup[r["brief_id"]]["input"]
                             for r in joined),
                "output": sum(per_brief_rollup[r["brief_id"]]["output"]
                              for r in joined),
                "cached_input": sum(
                    per_brief_rollup[r["brief_id"]]["cached_input"]
                    for r in joined),
                "total": sum(per_brief_rollup[r["brief_id"]]["total"]
                             for r in joined)},
            "deltas_named": deltas,
            "unjoined_named": [u for u in unjoined
                               if u.get("window") == label],
        }

    win_reports = [window_report(*w) for w in windows]
    all_joined = [bid for bid in per_brief_rollup]
    return {
        "source": str(source),
        "ledger_path": str(ledger_path),
        "host": host, "lane_id": lane_id,
        "join_key": "brief_id = job_key (job/receipt identity)",
        "extraction": "gate.py (turn.completed input+output, "
                      "cached input counted in full)",
        "windows": win_reports,
        "overall": {
            "finished_briefs_in_windows": sum(
                w["finished_briefs"] for w in win_reports),
            "joined": sum(w["joined"] for w in win_reports),
            "deltas_named": [d for w in win_reports
                              for d in w["deltas_named"]],
            "reconciliation_exact": all(
                not w["deltas_named"] for w in win_reports),
        },
        "unjoined_named": unjoined,
        "skipped_named": skipped,
        "rollup": {
            "events": summary["gate_valid_totals"]["events"],
            "reported": summary["gate_valid_totals"]["reported"],
            "estimated_events":
                summary["gate_valid_totals"]["estimated"]["events"],
            "streams": summary["streams"],
            "excluded_streams": summary["excluded_streams"],
            "duplicate_event_ids": summary["duplicate_event_ids"],
        },
        "gate_fold_cross_check": {
            "briefs_with_reported": len(per_brief_gate),
            "total": sum(per_brief_gate.values()),
            "matches_rollup": per_brief_gate == {
                bid: v["total"] for bid, v in per_brief_rollup.items()},
        },
        "emitted_events": len(emitted),
    }


def render_markdown(report):
    lines = ["# Slice 4 replay reconciliation (shadow.py)",
             f"Source: {report['source']}",
             f"Ledger stream: {report['ledger_path']}",
             f"Join key: {report['join_key']}",
             f"Extraction: {report['extraction']}", ""]
    for w in report["windows"]:
        lines += [
            f"## Window {w['window']['label']} "
            f"{w['window']['start']} → {w['window']['end']}",
            f"Finished briefs: {w['finished_briefs']}; joined: "
            f"{w['joined']}; coverage: {w['coverage']} "
            f"(vs G1 90%: {w['coverage_vs_g1_90pct']})",
            f"Receipt totals: {w['receipt_totals']}",
            f"Ledger joined reported totals: "
            f"{w['ledger_joined_reported_totals']}",
            f"Deltas named: {w['deltas_named']}",
            f"Unjoined named: {w['unjoined_named']}", ""]
    lines += [
        f"Overall reconciliation exact: "
        f"{report['overall']['reconciliation_exact']}",
        f"Gate-fold cross-check: {report['gate_fold_cross_check']}",
        f"Rollup totals: {report['rollup']['reported']} "
        f"over {report['rollup']['events']} events",
        f"Skipped named: {report['skipped_named']}"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Shadow-mode replay of codex-cp receipts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay")
    rp.add_argument("--source", required=True,
                    help="codex-cp jobs dir or snapshot JSON")
    rp.add_argument("--ledger", required=True,
                    help="fresh usage-ledger JSONL path to write")
    rp.add_argument("--host", default="msi")
    rp.add_argument("--lane", default="shadow-replay")
    rp.add_argument("--window", action="append", nargs=3,
                    metavar=("LABEL", "START", "END"),
                    help="repeatable; default: pilot + pre-window")
    rp.add_argument("--report", help="write JSON report here")
    rp.add_argument("--report-md", help="write Markdown report here")
    args = ap.parse_args(argv)
    windows = [tuple(w) for w in args.window] if args.window \
        else [PRE_WINDOW, PILOT_WINDOW]
    report = replay(args.source, args.ledger, host=args.host,
                    lane_id=args.lane, windows=windows)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    md = render_markdown(report)
    if args.report_md:
        with open(args.report_md, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
