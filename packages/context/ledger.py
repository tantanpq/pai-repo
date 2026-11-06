#!/usr/bin/env python3
"""Usage-ledger core — Phase 4, Slice 1.

One append-only JSONL event stream per host recording pack serves,
cache outcomes, ad-hoc fallbacks, assemblies, and corrections, with
token accounting in the contract's two never-summed fields
(`contracts/context-package.md` rule 4; PHASE4_DESIGN_DOSSIER_V1 §2).

Design invariants (dossier §2.1–§2.4):

- This module is NOT the claim register and NOT the cabinet Registrar.
  It writes only to the stream path it is handed; it never touches any
  production store.
- The writer is append-only at the API level: it exposes append
  operations and read helpers only — no update, delete, truncate, or
  rewrite path exists.
- Every stored line carries a `prev_hash` running content hash
  (Registrar-style chain): line N's `prev_hash` is the sha256 of line
  N-1's bytes (line 1 chains to the genesis hash, sha256 of empty), so
  a rollup can prove the stream it folded is the stream that was
  written, and name the rows around a break.
- Corrections are new events: a `correction` event references the
  original `event_id` and states the fix. A wrong row is never edited.
  A correction may also carry a structured `corrects` payload
  ({target_event_id, set: {...}}) whose `set` replaces only the
  accounting fields `reported_tokens` / `estimated_tokens` /
  `context_tokens_served` on the target; the rollup applies it.
  The payload may carry an optional `kind` (Slice 4 fix F2,
  additive): "error_fix" or "late_accounting"; absent means
  "error_fix", so every pre-existing stream is unaffected. Kind
  is a discriminator for tooling only; it does not change how
  the correction is applied.
- Head commitment (F1): the hash chain alone cannot authenticate a
  stream's TAIL — the last line has no successor whose `prev_hash`
  pins it. So the writer maintains a sidecar `<stream>.head.json`
  next to each stream, rewritten atomically (temp file + os.replace)
  after every successful append, carrying {head_hash, line_count,
  last_event_id, host}. The rollup checks a folded stream against its
  sidecar when one exists and excludes the stream on mismatch; a
  stream with no sidecar still folds but is named as tail-uncommitted.
  RESIDUAL LIMIT, stated honestly: a tamperer who rewrites the stream
  tail AND the sidecar consistently defeats this check. That case is
  out of scope until the gate report anchors head commitments
  externally (e.g. publishes them in a separate, witnessed store).
- Writer-side commitment gate (R1): detection alone is not enough —
  a writer that opens a stream whose sidecar does NOT match its tail
  and simply appends would rewrite the sidecar to match the tampered
  tail, laundering the mismatch into gate-valid truth (and, after a
  truncation, silently re-minting a committed event's ID for a
  different event). So opening a LedgerWriter over an EXISTING stream
  verifies the sidecar after the chain check: an exact match
  proceeds; the one healable case — the sidecar is an exact PREFIX
  state of the verified stream (crash between stream fsync and
  sidecar replace) — advances the sidecar to the current head and
  proceeds with `writer.healed` set; EVERYTHING else (sidecar ahead
  of the stream, a head mismatch that is not an exact prefix state,
  a corrupt/unparseable sidecar) refuses with LedgerError naming
  expected vs actual, writing nothing. A non-empty stream with NO
  sidecar refuses too, unless the caller passes
  adopt_uncommitted=True, in which case the sidecar is written with
  `adopted: true` + `adopted_at_line_count` and the rollup names the
  stream's pre-adoption history as uncommitted (adopted history)
  while folding it.
- Durable heal markers (fix round 3): a crash-window heal is
  legitimate recovery, but it must never be silent — a healed stream
  is otherwise indistinguishable from one whose tail was forged with
  chain-valid lines while its sidecar was stale. So every heal
  appends an entry {healed_at_line_count (the sidecar's prior
  count), stream_lines_at_heal, healed_head_hash} to a `heals` list
  in the sidecar; the list is preserved and carried forward on every
  later sidecar rewrite (like the adoption marker), multiple heals
  accumulate, and the rollup names every stream whose sidecar
  carries heals in its `healed_streams` list while still folding it.
- Corrections never target corrections (R2): the validator rejects a
  correction candidate whose target is its own event_id
  (self-reference), and the rollup names — never applies — any
  correction whose target event is itself a correction event
  (`target_is_correction`), so a correction cannot mint token figures
  by rewriting another correction's (or its own) accounting fields.
- `reported_tokens` (provider-reported) and `estimated_tokens` (local
  estimate, estimator named) are never added together — not in an
  event (an event is metered OR estimated, never both, and any
  summed/combined token field is rejected), not anywhere downstream.
  A token number without a named source is not accounting.

Stdlib only; runs on Python 3.11+ (Windows and Linux).
"""
import hashlib
import json
import os
import re
from datetime import datetime

GENESIS_HASH = hashlib.sha256(b"").hexdigest()
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

EVENT_TYPES = ("assemble", "serve", "resume", "fallback", "correction")
HOSTS = ("msi", "home", "vm")
OUTCOMES = ("hit", "cache_hit", "partial", "miss", "stale_rejected")
DERIVED_LEVELS = ("house", "private", "secret-pointer", "unknown")
ENTITLEMENT_RESULTS = ("served_full", "served_with_exclusions", "denied")

# Canonical field order for serialization (mirrors the Registrar's
# FIELD_ORDER discipline: one byte form per event, so hashes and
# byte-identical rebuilds are meaningful).
FIELD_ORDER = [
    "event_id", "ts", "event_type", "host", "lane_id", "run_id",
    "brief_id", "unjoined_reason", "consumer", "pack_id",
    "pack_version", "requested_key", "outcome", "derived_level",
    "entitlement_result", "excluded", "context_tokens_served",
    "token_counter", "reported_tokens", "estimated_tokens",
    "old_path_equivalent_tokens", "not_computable_reason",
    "sources_hash_set_hash", "corrects_event_id", "correction",
    "corrects", "prev_hash",
]
ALLOWED_FIELDS = frozenset(FIELD_ORDER)

REPORTED_KEYS = frozenset(("provider", "input", "output", "cached_input"))
ESTIMATED_KEYS = frozenset(("value", "estimator"))
# Closed consumer sub-schema (F4): identity plus the entitlement-context
# keys the house consumer model actually uses. Precise shape (R4):
# pack.py's INTERNAL normalised consumer is {identity, max_level},
# with `level` read there as an input alias for max_level; what
# pack.py actually EMITS to the ledger is only the identity string.
# The ledger accepts the {identity, max_level, level} superset so no
# consumer shape pack.py can produce is ever rejected.
CONSUMER_KEYS = frozenset(("identity", "max_level", "level"))
CORRECTS_KEYS = frozenset(("target_event_id", "set", "kind"))
# Slice 4 fix F2 (additive): optional structured discriminator on a
# structured correction. Absent kind means "error_fix" (the default
# for every pre-existing stream); "late_accounting" marks a
# late-accounting join (e.g. shadow.py's receipt join). Kind does
# not change how a correction is applied.
CORRECTION_KINDS = frozenset(("error_fix", "late_accounting"))
DEFAULT_CORRECTION_KIND = "error_fix"
CORRECTION_SET_FIELDS = ("reported_tokens", "estimated_tokens",
                         "context_tokens_served")


class LedgerError(Exception):
    """Base error for ledger failures (I/O, broken existing chain)."""


class ValidationError(LedgerError):
    """An event failed schema validation; `.reasons` names every defect."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


# ---------------------------------------------------------------- helpers

def _is_count(v):
    """A non-negative integer token count (bools are not counts)."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def _tz_qualified_iso(s):
    if not isinstance(s, str):
        return False
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return False
    return dt.tzinfo is not None


def line_hash(line_bytes):
    return hashlib.sha256(line_bytes).hexdigest()


def _reported_reasons(reported, field):
    """Per-field validation for a reported_tokens object. `field` is
    the dotted name used in reasons ('reported_tokens' at top level,
    'corrects.set.reported_tokens' inside a structured correction) —
    the same validators apply in both places (F3)."""
    reasons = []
    if not isinstance(reported, dict):
        reasons.append(f"{field} must be an object "
                       "{provider, input, output, cached_input}")
        return reasons
    extra = set(reported) - REPORTED_KEYS
    if extra:
        reasons.append(f"{field} has unknown keys: {sorted(extra)}")
    if not _nonempty_str(reported.get("provider")):
        reasons.append(f"{field}.provider must name the provider")
    for k in ("input", "output"):
        if not _is_count(reported.get(k)):
            reasons.append(f"{field}.{k} must be a "
                           "non-negative integer")
    if "cached_input" in reported and not _is_count(
            reported["cached_input"]):
        reasons.append(f"{field}.cached_input must be a "
                       "non-negative integer")
    return reasons


def _estimated_reasons(estimated, field):
    """Per-field validation for an estimated_tokens object (same
    validators at top level and inside corrects.set)."""
    reasons = []
    if not isinstance(estimated, dict):
        reasons.append(f"{field} must be an object "
                       "{value, estimator}")
        return reasons
    extra = set(estimated) - ESTIMATED_KEYS
    if extra:
        reasons.append(f"{field} has unknown keys: {sorted(extra)}")
    if not _is_count(estimated.get("value")):
        reasons.append(f"{field}.value must be a "
                       "non-negative integer")
    if not _nonempty_str(estimated.get("estimator")):
        reasons.append(f"{field}.estimator must name "
                       "the estimator (e.g. 'char/4'): an "
                       "estimate without a named estimator is "
                       "not accounting (rule 4)")
    return reasons


# ------------------------------------------------------- head sidecar

def head_sidecar_path(path):
    """Path of the head-commitment sidecar for a stream (F1)."""
    return str(path) + ".head.json"


def read_head_commitment(path):
    """Read a stream's head-commitment sidecar.

    Returns the parsed dict, None when no sidecar exists, or {} when
    a sidecar exists but cannot be parsed (which the rollup treats
    as a commitment mismatch, never as 'no commitment')."""
    sidecar = head_sidecar_path(path)
    if not os.path.exists(sidecar):
        return None
    try:
        with open(sidecar, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------- validation

def validate_event(ev, stored=False):
    """Validate one event against the §2.3 schema.

    Returns a list of named violation reasons; an empty list means the
    event is valid. With stored=True the event is a line read back from
    a stream and must carry a well-formed `prev_hash`; with
    stored=False it is a writer candidate and must NOT carry one (the
    writer sets it).
    """
    reasons = []
    if not isinstance(ev, dict):
        return ["event is not a JSON object"]

    # Closed schema. Token-flavoured unknown fields get the rule-4
    # reason: combined/summed token figures are exactly what the
    # contract forbids, so name that instead of a bare "unknown field".
    for key in ev:
        if key not in ALLOWED_FIELDS:
            if "token" in key.lower():
                reasons.append(
                    f"field {key!r} is not in the schema: token figures "
                    "live only in reported_tokens / estimated_tokens, "
                    "which are never summed (context-package rule 4)")
            else:
                reasons.append(f"unknown field {key!r}")

    if stored:
        ph = ev.get("prev_hash")
        if not isinstance(ph, str) or not SHA256_RE.match(ph):
            reasons.append("prev_hash must be present and lowercase "
                           "sha256 hex on a stored event")
    elif "prev_hash" in ev:
        reasons.append("prev_hash is writer-managed; candidates must "
                       "not carry it")

    host = ev.get("host")
    if host not in HOSTS:
        reasons.append(f"host must be one of {list(HOSTS)}, got {host!r}")

    eid = ev.get("event_id")
    if not _nonempty_str(eid):
        reasons.append("event_id must be a non-empty string")
    elif isinstance(host, str):
        m = re.match(r"^([a-z]+)-(\d{4,})$", eid)
        if not m:
            reasons.append(
                f"event_id {eid!r} must be host prefix + sequence "
                "(e.g. 'msi-000001')")
        elif m.group(1) != host:
            reasons.append(
                f"event_id prefix {m.group(1)!r} does not match "
                f"host {host!r}")
        elif int(m.group(2)) == 0:
            reasons.append(
                f"event_id {eid!r} has sequence 0000: sequences "
                "start at 000001; sequence 0000 is not a valid "
                "event_id (F5)")

    if not _tz_qualified_iso(ev.get("ts")):
        reasons.append("ts must be a timezone-qualified ISO timestamp")

    etype = ev.get("event_type")
    if etype not in EVENT_TYPES:
        reasons.append(
            f"event_type must be one of {list(EVENT_TYPES)}, "
            f"got {etype!r}")

    for field in ("lane_id", "run_id"):
        if not _nonempty_str(ev.get(field)):
            reasons.append(f"{field} must be a non-empty string")

    # brief_id join key: null is allowed ONLY with a named reason
    # (dossier §2.3 / §3.4 — unjoined rows are reported, never hidden).
    if etype != "correction" and "brief_id" not in ev:
        reasons.append("brief_id is required (null only with "
                       "unjoined_reason named)")
    if "brief_id" in ev:
        bid = ev["brief_id"]
        if bid is None:
            if not _nonempty_str(ev.get("unjoined_reason")):
                reasons.append(
                    "brief_id is null but unjoined_reason is not "
                    "named: unjoined rows must carry a named reason")
        elif not _nonempty_str(bid):
            reasons.append("brief_id must be a non-empty string or null")
        elif ev.get("unjoined_reason") is not None:
            reasons.append("unjoined_reason present but brief_id is "
                           "set; the two are mutually exclusive")

    consumer = ev.get("consumer")
    if consumer is not None:
        ok = _nonempty_str(consumer) or (
            isinstance(consumer, dict)
            and _nonempty_str(consumer.get("identity")))
        if not ok:
            reasons.append("consumer must be a non-empty identity "
                           "string or an object with an 'identity'")
        if isinstance(consumer, dict):
            # Closed sub-schema (F4): unknown keys are rejected by
            # name, so no combined token figure can hide here.
            extra = set(consumer) - CONSUMER_KEYS
            if extra:
                reasons.append(f"consumer has unknown keys: "
                               f"{sorted(extra)} (allowed: "
                               f"{sorted(CONSUMER_KEYS)})")
            for lvl_key in ("max_level", "level"):
                if lvl_key in consumer and not _nonempty_str(
                        consumer[lvl_key]):
                    reasons.append(f"consumer.{lvl_key} must be a "
                                   "non-empty string")

    if etype in ("serve", "resume", "assemble"):
        if not _nonempty_str(ev.get("pack_id")):
            reasons.append(f"pack_id is required on {etype} events")
        pv = ev.get("pack_version")
        if not (isinstance(pv, int) and not isinstance(pv, bool)
                and pv >= 1):
            reasons.append(f"pack_version must be a positive integer "
                           f"on {etype} events")

    rk = ev.get("requested_key")
    if etype == "fallback" and rk is None:
        reasons.append("requested_key is required on fallback events")
    if rk is not None:
        if not isinstance(rk, dict):
            reasons.append("requested_key must be an object "
                           "{domain, task_type}")
        else:
            extra = set(rk) - {"domain", "task_type"}
            if extra:
                reasons.append(f"requested_key has unknown keys: "
                               f"{sorted(extra)}")
            if not _nonempty_str(rk.get("domain")):
                reasons.append("requested_key.domain must be a "
                               "non-empty string")
            if not _nonempty_str(rk.get("task_type")):
                reasons.append("requested_key.task_type must be a "
                               "non-empty string")

    outcome = ev.get("outcome")
    if etype in ("serve", "resume", "fallback") and outcome is None:
        reasons.append(f"outcome is required on {etype} events")
    if outcome is not None and outcome not in OUTCOMES:
        reasons.append(f"outcome must be one of {list(OUTCOMES)}, "
                       f"got {outcome!r}")

    dl = ev.get("derived_level")
    if dl is not None and dl not in DERIVED_LEVELS:
        reasons.append(f"derived_level must be one of "
                       f"{list(DERIVED_LEVELS)}, got {dl!r}")

    er = ev.get("entitlement_result")
    if er is not None and er not in ENTITLEMENT_RESULTS:
        reasons.append(f"entitlement_result must be one of "
                       f"{list(ENTITLEMENT_RESULTS)}, got {er!r}")
    excluded = ev.get("excluded")
    if er == "served_with_exclusions":
        if not (isinstance(excluded, list) and excluded):
            reasons.append("entitlement_result is "
                           "served_with_exclusions but no excluded "
                           "(system, ID) list is named")
    if excluded is not None:
        if not isinstance(excluded, list):
            reasons.append("excluded must be a list of {system, id}")
        else:
            for item in excluded:
                if not (isinstance(item, dict)
                        and _nonempty_str(item.get("system"))
                        and _nonempty_str(item.get("id"))):
                    reasons.append("each excluded entry must be "
                                   "{system, id} with non-empty values")
                    break

    # --- token accounting: counted, metered, or estimated — labelled.
    cts = ev.get("context_tokens_served")
    if cts is not None:
        if not _is_count(cts):
            reasons.append("context_tokens_served must be a "
                           "non-negative integer")
        if not _nonempty_str(ev.get("token_counter")):
            reasons.append("context_tokens_served carries no named "
                           "token_counter: a number without a named "
                           "source is not accounting (rule 4)")
    elif ev.get("token_counter") is not None:
        reasons.append("token_counter present but "
                       "context_tokens_served is absent")

    reported = ev.get("reported_tokens")
    estimated = ev.get("estimated_tokens")
    if reported is not None and estimated is not None:
        reasons.append(
            "event carries both reported_tokens and estimated_tokens: "
            "an event is metered or estimated, never both "
            "(estimated_tokens is only for where no meter exists)")
    if reported is not None:
        reasons.extend(_reported_reasons(reported, "reported_tokens"))
    if estimated is not None:
        reasons.extend(_estimated_reasons(estimated,
                                          "estimated_tokens"))

    ope = ev.get("old_path_equivalent_tokens")
    if ope is not None and not _is_count(ope):
        reasons.append("old_path_equivalent_tokens must be a "
                       "non-negative integer or null")
    if "old_path_equivalent_tokens" in ev and ope is None:
        if not _nonempty_str(ev.get("not_computable_reason")):
            reasons.append("old_path_equivalent_tokens is null but "
                           "not_computable_reason is not named")

    shs = ev.get("sources_hash_set_hash")
    if shs is not None and not (isinstance(shs, str)
                                and SHA256_RE.match(shs)):
        reasons.append("sources_hash_set_hash must be lowercase "
                       "sha256 hex")

    if etype == "correction":
        corrects = ev.get("corrects")
        structured_target = (
            corrects.get("target_event_id")
            if isinstance(corrects, dict) else None)
        # Self-reference (R2a): a correction candidate whose target is
        # its OWN event_id is rejected by name. Candidate-side only
        # (stored=False): a handcrafted stored stream that bypassed
        # the writer is the rollup's job — it names the correction
        # not-applied with reason target_is_correction (R2b) instead
        # of dropping it as a schema-invalid row.
        if not stored and _nonempty_str(ev.get("event_id")):
            own = ev["event_id"]
            if ev.get("corrects_event_id") == own \
                    or structured_target == own:
                reasons.append(
                    f"correction targets itself: its target "
                    f"{own!r} is its own event_id — a correction "
                    "must not target itself (corrections never "
                    "target corrections; see rollup "
                    "target_is_correction)")
        if not _nonempty_str(ev.get("corrects_event_id")) \
                and not _nonempty_str(structured_target):
            reasons.append("correction events must reference the "
                           "original event via corrects_event_id")
        if not _nonempty_str(ev.get("correction")) \
                and corrects is None:
            reasons.append("correction events must state the fix in "
                           "the correction field")
        if corrects is not None:
            reasons.extend(_corrects_reasons(ev, corrects))

    return reasons


def _corrects_reasons(ev, corrects):
    """Validate the structured correction payload (F3):
    corrects = {target_event_id, set: {...}} where `set` may replace
    ONLY reported_tokens / estimated_tokens / context_tokens_served,
    and its values pass the same per-field validators as normal
    events. Whether applying it would leave the TARGET carrying both
    token fields depends on the target, so that check is the
    rollup's (it names the correction and never applies it).
    Slice 4 fix F2 (additive): `corrects` may also carry an optional
    `kind` in CORRECTION_KINDS; absent kind means error_fix."""
    reasons = []
    if not isinstance(corrects, dict):
        return ["corrects must be an object "
                "{target_event_id, set}"]
    extra = set(corrects) - CORRECTS_KEYS
    if extra:
        reasons.append(f"corrects has unknown keys: {sorted(extra)}")
    if "kind" in corrects and corrects.get("kind") not in \
            CORRECTION_KINDS:
        reasons.append(
            f"corrects.kind must be one of "
            f"{sorted(CORRECTION_KINDS)}, got "
            f"{corrects.get('kind')!r}")
    target = corrects.get("target_event_id")
    if not _nonempty_str(target):
        reasons.append("corrects.target_event_id must be a "
                       "non-empty string")
    elif _nonempty_str(ev.get("corrects_event_id")) \
            and ev["corrects_event_id"] != target:
        reasons.append("corrects.target_event_id does not match "
                       "corrects_event_id")
    cset = corrects.get("set")
    if cset is not None:
        if not isinstance(cset, dict) or not cset:
            reasons.append("corrects.set must be a non-empty object "
                           "of accounting-field replacements")
        else:
            extra = set(cset) - set(CORRECTION_SET_FIELDS)
            if extra:
                reasons.append(
                    f"corrects.set has keys outside the accounting "
                    f"fields it may replace: {sorted(extra)} "
                    f"(allowed: {list(CORRECTION_SET_FIELDS)})")
            if "reported_tokens" in cset and \
                    "estimated_tokens" in cset:
                reasons.append(
                    "corrects.set carries both reported_tokens and "
                    "estimated_tokens: applying it would leave the "
                    "target metered and estimated, never both")
            if "reported_tokens" in cset:
                reasons.extend(_reported_reasons(
                    cset["reported_tokens"],
                    "corrects.set.reported_tokens"))
            if "estimated_tokens" in cset:
                reasons.extend(_estimated_reasons(
                    cset["estimated_tokens"],
                    "corrects.set.estimated_tokens"))
            if "context_tokens_served" in cset and not _is_count(
                    cset["context_tokens_served"]):
                reasons.append("corrects.set.context_tokens_served "
                               "must be a non-negative integer")
    return reasons


# ---------------------------------------------------------- serialization

def serialize_event(ev):
    """Canonical one-line byte form (no trailing LF). Field order is
    FIELD_ORDER; nested objects get their own fixed key order so the
    same event always serializes to the same bytes."""
    ordered = {k: ev[k] for k in FIELD_ORDER if k in ev}
    rk = ordered.get("requested_key")
    if isinstance(rk, dict):
        ordered["requested_key"] = {
            k: rk[k] for k in ("domain", "task_type") if k in rk}
    rt = ordered.get("reported_tokens")
    if isinstance(rt, dict):
        ordered["reported_tokens"] = {
            k: rt[k] for k in ("provider", "input", "output",
                               "cached_input") if k in rt}
    et = ordered.get("estimated_tokens")
    if isinstance(et, dict):
        ordered["estimated_tokens"] = {
            k: et[k] for k in ("value", "estimator") if k in et}
    ex = ordered.get("excluded")
    if isinstance(ex, list):
        ordered["excluded"] = [
            {k: item[k] for k in ("system", "id") if k in item}
            if isinstance(item, dict) else item for item in ex]
    cons = ordered.get("consumer")
    if isinstance(cons, dict):
        ordered["consumer"] = {
            k: cons[k] for k in ("identity", "max_level", "level")
            if k in cons}
    corr = ordered.get("corrects")
    if isinstance(corr, dict):
        fixed = {k: corr[k] for k in ("target_event_id", "kind", "set")
                 if k in corr}
        cset = fixed.get("set")
        if isinstance(cset, dict):
            fixed_set = {}
            for k in CORRECTION_SET_FIELDS:
                if k not in cset:
                    continue
                v = cset[k]
                if k == "reported_tokens" and isinstance(v, dict):
                    v = {kk: v[kk] for kk in
                         ("provider", "input", "output",
                          "cached_input") if kk in v}
                elif k == "estimated_tokens" and isinstance(v, dict):
                    v = {kk: v[kk] for kk in ("value", "estimator")
                         if kk in v}
                fixed_set[k] = v
            fixed["set"] = fixed_set
        ordered["corrects"] = fixed
    return json.dumps(ordered, ensure_ascii=False)


# -------------------------------------------------------------- reading

def _pairs_no_dupes(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise LedgerError(f"duplicate JSON key: {k}")
        obj[k] = v
    return obj


def read_stream(path):
    """Tolerant read of one stream file, for rollup/inspection.

    Returns {"lines": [line_bytes_without_LF, ...],
             "events": [dict or None per line],
             "parse_errors": {line_number_1based: reason}}.
    A missing file reads as an empty stream."""
    if not os.path.exists(path):
        return {"lines": [], "events": [], "parse_errors": {}}
    with open(path, "rb") as f:
        data = f.read()
    if data == b"":
        return {"lines": [], "events": [], "parse_errors": {}}
    raw_lines = data.split(b"\n")
    if raw_lines and raw_lines[-1] == b"":
        raw_lines.pop()  # final LF terminator, not a line
    lines, events, errors = [], [], {}
    for i, raw in enumerate(raw_lines):
        lineno = i + 1
        lines.append(raw)
        if raw.endswith(b"\r"):
            events.append(None)
            errors[lineno] = "CR byte in line (CRLF is not the stream form)"
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            events.append(None)
            errors[lineno] = "line is not valid UTF-8"
            continue
        try:
            ev = json.loads(text, object_pairs_hook=_pairs_no_dupes)
        except (json.JSONDecodeError, LedgerError) as exc:
            events.append(None)
            errors[lineno] = f"invalid JSON: {exc}"
            continue
        if not isinstance(ev, dict):
            events.append(None)
            errors[lineno] = "line is not a JSON object"
            continue
        events.append(ev)
    return {"lines": lines, "events": events, "parse_errors": errors}


def verify_chain(lines, events):
    """Check the running hash chain. Returns a list of breaks, each
    {"line": N (1-based), "expected": hash, "found": hash or None} —
    line N is the first line whose prev_hash does not match the hash
    of line N-1 (or genesis for line 1)."""
    breaks = []
    for i, ev in enumerate(events):
        expected = GENESIS_HASH if i == 0 else line_hash(lines[i - 1])
        found = ev.get("prev_hash") if isinstance(ev, dict) else None
        if found != expected:
            breaks.append({"line": i + 1, "expected": expected,
                           "found": found})
    return breaks


# ---------------------------------------------------------------- writer

class LedgerWriter:
    """Append-only writer for one host's stream.

    The public surface is deliberately append + inspect only:
    append(), append_many(), head_hash, line_count, path, host. There
    is no update, delete, truncate, or rewrite operation, and opening
    a writer over a stream whose chain is broken raises instead of
    extending corrupt history. Every successful append also rewrites
    the head-commitment sidecar (`<stream>.head.json`, F1) atomically
    after the stream write — the sidecar is derived state, not a
    stream mutation path.

    Opening over an EXISTING stream additionally gates on the
    sidecar (R1, see the module docstring): exact match proceeds;
    an exact-prefix sidecar (crash window) is advanced to the current
    head and `self.healed` is set; any other mismatch, a corrupt
    sidecar, or a missing sidecar on a non-empty stream refuses with
    LedgerError — unless the caller passes adopt_uncommitted=True
    for the missing-sidecar case, which adopts the stream
    (`self.adopted` set; the sidecar records the adoption) while its
    pre-adoption history stays honestly uncommitted in the rollup.
    """

    def __init__(self, path, host, adopt_uncommitted=False):
        if host not in HOSTS:
            raise LedgerError(f"host must be one of {list(HOSTS)}, "
                              f"got {host!r}")
        self.path = str(path)
        self.host = host
        self.healed = False
        self.adopted = False
        self._heals = []
        self._adopted_at_line_count = None
        self._adopt_requested = bool(adopt_uncommitted)
        stream = read_stream(self.path)
        if stream["parse_errors"]:
            bad = sorted(stream["parse_errors"])[0]
            raise LedgerError(
                f"existing stream {self.path} line {bad} does not "
                f"parse ({stream['parse_errors'][bad]}); refusing to "
                "append to a corrupt stream")
        breaks = verify_chain(stream["lines"], stream["events"])
        if breaks:
            raise LedgerError(
                f"existing stream {self.path} has a broken hash chain "
                f"at line {breaks[0]['line']}; refusing to extend it "
                "— corrections are new events on a sound stream")
        self._lines = len(stream["lines"])
        self._head = (line_hash(stream["lines"][-1])
                      if stream["lines"] else GENESIS_HASH)
        self._ids = {ev["event_id"] for ev in stream["events"]
                     if isinstance(ev, dict)
                     and isinstance(ev.get("event_id"), str)}
        # Minting state (F5): next sequence is max(existing numeric
        # sequence for this host prefix) + 1, never the line count,
        # so caller-supplied IDs cannot brick or rewind minting.
        self._max_seq = 0
        self._last_event_id = None
        for ev in stream["events"]:
            if not isinstance(ev, dict):
                continue
            eid = ev.get("event_id")
            if isinstance(eid, str):
                self._last_event_id = eid
                m = re.match(r"^([a-z]+)-(\d{4,})$", eid)
                if m and m.group(1) == host:
                    self._max_seq = max(self._max_seq,
                                        int(m.group(2)))
        self._gate_on_head_commitment(stream)

    def _gate_on_head_commitment(self, stream):
        """R1: verify the head-commitment sidecar before this writer
        may append to an existing stream. The chain has already
        verified (see __init__). Cases, in order:

        - no sidecar + empty stream: fresh stream, proceed.
        - no sidecar + non-empty stream: REFUSE, unless the caller
          opted into adoption (adopt_uncommitted=True) — adoption
          writes the sidecar marked adopted at the current head.
        - sidecar matches (line_count AND head_hash): proceed,
          carrying any adoption marker forward.
        - CRASH-WINDOW HEAL (the only mismatch that may proceed):
          sidecar.line_count < actual line count AND the sidecar's
          head_hash is exactly the hash of the stream line at
          sidecar.line_count (the GENESIS hash for 0) — the sidecar
          is an exact prefix state of a verified chain. Advance the
          sidecar to the current head, recording a durable heal
          entry in its `heals` list (carried forward on all later
          rewrites, like the adoption marker), set self.healed,
          proceed.
        - everything else (sidecar ahead of the stream, a head
          mismatch that is not an exact prefix state, a corrupt or
          unparseable sidecar): REFUSE with LedgerError naming
          expected vs actual; nothing is written.
        """
        commitment = read_head_commitment(self.path)
        if commitment is None:
            if self._lines == 0:
                return
            if not self._adopt_requested:
                raise LedgerError(
                    f"existing stream {self.path} has "
                    f"{self._lines} line(s) but no head-commitment "
                    "sidecar; refusing to append — the tail is "
                    "uncommitted and appending would silently commit "
                    "it. Pass adopt_uncommitted=True to adopt the "
                    "stream explicitly (its pre-adoption history "
                    "stays named uncommitted in the rollup)")
            self.adopted = True
            self._adopted_at_line_count = self._lines
            self._write_head_commitment()
            return
        sc_count = commitment.get("line_count")
        sc_head = commitment.get("head_hash")
        if not isinstance(sc_count, int) \
                or isinstance(sc_count, bool) \
                or not isinstance(sc_head, str):
            raise LedgerError(
                f"head-commitment sidecar for {self.path} is "
                f"corrupt/unparseable: expected a commitment with "
                f"integer line_count and head_hash, actual sidecar "
                f"content {commitment!r}; stream actually has "
                f"line_count {self._lines}, head_hash {self._head}; "
                "refusing to append, stream and sidecar untouched")
        if commitment.get("adopted"):
            self.adopted = True
            self._adopted_at_line_count = commitment.get(
                "adopted_at_line_count")
        prior_heals = commitment.get("heals")
        if isinstance(prior_heals, list):
            # Durable heal history (fix round 3): carried forward on
            # every later sidecar rewrite, exactly like the adoption
            # marker, so a heal can never be erased by a later append.
            self._heals = [dict(h) if isinstance(h, dict) else h
                           for h in prior_heals]
        if sc_count == self._lines and sc_head == self._head:
            return  # exact match: proceed
        prefix_head = None
        if sc_count == 0:
            prefix_head = GENESIS_HASH
        elif 0 < sc_count < self._lines:
            prefix_head = line_hash(stream["lines"][sc_count - 1])
        if 0 <= sc_count < self._lines and sc_head == prefix_head:
            # Crash window: stream fsync landed, sidecar replace did
            # not. The sidecar is an exact prefix state of a chain
            # that verified — advance it to the current head, and
            # record the heal durably so it is never silent.
            self._heals.append({
                "healed_at_line_count": sc_count,
                "stream_lines_at_heal": self._lines,
                "healed_head_hash": self._head,
            })
            self.healed = True
            self._write_head_commitment()
            return
        raise LedgerError(
            f"head-commitment mismatch for {self.path}: sidecar "
            f"expects line_count {sc_count}, head_hash {sc_head}; "
            f"actual stream has line_count {self._lines}, "
            f"head_hash {self._head}; refusing to append — appending "
            "would rewrite the sidecar to match a tail the writer "
            "never committed (no append, no sidecar write, stream "
            "untouched)")

    @property
    def head_hash(self):
        return self._head

    @property
    def line_count(self):
        return self._lines

    def append(self, candidate):
        """Validate and append one event; returns the stored event
        (with event_id minted if absent, and prev_hash set). Raises
        ValidationError with named reasons; on failure nothing is
        written."""
        return self.append_many([candidate])[0]

    def _write_head_commitment(self):
        """Rewrite the head-commitment sidecar atomically (F1):
        temp file in the same directory, fsync, then os.replace over
        the previous sidecar. Called only AFTER a stream append has
        succeeded, with the writer's state already updated."""
        payload = {
            "head_hash": self._head,
            "line_count": self._lines,
            "last_event_id": self._last_event_id,
            "host": self.host,
        }
        if self.adopted:
            # Adoption marker (R1): carried forward on every later
            # rewrite so the rollup keeps naming this stream's
            # pre-adoption history as uncommitted (adopted history).
            payload["adopted"] = True
            payload["adopted_at_line_count"] = \
                self._adopted_at_line_count
        if self._heals:
            # Durable heal markers (fix round 3): carried forward on
            # every later rewrite so the rollup keeps naming this
            # stream in healed_streams; heals accumulate, never reset.
            payload["heals"] = [dict(h) if isinstance(h, dict) else h
                                for h in self._heals]
        data = (json.dumps(payload, sort_keys=True) + "\n").encode(
            "utf-8")
        sidecar = head_sidecar_path(self.path)
        parent = os.path.dirname(os.path.abspath(sidecar))
        os.makedirs(parent, exist_ok=True)
        tmp = sidecar + f".tmp-{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, sidecar)

    def append_many(self, candidates):
        prepared = []
        max_seq = self._max_seq
        head = self._head
        ids = set(self._ids)
        new_lines = []
        for cand in candidates:
            if not isinstance(cand, dict):
                raise ValidationError(["candidate event is not a "
                                       "JSON object"])
            ev = dict(cand)
            # NOTE (F6): a caller-supplied prev_hash is NOT stripped
            # here. The validator's documented contract wins:
            # validate_event(stored=False) rejects it by name
            # ("prev_hash is writer-managed; candidates must not
            # carry it"), and nothing is written.
            if "event_id" not in ev:
                max_seq += 1
                ev["event_id"] = f"{self.host}-{max_seq:06d}"
            else:
                m = re.match(r"^([a-z]+)-(\d{4,})$",
                             ev["event_id"]) \
                    if isinstance(ev.get("event_id"), str) else None
                if m and m.group(1) == self.host:
                    max_seq = max(max_seq, int(m.group(2)))
            if ev["event_id"] in ids:
                raise ValidationError(
                    [f"event_id {ev['event_id']!r} already exists in "
                     "this stream; event_ids are stable and unique"])
            ids.add(ev["event_id"])
            reasons = validate_event(ev, stored=False)
            if reasons:
                raise ValidationError(reasons)
            ev["prev_hash"] = head
            line = serialize_event(ev)
            new_lines.append(line)
            head = line_hash(line.encode("utf-8"))
            prepared.append(ev)
        if new_lines:
            parent = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(parent, exist_ok=True)
            with open(self.path, "ab") as f:
                for line in new_lines:
                    f.write(line.encode("utf-8") + b"\n")
                f.flush()
                os.fsync(f.fileno())
            self._lines += len(new_lines)
            self._head = head
            self._ids = ids
            self._max_seq = max_seq
            self._last_event_id = prepared[-1]["event_id"]
            self._write_head_commitment()
        return prepared
