#!/usr/bin/env python3
"""Cabinet Registrar — production append/project tooling.

Implements the write discipline of CABINET_ID_SPEC_V1 §3–§4 for the
registry at docs/cabinet-registry/REGISTRY.jsonl, replacing the Step 1
genesis builder (a one-shot script with a hardcoded table that rewrote
the registry with `wb`; ruled genesis-only in the Step 1 Codex review —
it must never be reused for appends).

Properties enforced here, mechanically (§3):
- Appends are accepted only against the expected accepted head: the
  caller states the head hash it built on; a moved head is a stale-head
  rejection, never a merge.
- MINT sequences are allocated from the greatest MINT sequence in the
  accepted history, never from the tail event.
- The complete candidate fold is validated before anything is written
  (schema, chain, sequence uniqueness/monotonicity, referenced Cabinets
  exist, at most one active primary per member, targeted UNLINKs).
- History is append-only: the registry file is opened in append mode;
  existing bytes are never rewritten.
- The fold refuses a registry with a partial tail (§4) until the tail
  is removed by the explicit `recover` operation and the removal is
  recorded in INDEX.md.
- Projections (PROJECTION.json + INDEX.md) are built only from the
  accepted fold, cover MINT/LINK/UNLINK, and are verified by readback.

CLI:
  registrar.py verify  --registry PATH
  registrar.py fold    --registry PATH
  registrar.py append  --registry PATH --expected-head HEX --events FILE
  registrar.py project --registry PATH [--out-dir DIR] [--labels FILE]
                       [--generated-at ISO]
  registrar.py recover --registry PATH
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

GENESIS_HASH = hashlib.sha256(b"").hexdigest()
SYSTEMS = {"vm-spine", "claim-register", "home-runloop", "claim-service"}
RELATIONS = {"primary", "secondary"}
MINT_REASONS = {"new-work-area"}
LINK_REASONS = {"shared-artifact", "dispatch-record", "admitted-claim-describes",
                "title-citation", "owner-decision", "merge-movement",
                "secondary-relation"}
UNLINK_REASONS = {"evidence-refuted", "merge-movement", "wrong-member",
                  "forget-consequence", "owner-decision"}
REASON_VOCAB = {"MINT": MINT_REASONS, "LINK": LINK_REASONS,
                "UNLINK": UNLINK_REASONS}
FIELD_ORDER = ["type", "cabinet_id", "at", "actor", "member", "relation",
               "evidence", "corrects", "reason", "prev_hash"]
MEMBER_FIELDS = {"system", "id", "kind"}
CABINET_RE = re.compile(r"^cab-(\d{4,})$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_RE = re.compile(r"^sha256:([0-9a-f]{64})@(.+)$")
TZ = ZoneInfo("America/Los_Angeles")


class RegistryError(Exception):
    pass


class PartialTailError(RegistryError):
    """The final line is a crash artifact, not an event (§4)."""


class StaleHeadError(RegistryError):
    pass


class ValidationError(RegistryError):
    pass


def now_iso():
    return datetime.now(TZ).replace(microsecond=0).isoformat()


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


def head_of(lines):
    return line_hash(lines[-1]) if lines else GENESIS_HASH


# ---------------------------------------------------------------- parsing

def _pairs_no_dupes(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise RegistryError(f"duplicate JSON key: {k}")
        obj[k] = v
    return obj


def parse_registry_bytes(data):
    """Strict §4 byte parse. Returns (line_bytes, events) with line_bytes
    excluding LF terminators. Refuses: CR bytes, invalid UTF-8, invalid
    JSON, duplicate keys, non-object lines. A defect confined to the
    final line — including a missing LF terminator — is a PartialTailError
    (the fold must refuse until the tail is removed); a defect in any
    earlier line is a hard RegistryError."""
    if data == b"":
        return [], []
    ends_lf = data.endswith(b"\n")
    body = data[:-1] if ends_lf else data
    raw = body.split(b"\n")
    lines, events = [], []
    for i, lb in enumerate(raw):
        is_last = i == len(raw) - 1
        if is_last and not ends_lf:
            raise PartialTailError(
                f"line {i + 1}: missing LF terminator (partial tail)")
        err, ev = None, None
        if b"\r" in lb:
            err = "CR byte in line"
        else:
            try:
                text = lb.decode("utf-8")
            except UnicodeDecodeError:
                err = "invalid UTF-8"
            else:
                try:
                    ev = json.loads(text, object_pairs_hook=_pairs_no_dupes)
                except RegistryError as e:
                    err = str(e)
                except json.JSONDecodeError as e:
                    err = f"invalid JSON: {e}"
                else:
                    if not isinstance(ev, dict):
                        err = "line is not a JSON object"
        if err is not None:
            if is_last:
                raise PartialTailError(f"line {i + 1}: {err} (partial tail)")
            raise RegistryError(f"line {i + 1}: {err}")
        lines.append(lb)
        events.append(ev)
    return lines, events


def read_registry(path):
    if not os.path.exists(path):
        return [], []
    with open(path, "rb") as f:
        return parse_registry_bytes(f.read())


def verify_chain(lines, events):
    for i, ev in enumerate(events):
        expected = GENESIS_HASH if i == 0 else line_hash(lines[i - 1])
        if ev.get("prev_hash") != expected:
            raise ValidationError(
                f"line {i + 1}: prev_hash mismatch (chain broken)")


# -------------------------------------------------------------- validation

def _no_whitespace_values(v, path="event"):
    if isinstance(v, str):
        if any(ch.isspace() for ch in v):
            raise ValidationError(
                f"{path}: string value contains whitespace "
                f"(§6 closed history inventory): {v!r}")
    elif isinstance(v, dict):
        for k, x in v.items():
            _no_whitespace_values(x, f"{path}.{k}")
    elif isinstance(v, list):
        for x in v:
            _no_whitespace_values(x, path)


def validate_event(ev):
    """Schema + value validation of one event (§4 inventories). Raises
    ValidationError on the first defect found."""
    t = ev.get("type")
    if t not in REASON_VOCAB:
        raise ValidationError(f"bad event type: {t!r}")
    expected = {"type", "cabinet_id", "at", "actor", "reason", "prev_hash"}
    if t in ("LINK", "UNLINK"):
        expected |= {"member", "relation", "evidence"}
    if t == "UNLINK":
        expected |= {"corrects"}
    if set(ev) != expected:
        raise ValidationError(
            f"{t} field inventory mismatch: got {sorted(ev)}, "
            f"want {sorted(expected)}")
    cab = ev["cabinet_id"]
    m = CABINET_RE.match(cab) if isinstance(cab, str) else None
    if m is None or int(m.group(1)) < 1:
        raise ValidationError(f"bad cabinet_id: {cab!r}")
    if not _tz_qualified_iso(ev["at"]):
        raise ValidationError(f"at is not a tz-qualified ISO-8601: {ev['at']!r}")
    if not isinstance(ev["actor"], str) or not ev["actor"]:
        raise ValidationError("actor must be a non-empty string")
    reason = ev["reason"]
    code, at_sign, suffix = (reason.partition("@")
                             if isinstance(reason, str) else ("", "", ""))
    if code not in REASON_VOCAB[t] or (at_sign and not SHA256_RE.match(suffix)):
        raise ValidationError(f"bad reason code for {t}: {reason!r}")
    if not isinstance(ev["prev_hash"], str) or not SHA256_RE.match(ev["prev_hash"]):
        raise ValidationError("prev_hash must be lowercase sha256 hex")
    _no_whitespace_values(ev)
    if t in ("LINK", "UNLINK"):
        mem = ev["member"]
        if not isinstance(mem, dict) or set(mem) != MEMBER_FIELDS:
            raise ValidationError("member must have exactly system/id/kind")
        if mem["system"] not in SYSTEMS:
            raise ValidationError(f"unknown member system: {mem['system']!r}")
        if not isinstance(mem["id"], str) or not mem["id"]:
            raise ValidationError("member id must be a non-empty string")
        if not isinstance(mem["kind"], str) or not mem["kind"]:
            raise ValidationError("member kind must be a non-empty string")
        if ev["relation"] not in RELATIONS:
            raise ValidationError(f"bad relation: {ev['relation']!r}")
        em = EVIDENCE_RE.match(ev["evidence"]) \
            if isinstance(ev["evidence"], str) else None
        if em is None or not _tz_qualified_iso(em.group(2)):
            raise ValidationError(
                "evidence must be sha256:<digest>@<tz-qualified capture>")
    if t == "UNLINK":
        corr = ev["corrects"]
        if not isinstance(corr, str) or not corr.isdigit() or int(corr) < 1:
            raise ValidationError(
                f"corrects must be the string form of a registry line "
                f"number: {corr!r}")


def fold_events(events):
    """Fold + fully validate an event history (§3/§4 fold semantics).
    Returns the state dict (JSON-serializable). Raises ValidationError."""
    cabinets = {}   # cab -> {"mint_line": n, "members": [records]}
    members = {}    # (system, id) -> {"primary": rec|None, "secondary": [rec]}
    records = {}    # registry line -> LINK record (for UNLINK targeting)
    max_mint = 0
    for i, ev in enumerate(events, 1):
        validate_event(ev)
        t, cab = ev["type"], ev["cabinet_id"]
        if t == "MINT":
            seq = int(CABINET_RE.match(cab).group(1))
            if cab in cabinets:
                raise ValidationError(f"line {i}: duplicate MINT for {cab}")
            if seq <= max_mint:
                raise ValidationError(
                    f"line {i}: MINT sequence {seq} is not greater than "
                    f"the accepted maximum {max_mint}")
            max_mint = seq
            cabinets[cab] = {"mint_line": i, "members": []}
        elif t == "LINK":
            if cab not in cabinets:
                raise ValidationError(
                    f"line {i}: LINK references unminted Cabinet {cab}")
            mem = ev["member"]
            key = (mem["system"], mem["id"])
            slot = members.setdefault(key, {"primary": None, "secondary": []})
            if ev["relation"] == "primary" and slot["primary"] is not None:
                raise ValidationError(
                    f"line {i}: member {key} already has an active primary "
                    f"({slot['primary']['cabinet_id']})")
            rec = {"system": mem["system"], "id": mem["id"],
                   "kind": mem["kind"], "relation": ev["relation"],
                   "cabinet_id": cab, "registry_line": i, "active": True,
                   "unlinked_by": None}
            records[i] = rec
            cabinets[cab]["members"].append(rec)
            if ev["relation"] == "primary":
                slot["primary"] = rec
            else:
                slot["secondary"].append(rec)
        else:  # UNLINK
            if cab not in cabinets:
                raise ValidationError(
                    f"line {i}: UNLINK references unminted Cabinet {cab}")
            tgt = records.get(int(ev["corrects"]))
            if tgt is None:
                raise ValidationError(
                    f"line {i}: corrects names no LINK: line {ev['corrects']}")
            if not tgt["active"]:
                raise ValidationError(
                    f"line {i}: target LINK at line {ev['corrects']} is "
                    f"not active")
            mem = ev["member"]
            if (tgt["cabinet_id"] != cab or tgt["system"] != mem["system"]
                    or tgt["id"] != mem["id"] or tgt["kind"] != mem["kind"]
                    or tgt["relation"] != ev["relation"]):
                raise ValidationError(
                    f"line {i}: UNLINK does not match its target LINK "
                    f"at line {ev['corrects']}")
            tgt["active"] = False
            tgt["unlinked_by"] = i
            slot = members[(mem["system"], mem["id"])]
            if tgt["relation"] == "primary":
                slot["primary"] = None
            else:
                slot["secondary"] = [r for r in slot["secondary"]
                                     if r is not tgt]
    out_cabinets = {}
    for cab in sorted(cabinets, key=lambda c: int(c[4:])):
        active = [{k: r[k] for k in ("system", "id", "kind", "relation",
                                     "registry_line")}
                  for r in cabinets[cab]["members"] if r["active"]]
        out_cabinets[cab] = {"mint_line": cabinets[cab]["mint_line"],
                             "members": active}
    out_members = {}
    for (system, mid), slot in sorted(members.items()):
        p = slot["primary"]
        out_members[f"{system}:{mid}"] = {
            "primary": ({"cabinet_id": p["cabinet_id"],
                         "registry_line": p["registry_line"]}
                        if p else None),
            "secondary": [{"cabinet_id": r["cabinet_id"],
                           "registry_line": r["registry_line"]}
                          for r in slot["secondary"]]}
    return {"cabinets": out_cabinets, "members": out_members,
            "max_mint_seq": max_mint, "event_count": len(events)}


def serialize_event(ev):
    ordered = {k: ev[k] for k in FIELD_ORDER if k in ev}
    if "member" in ordered:
        mem = ordered["member"]
        ordered["member"] = {k: mem[k] for k in ("system", "id", "kind")}
    return json.dumps(ordered, ensure_ascii=False)


# ---------------------------------------------------------------- locking

class AppendLock:
    """Single-writer lockfile beside the registry (house discipline,
    same pattern as the claim register: O_EXCL, stale after 120 s)."""

    def __init__(self, registry_path):
        self.path = registry_path + ".lock"
        self.fd = None

    def __enter__(self):
        import time
        deadline = time.time() + 30
        while True:
            try:
                self.fd = os.open(self.path,
                                  os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > 120:
                        os.unlink(self.path)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() > deadline:
                    raise RegistryError("registry is locked by another writer")
                time.sleep(0.25)

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        return False


# ----------------------------------------------------------------- append

def append_events(registry_path, candidates, expected_head):
    """Validate and append candidate events (dicts without prev_hash;
    a MINT candidate may omit cabinet_id to take the next sequence from
    the accepted maximum). Accepted only against `expected_head`.
    Returns {"head", "lines", "first_new_line", "appended"}."""
    with AppendLock(registry_path):
        lines, events = read_registry(registry_path)
        verify_chain(lines, events)
        state = fold_events(events)  # the accepted history must itself fold
        head = head_of(lines)
        if head != expected_head:
            raise StaleHeadError(
                f"stale head: built on {expected_head}, "
                f"accepted head is {head}; append rejected, nothing written")
        next_seq = state["max_mint_seq"]
        new_lines = []
        for cand in candidates:
            if not isinstance(cand, dict):
                raise ValidationError("candidate event is not a JSON object")
            ev = dict(cand)
            ev.pop("prev_hash", None)
            if ev.get("type") == "MINT" and not ev.get("cabinet_id"):
                next_seq += 1
                ev["cabinet_id"] = f"cab-{next_seq:04d}"
            ev["prev_hash"] = head
            line = serialize_event(ev)
            validate_event(ev)
            new_lines.append(line)
            lines.append(line.encode("utf-8"))
            events.append(ev)
            head = line_hash(line.encode("utf-8"))
        fold_events(events)      # complete candidate-fold validation (§3)
        verify_chain(lines, events)
        if new_lines:
            with open(registry_path, "ab") as f:
                for line in new_lines:
                    f.write(line.encode("utf-8") + b"\n")
                f.flush()
                os.fsync(f.fileno())
    return {"head": head, "lines": len(lines),
            "first_new_line": len(lines) - len(new_lines) + 1,
            "appended": len(new_lines)}


# -------------------------------------------------------------- projection

def build_projection(state, head, n_lines, generated_at):
    """PROJECTION.json content from the accepted fold. The cabinets
    section carries every active membership; the members section maps
    each member to its primary (or earliest) membership, with any
    further active memberships under "also". For a primary-only history
    this is exactly the genesis projection shape."""
    cabinets = {}
    for cab, c in state["cabinets"].items():
        cabinets[cab] = {"members": [dict(m) for m in c["members"]]}
    members = {}
    # Rebuild per-member groupings from the cabinets section to keep one
    # source of truth inside the projection itself.
    by_member = {}
    for cab, c in cabinets.items():
        for m in c["members"]:
            by_member.setdefault(f"{m['system']}:{m['id']}", []).append(
                {"cabinet_id": cab, "relation": m["relation"],
                 "registry_line": m["registry_line"]})
    for key, lst in by_member.items():
        lst.sort(key=lambda x: x["registry_line"])
        base = next((x for x in lst if x["relation"] == "primary"), lst[0])
        entry = {"cabinet_id": base["cabinet_id"],
                 "relation": base["relation"],
                 "registry_line": base["registry_line"]}
        rest = [x for x in lst if x is not base]
        if rest:
            entry["also"] = rest
        members[key] = entry
    return {"projection": "cabinet-membership-v1",
            "generated_from": {"registry_head_sha256": head,
                               "registry_lines": n_lines,
                               "generated_at": generated_at},
            "cabinets": cabinets, "members": members}


def projection_bytes(proj):
    return (json.dumps(proj, ensure_ascii=False, indent=1, sort_keys=True)
            + "\n").encode("utf-8")


def parse_index_labels(index_text):
    labels = {}
    for line in index_text.splitlines():
        m = re.match(r"^\|\s*(cab-\d{4,})\s*\|\s*([^|]+?)\s*\|", line)
        if m:
            labels[m.group(1)] = m.group(2)
    return labels


def extract_section(index_text, heading):
    """Return the verbatim section starting at `heading` up to the next
    '## ' heading or EOF (used to carry pending exhibits / recovery
    records across INDEX regenerations)."""
    lines = index_text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith(heading)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).rstrip() + "\n"


def build_index(state, head, n_lines, labels, pending_section="",
                recovery_section="", note=""):
    idx = ["# Cabinet Registrar — Index", "",
           "Human index of the Cabinet Registrar registry (`REGISTRY.jsonl`, "
           "the source of",
           "truth; this file is a projection of its accepted fold). Work-area "
           "labels live",
           "only on this surface and in projections — never in registry "
           "history lines",
           "(spec §6 history rule). A record is always cited by its native",
           "(owning-system, ID) pair; a Cabinet ID names a work area only.",
           "",
           f"- Accepted head: `{head}` · {n_lines} registry lines"
           + (f" · {note}" if note else ""), "",
           "## Cabinets", "",
           "| Cabinet | INDEX label | Members (owning-system: native ID — relation) |",
           "|---|---|---|"]
    n_primary = n_secondary = 0
    per_system = {}
    for cab, c in state["cabinets"].items():
        mem = []
        for m in c["members"]:
            mem.append(f"{m['system']}: {m['id']} — {m['relation']}")
            if m["relation"] == "primary":
                n_primary += 1
            else:
                n_secondary += 1
            per_system[m["system"]] = per_system.get(m["system"], 0) + 1
        label = labels.get(cab, "—")
        idx.append(f"| {cab} | {label} | " + "<br>".join(mem) + " |")
    idx += ["", "## Coverage", "",
            f"- Cabinets minted: {len(state['cabinets'])} "
            f"(cab-0001…cab-{state['max_mint_seq']:04d}).",
            f"- Active memberships: {n_primary + n_secondary} — "
            f"{n_primary} primary, {n_secondary} secondary"
            + (". Per system: " + ", ".join(
                f"{s} {n}" for s, n in sorted(per_system.items())) + "."
               if per_system else "."),
            ""]
    if pending_section:
        idx.append(pending_section.rstrip())
        idx.append("")
    if recovery_section:
        idx.append(recovery_section.rstrip())
        idx.append("")
    return "\n".join(idx).rstrip() + "\n"


def project(registry_path, out_dir=None, labels=None, generated_at=None):
    """Rebuild PROJECTION.json (+ INDEX.md) from the accepted fold and
    verify by readback: the written projection must re-derive from an
    independent re-fold of the registry on disk."""
    out_dir = out_dir or os.path.dirname(os.path.abspath(registry_path))
    lines, events = read_registry(registry_path)
    verify_chain(lines, events)
    state = fold_events(events)
    head = head_of(lines)
    generated_at = generated_at or now_iso()
    proj = build_projection(state, head, len(lines), generated_at)
    proj_path = os.path.join(out_dir, "PROJECTION.json")
    with open(proj_path, "wb") as f:
        f.write(projection_bytes(proj))
    index_path = os.path.join(out_dir, "INDEX.md")
    old_index = ""
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            old_index = f.read()
    merged_labels = parse_index_labels(old_index)
    if labels:
        merged_labels.update(labels)
    new_index = build_index(
        state, head, len(lines), merged_labels,
        pending_section=extract_section(old_index, "## Pending exhibits"),
        recovery_section=extract_section(old_index, "## Recovery records"),
        note=f"projection rebuilt {generated_at} from the accepted fold")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(new_index)
    # Readback: re-read everything and re-derive.
    lines2, events2 = read_registry(registry_path)
    state2 = fold_events(events2)
    with open(proj_path, "rb") as f:
        written = json.loads(f.read().decode("utf-8"))
    expect = build_projection(state2, head_of(lines2), len(lines2),
                              generated_at)
    if written != expect:
        raise RegistryError("projection readback mismatch after write")
    return {"head": head, "lines": len(lines),
            "cabinets": len(state["cabinets"]),
            "active_memberships": sum(len(c["members"])
                                      for c in state["cabinets"].values())}


# ---------------------------------------------------------------- recover

def recover_tail(registry_path, index_path=None):
    """Remove a partial tail (§4) and return the removal record. The
    prefix must parse, chain-verify and fold cleanly before anything is
    truncated; interior corruption is never 'recovered' this way."""
    with open(registry_path, "rb") as f:
        data = f.read()
    try:
        lines, events = parse_registry_bytes(data)
        return {"removed_bytes": 0, "record": None,
                "head": head_of(lines), "lines": len(lines)}
    except PartialTailError:
        pass
    # The recoverable prefix drops exactly the final line (LF-terminated
    # or not): a crash interrupts one append. If the remainder still does
    # not parse, the damage is not a tail artifact and is never truncated.
    if data.endswith(b"\n"):
        prev_lf = data.rfind(b"\n", 0, len(data) - 1)
    else:
        prev_lf = data.rfind(b"\n")
    prefix = data[:prev_lf + 1] if prev_lf >= 0 else b""
    try:
        lines, events = parse_registry_bytes(prefix)
    except RegistryError as e:
        raise RegistryError(
            f"tail is not recoverable by single-line removal: {e}")
    verify_chain(lines, events)
    fold_events(events)
    removed = len(data) - len(prefix)
    with open(registry_path, "r+b") as f:
        f.truncate(len(prefix))
    record = (f"- Recovery {now_iso()}: removed {removed} trailing "
              f"partial byte(s) (crash artifact, no complete event); "
              f"accepted history is {len(lines)} lines, "
              f"head `{head_of(lines)}`.")
    if index_path and os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            text = f.read()
        if "## Recovery records" in text:
            text = text.rstrip() + "\n" + record + "\n"
        else:
            text = text.rstrip() + "\n\n## Recovery records\n\n" + record + "\n"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(text)
    return {"removed_bytes": removed, "record": record,
            "head": head_of(lines), "lines": len(lines)}


# -------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("verify", "fold", "project", "recover"):
        p = sub.add_parser(name)
        p.add_argument("--registry", required=True)
        if name == "project":
            p.add_argument("--out-dir")
            p.add_argument("--labels")
            p.add_argument("--generated-at")
    p = sub.add_parser("append")
    p.add_argument("--registry", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--events", required=True)
    args = ap.parse_args()
    try:
        if args.cmd == "verify":
            lines, events = read_registry(args.registry)
            verify_chain(lines, events)
            state = fold_events(events)
            out = {"ok": True, "lines": len(lines),
                   "head": head_of(lines), **state}
        elif args.cmd == "fold":
            lines, events = read_registry(args.registry)
            verify_chain(lines, events)
            out = fold_events(events)
        elif args.cmd == "append":
            with open(args.events, encoding="utf-8") as f:
                candidates = json.load(f)
            out = append_events(args.registry, candidates,
                                args.expected_head)
        elif args.cmd == "project":
            labels = None
            if args.labels:
                with open(args.labels, encoding="utf-8") as f:
                    labels = json.load(f)
            out = project(args.registry, out_dir=args.out_dir,
                          labels=labels, generated_at=args.generated_at)
        elif args.cmd == "recover":
            index = os.path.join(os.path.dirname(
                os.path.abspath(args.registry)), "INDEX.md")
            out = recover_tail(args.registry, index_path=index)
    except RegistryError as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
