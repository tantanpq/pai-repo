#!/usr/bin/env python3
"""Pack assembler + serve path — Phase 4, Slice 2.

Compiles bounded, budgeted context packs in the shape of
`contracts/context-package.md` from the Phase 3 cabinet read API
(`packages/cabinet/read_api.py`, consumed READ-ONLY through an
injected instance or factory), and serves them under the rights
rules of PHASE4_DESIGN_DOSSIER_V1 §1.2:

- Every manifest record is resolved through the read API. A pack's
  derived level is the strictest member level, computed AT SERVE
  TIME from fresh resolutions — it is never stamped into the pack
  manifest at assembly time (levels change: edits, forgets).
- Any manifest record whose current level is `unknown` denies the
  WHOLE serve, with the exclusion named (mirrors cabinet()
  combined-read semantics in READ_API.md). Records merely above the
  consumer's entitlement are served around: entitled sections plus
  a named exclusion report.
- HOME registry-only members (`home-runloop`, `claim-service`) are
  served as POINTER sections: structure + level, no body. Content
  stays with the owning systems on HOME (spec §5.1).
- Forgotten records appear ONLY as tombstones — the rule-6 closed
  set (system, ID, forget timestamp, actor). Their content is
  absent and their former privacy level is never emitted anywhere
  in a serve result: forgotten members are excluded from the
  derived-level computation exactly as the read API excludes them.
- Oversize content is bounded at ASSEMBLY time: budgets are counted
  before assembly completes (contract rule 2), and an over-budget
  section is stored in the version plan as a bounded segment plus
  an explicit truncation marker plus a continuation cursor —
  never silently dropped (contract rule 3). The cursor is opaque
  and bound to the pack version's source-hash set; resuming after
  any source content_hash change fails loudly as STALE
  (contract rule 5).
- Freshness is recorded per source at every serve, using the
  retrieval package's fingerprint-compare mechanism
  (`retrieval_query.freshness`: a source whose current fingerprint
  differs from the recorded one is STALE) applied per record:
  the fingerprint is the record's content_hash. Stale content is
  never presented as current (contract rule 7): a stale section is
  excluded and named, not served.
- Packs are retrieval-only (contract rule 6): sections carry the
  record itself (canonical JSON) plus its citation anchor — no
  generated prose is ever produced here.

Pack versions live in an append-only JSONL manifest inside a
caller-supplied room directory (`<room>/manifest.jsonl`). Any
manifest change (source set, a source's content_hash, budgets,
purpose) mints a new version: pack_id stays stable, the previous
version is superseded with `invalid_at` set. Nothing in this
module writes to the claim register, the Registrar registry, or
any production store; the manifest (and its head-commitment
sidecar, below) is the only file it writes, and only inside the
room directory it was handed.

Serve / resume accounting goes through an OPTIONAL ledger sink
(any object with LedgerWriter.append's shape, e.g.
`ledger.LedgerWriter`); the default is None and this module never
imports the ledger — accounting is a sink, not a dependency.

Stdlib only; Python 3.11+ (Windows and Linux).

Slice-2 API-gap flags (read_api.py is consumed read-only; these
are designed around, NOT patched — see SLICE2_BUILD_NOTES.md):
  F-1  The read API returns no content_hash and no content anchor.
       The pack computes content_hash itself (sha256 of the
       canonical JSON of the resolved content, EXCLUDING the
       top-level `privacy` field: privacy is rights metadata,
       re-checked as a level at serve time, so a privacy-only edit
       is a level change, not a content revision) and derives the
       anchor from the member's registry line when it is a member.
  F-2  The read API has no consumer/entitlement parameter: it
       reports each record's effective level and lets callers
       decide. The consumer model here — {identity, max_level} —
       is therefore the pack layer's own, built strictly on the
       levels the API reports.
  F-3  The retrieval freshness gate operates on file paths from
       its own index manifest; cabinet sources expose no paths
       through the read API. The pack applies the same
       fingerprint-compare semantics per record (above).
  F-4  A ReadAPI instance caches its native folds at construction
       (verified empirically, 2026-11-06): a long-lived instance
       does NOT observe later privacy/content edits. Serve-time
       recomputation therefore requires a FRESH instance per
       serve — construct this assembler with `api_factory` (a
       zero-arg callable returning a ReadAPI) for live use.
       Fix-1 #4: a single injected instance is accepted ONLY with
       the explicit opt-in `snapshot_ok=True` (the constructor
       raises without it), and every serve output then carries
       "snapshot_mode": true on its face.
"""
import base64
import hashlib
import json
import math
import os
from datetime import datetime, timezone

# Contract levels, loosest to strictest — mirrors read_api.LEVELS.
LEVELS = ("house", "private", "secret-pointer")
_STRICTNESS = {lvl: i for i, lvl in enumerate(LEVELS)}

# Registry-only systems (spec §5.1): pointer sections, never bodies.
POINTER_SYSTEMS = ("home-runloop", "claim-service")

TRUNCATION_MARKER = "\n[TRUNCATED: continuation cursor in footer]"
TOKEN_ESTIMATOR = "char/4"
MANIFEST_NAME = "manifest.jsonl"
MANIFEST_HEAD_NAME = "manifest.jsonl.head.json"

# Manifest hash chain (Fix-1 #8): same discipline as ledger.py —
# line N's prev_hash is the sha256 of line N-1's bytes; line 1
# chains to the genesis hash (sha256 of the empty byte string).
GENESIS_HASH = hashlib.sha256(b"").hexdigest()

# Fallback alias map, used only when the cabinet read_api module
# cannot be imported (see normalize_system).
_SYSTEM_ALIASES_FALLBACK = {"home-claim-service": "claim-service"}


def normalize_system(system):
    """Fix-1 #7: normalize a system name through the read API's
    alias map (read_api.normalize_system) at the pack boundary, so
    the contract alias `home-claim-service` resolves to the
    registry spelling `claim-service` and gets POINTER semantics
    instead of a registry-only exclusion. Falls back to a local
    copy of the same alias map when read_api is not importable
    from this process."""
    try:
        import read_api as _read_api
        return _read_api.normalize_system(system)
    except Exception:  # noqa: BLE001 — fallback is the same map
        return _SYSTEM_ALIASES_FALLBACK.get(system, system)

DEFAULT_CHAR_BUDGET = 4000
DEFAULT_TOKEN_BUDGET = 1000


class PackError(Exception):
    """Base error for pack assembly / serve failures."""


class StaleCursorError(PackError):
    """A continuation cursor was resumed against a changed source
    revision. The message always carries the loud STALE marker
    (contract rule 5)."""


class PackBudgetError(PackError):
    """A section budget cannot hold the truncation marker plus at
    least one content char (Fix-1 #3): assembly / serve / resume
    fail loudly instead of serving over budget or minting a cursor
    that never advances."""


class RetiredPackError(PackError):
    """A serve / resume was attempted against a retired pack
    (Fix-1 #1). The message always carries the loud RETIRED
    marker; no content is served."""


class PackNotFoundError(PackError):
    pass


# ---------------------------------------------------------------- helpers

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def est_tokens(text):
    """The retrieval package's shared estimator: ceil(chars/4)
    (retrieval_query.est_tokens). An estimator, not a tokenizer."""
    return math.ceil(len(text) / 4)


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_text_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def content_text_of(content):
    """The served body of a content-bearing record: the record
    itself as canonical JSON (retrieval-only, contract rule 6)."""
    return _canonical(content)


def content_hash_of(resolved):
    """F-1: the pack-layer content fingerprint of one resolution.

    Content-bearing records hash their content (privacy excluded —
    see module docstring). Contentless postures hash a small
    posture payload so a posture change is still a revision change
    for cursor binding."""
    if resolved.get("forgotten"):
        return _sha256_text(_canonical(
            {"tombstone": resolved.get("tombstone") or {}}))
    content = resolved.get("content")
    if content is not None:
        payload = {k: v for k, v in content.items() if k != "privacy"}
        return _sha256_text(_canonical(payload))
    system, mid = resolved.get("system"), resolved.get("id")
    if system in POINTER_SYSTEMS:
        return _sha256_text(_canonical(
            {"pointer": f"{system}:{mid}",
             "kind": resolved.get("kind")}))
    return _sha256_text(_canonical(
        {"system": system, "id": mid,
         "level": resolved.get("effective_privacy"),
         "excluded": resolved.get("content_excluded"),
         "note": resolved.get("content_note")}))


def anchor_of(resolved):
    """F-1: citation anchor from the resolution: the earliest
    cabinet registry line when the record is a cabinet member."""
    cabinets = resolved.get("cabinets") or []
    if cabinets:
        first = min(cabinets, key=lambda c: c["registry_line"])
        return (f"{first['cabinet_id']}#registry-line:"
                f"{first['registry_line']}")
    return f"{resolved.get('system')}:{resolved.get('id')}"


def source_hash_set_hash(sources):
    """Hash of a version's source-hash set — the revision a cursor
    binds to (contract rule 5). `sources` are manifest entries
    carrying (system, id, content_hash)."""
    pairs = sorted((s["system"], s["id"], s["content_hash"])
                   for s in sources)
    return _sha256_text(_canonical(
        [[sys_, mid, h] for sys_, mid, h in pairs]))


def _effective_limit(char_budget, token_budget):
    limit = char_budget
    if token_budget is not None:
        limit = min(limit, token_budget * 4)
    return limit


def _bounded_segment(full_text, offset, char_budget, token_budget):
    """One bounded segment of `full_text` starting at `offset`.

    Returns (segment_text, next_offset_or_None, truncated). The
    segment — marker included — never exceeds the effective budget,
    so its char count and its char/4 token estimate both stay within
    the declared budgets. Nothing is silently dropped: when content
    remains, the segment ends with the explicit truncation marker
    and next_offset names exactly where the continuation resumes."""
    limit = _effective_limit(char_budget, token_budget)
    remaining = full_text[offset:]
    if len(remaining) <= limit:
        return remaining, None, False
    # Fix-1 #3: the marker counts INSIDE the budget. A budget that
    # cannot hold marker + at least 1 content char can never serve
    # within budget and can never advance a cursor — fail loudly
    # instead of overflowing or looping on an identical cursor.
    if limit < len(TRUNCATION_MARKER) + 1:
        raise PackBudgetError(
            f"PackBudgetError: effective section budget {limit} "
            f"char(s) cannot fit the truncation marker "
            f"({len(TRUNCATION_MARKER)} chars) plus at least 1 "
            "content char; refusing to serve over budget or mint "
            "a non-advancing cursor")
    take = limit - len(TRUNCATION_MARKER)
    return remaining[:take] + TRUNCATION_MARKER, offset + take, True


def _normalize_consumer(consumer):
    """F-2 consumer model: {"identity": str, "max_level": level}.
    A bare string is read as a max_level with a generic identity."""
    if isinstance(consumer, str):
        consumer = {"identity": "consumer", "max_level": consumer}
    if not isinstance(consumer, dict):
        raise PackError(f"consumer must be a dict or level string, "
                        f"got {type(consumer).__name__}")
    identity = consumer.get("identity") or "consumer"
    level = consumer.get("max_level", consumer.get("level"))
    if level not in _STRICTNESS:
        raise PackError(f"consumer max_level must be one of "
                        f"{list(LEVELS)}, got {level!r}")
    return {"identity": str(identity), "max_level": level}


def _above(level, consumer_level):
    """True when `level` is stricter than the consumer's ceiling."""
    return _STRICTNESS[level] > _STRICTNESS[consumer_level]


# ---------------------------------------------------------------- cursors

def _encode_cursor(payload):
    raw = json.dumps(payload, ensure_ascii=False,
                     sort_keys=True).encode("utf-8")
    return "cur_" + base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor):
    if not isinstance(cursor, str) or not cursor.startswith("cur_"):
        raise PackError("malformed continuation cursor")
    try:
        payload = json.loads(base64.urlsafe_b64decode(
            cursor[4:].encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — reported, not hidden
        raise PackError(f"malformed continuation cursor: {exc}")
    if not isinstance(payload, dict) \
            or "pack_id" not in payload \
            or "sources_hash_set_hash" not in payload \
            or not isinstance(payload.get("offsets"), dict):
        raise PackError("malformed continuation cursor: bad payload")
    return payload


def _public_sources(sources, served_keys):
    """Fix-1 #2: consumer-facing source manifest. A member's
    content_hash is published ONLY when that member's content is
    served in this response (contract rule 1 applies to served
    members). Excluded, denied, pointer-only and forgotten members
    carry NO hash — a published hash of unserved content is an
    offline brute-force target and a change oracle. The internal
    room manifest file keeps every hash; only serve output is
    redacted."""
    out = []
    for s in sources:
        if (s["system"], s["id"]) in served_keys:
            out.append(dict(s))
        else:
            out.append({k: v for k, v in s.items()
                        if k != "content_hash"})
    return out


def _public_freshness(freshness, served_keys):
    """Fix-1 #2: consumer-facing freshness — same rule as
    _public_sources: hash fields only for members served in this
    response; everyone else carries system/id/status only."""
    out = []
    for f in freshness:
        if (f["system"], f["id"]) in served_keys:
            out.append(dict(f))
        else:
            out.append({"system": f["system"], "id": f["id"],
                        "status": f["status"]})
    return out


# ------------------------------------------------- manifest head sidecar

def _head_summary(last_event):
    """Summary fields for the sidecar's `last_event` (mirrors the
    ledger sidecar's last_event_id role): enough to name which
    event the committed head is, without duplicating the line."""
    if not isinstance(last_event, dict):
        return None
    summary = {}
    for key in ("event", "pack_id", "version"):
        if key in last_event:
            summary[key] = last_event[key]
    return summary


def _head_payload(head_hash, line_count, last_event):
    return {"head_hash": head_hash, "line_count": line_count,
            "last_event": _head_summary(last_event)}


def _write_manifest_head_sidecar(sidecar_path, head_hash,
                                 line_count, last_event):
    """Rewrite the head-commitment sidecar atomically (parity with
    ledger.LedgerWriter._write_head_commitment): temp file in the
    same directory, fsync, then os.replace. Called only AFTER a
    manifest append (or a verified crash-window heal) succeeded."""
    data = (json.dumps(_head_payload(head_hash, line_count,
                                     last_event),
                       sort_keys=True) + "\n").encode("utf-8")
    parent = os.path.dirname(os.path.abspath(sidecar_path))
    os.makedirs(parent, exist_ok=True)
    tmp = sidecar_path + f".tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, sidecar_path)


def _read_manifest_head_sidecar(sidecar_path):
    """Read the sidecar: parsed dict, None when absent, {} when
    present but unparseable / not an object (ledger discipline —
    a corrupt sidecar is a mismatch, never 'no commitment')."""
    if not os.path.exists(sidecar_path):
        return None
    try:
        with open(sidecar_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- assembler

class PackAssembler:
    """Assembles and serves context packs for one room directory.

    read_api: a ReadAPI instance (snapshot semantics — see F-4;
    REQUIRES snapshot_ok=True, else the constructor raises), OR
    api_factory: a zero-arg callable returning a fresh ReadAPI per
    operation (the live-semantics choice; wins when both are given).
    ledger_sink: optional LedgerWriter-shaped object; ledger_context
    supplies {host, lane_id, run_id, brief_id} for emitted events.
    """

    def __init__(self, room_dir, read_api=None, api_factory=None,
                 ledger_sink=None, ledger_context=None,
                 snapshot_ok=False):
        if read_api is None and api_factory is None:
            raise PackError("PackAssembler needs a read_api instance "
                            "or an api_factory")
        # Fix-1 #4 (F-4): the silent single-instance path dies. A
        # live ReadAPI instance is a SNAPSHOT (it cannot observe
        # later edits — see flag F-4), so accepting one requires the
        # explicit opt-in `snapshot_ok=True`; without it the
        # constructor raises. The default live wiring is a factory
        # (a fresh ReadAPI per operation, built by the caller from
        # store paths), which needs no opt-in.
        if read_api is not None and not snapshot_ok:
            raise PackError(
                "PackAssembler: a single ReadAPI instance has "
                "snapshot semantics (serve-time recomputation is "
                "NOT guaranteed — flag F-4); pass api_factory for "
                "live wiring, or pass snapshot_ok=True to opt in "
                "to snapshot mode explicitly")
        self.room_dir = str(room_dir)
        self._api = read_api
        self._api_factory = api_factory
        # Snapshot mode is on the face of every serve output when
        # (and only when) a single instance was opted into and no
        # factory overrides it.
        self._snapshot_mode = bool(
            read_api is not None and api_factory is None)
        self._ledger_sink = ledger_sink
        self._ledger_context = dict(ledger_context or {})
        # Assembly cache: (pack_id, version, source-hash-set) ->
        # {member_key: full_content_text}. A cache hit skips
        # re-serialization ONLY — serve() always re-resolves and
        # re-checks entitlement + freshness first (dossier §1.4).
        self._cache = {}

    # ------------------------------------------------------------ api

    def _fresh_api(self):
        """(api, owned): factory instances are owned (closed after
        use — Windows file-handle discipline, per READ_API.md);
        an injected instance is the caller's and is never closed."""
        if self._api_factory is not None:
            return self._api_factory(), True
        return self._api, False

    @staticmethod
    def _release(api, owned):
        if owned and hasattr(api, "close"):
            api.close()

    def _resolve_all(self, api, members):
        # Fix-1 #7: normalize at the boundary (idempotent) so no
        # caller path can key a resolution by an alias spelling.
        return {(normalize_system(sys_), mid):
                api.resolve(normalize_system(sys_), mid)
                for sys_, mid in members}

    # -------------------------------------------------------- manifest

    @property
    def _manifest_path(self):
        return os.path.join(self.room_dir, MANIFEST_NAME)

    @property
    def _manifest_head_path(self):
        return os.path.join(self.room_dir, MANIFEST_HEAD_NAME)

    def _verify_manifest_head(self, raw_lines, events):
        """Head commitment (Slice-2 sidecar fix, parity with the
        Slice 1 ledger): the prev_hash chain authenticates every
        line EXCEPT the last — nothing pins the tail's bytes. The
        sidecar `manifest.jsonl.head.json`, rewritten atomically by
        _append_manifest after every append, commits to
        {head_hash, line_count, last_event}. Checked AFTER the
        chain, before any event is folded/served:

        - exact match (line_count + head_hash): proceed.
        - exact-prefix sidecar (line_count behind, head_hash ==
          hash of the manifest line at that count, chain valid):
          the crash window between manifest fsync and sidecar
          replace — advance the sidecar to the current head,
          proceed.
        - missing sidecar on a NON-EMPTY manifest: PackError, loud
          (pack.py is the only writer and always writes the
          sidecar — a missing one means tampering or a foreign
          manifest).
        - corrupt sidecar, count-ahead sidecar, or any other
          mismatch: PackError naming expected vs actual; nothing
          proceeds from this manifest.
        Residual (ledger's documented caveat): rewriting the tail
        AND the sidecar consistently defeats this check until a
        gate report anchors head commitments externally."""
        line_count = len(raw_lines)
        head_hash = _sha256_text_bytes(raw_lines[-1]) \
            if raw_lines else GENESIS_HASH
        commitment = _read_manifest_head_sidecar(
            self._manifest_head_path)
        if commitment is None:
            if line_count == 0:
                return  # fresh / empty manifest: nothing committed
            raise PackError(
                f"manifest head commitment missing: manifest "
                f"{self._manifest_path} is non-empty (line_count "
                f"{line_count}, head_hash {head_hash}) but sidecar "
                f"{MANIFEST_HEAD_NAME} does not exist — pack.py is "
                "the only writer and always writes the sidecar, so "
                "a missing sidecar means tampering or a foreign "
                "manifest; refusing to load")
        sc_count = commitment.get("line_count")
        sc_head = commitment.get("head_hash")
        if not isinstance(sc_count, int) \
                or isinstance(sc_count, bool) \
                or not isinstance(sc_head, str):
            raise PackError(
                f"manifest head commitment corrupt/unparseable: "
                f"expected a commitment with integer line_count "
                f"and head_hash, actual sidecar content "
                f"{commitment!r}; actual manifest has line_count "
                f"{line_count}, head_hash {head_hash}; refusing "
                "to load")
        if sc_count == line_count and sc_head == head_hash:
            return  # exact match: proceed
        prefix_head = None
        if sc_count == 0:
            prefix_head = GENESIS_HASH
        elif 0 < sc_count < line_count:
            prefix_head = _sha256_text_bytes(
                raw_lines[sc_count - 1])
        if 0 <= sc_count < line_count and sc_head == prefix_head:
            # Crash window: manifest fsync landed, sidecar replace
            # did not. The sidecar is an exact prefix state of a
            # chain that verified — advance it to the current head.
            _write_manifest_head_sidecar(
                self._manifest_head_path, head_hash, line_count,
                events[-1] if events else None)
            return
        raise PackError(
            f"manifest head commitment mismatch: sidecar expects "
            f"line_count {sc_count}, head_hash {sc_head}; actual "
            f"manifest has line_count {line_count}, head_hash "
            f"{head_hash}; refusing to load — the manifest tail "
            "is not the tail pack.py committed (no serve / resume "
            "/ assemble proceeds from it)")

    def _read_manifest_events(self):
        """Read + VERIFY the manifest (Fix-1 #8 + head sidecar).
        Every line must carry the Slice 1-style running content
        hash: line N's `prev_hash` is the sha256 of line N-1's
        bytes (line 1 chains to GENESIS_HASH). A broken chain
        fails loudly, naming the broken line. After the chain, the
        head-commitment sidecar is verified (see
        _verify_manifest_head) — a tampered manifest, tail
        included, is never folded or served from."""
        if not os.path.exists(self._manifest_path):
            # No manifest: only an anomalous lone sidecar could
            # disagree with the empty state; check it if present.
            self._verify_manifest_head([], [])
            return []
        with open(self._manifest_path, "rb") as f:
            data = f.read()
        if data == b"":
            self._verify_manifest_head([], [])
            return []
        raw_lines = data.split(b"\n")
        if raw_lines and raw_lines[-1] == b"":
            raw_lines.pop()  # final LF terminator, not a line
        events = []
        prev_raw = None
        for i, raw in enumerate(raw_lines):
            lineno = i + 1
            try:
                ev = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise PackError(
                    f"manifest hash chain broken at line {lineno}: "
                    f"line does not parse ({exc})")
            if not isinstance(ev, dict):
                raise PackError(
                    f"manifest hash chain broken at line {lineno}: "
                    "line is not a JSON object")
            expected = GENESIS_HASH if prev_raw is None \
                else _sha256_text_bytes(prev_raw)
            found = ev.get("prev_hash")
            if found != expected:
                raise PackError(
                    f"manifest hash chain broken at line {lineno}: "
                    f"prev_hash mismatch (expected {expected}, "
                    f"found {found!r}) — the manifest has been "
                    "tampered with or corrupted; refusing to load")
            events.append(ev)
            prev_raw = raw
        self._verify_manifest_head(raw_lines, events)
        return events

    def _append_manifest(self, events):
        os.makedirs(self.room_dir, exist_ok=True)
        # Current chain head: sha256 of the last stored line's
        # bytes, or genesis for an empty/absent manifest. (Loads
        # verify the chain before any append path reaches here:
        # assemble/retire fold the manifest first.)
        head = GENESIS_HASH
        line_count = 0
        if os.path.exists(self._manifest_path):
            with open(self._manifest_path, "rb") as f:
                existing = f.read()
            if existing:
                lines = existing.split(b"\n")
                if lines and lines[-1] == b"":
                    lines.pop()
                if lines:
                    head = _sha256_text_bytes(lines[-1])
                    line_count = len(lines)
        if not events:
            return
        with open(self._manifest_path, "ab") as f:
            for ev in events:
                ev["prev_hash"] = head
                line = json.dumps(ev, ensure_ascii=False,
                                  sort_keys=True)
                f.write((line + "\n").encode("utf-8"))
                head = _sha256_text(line)
            f.flush()
            os.fsync(f.fileno())
        # Head commitment (sidecar fix): after EVERY successful
        # manifest append — assemble / supersede / retire events
        # alike — rewrite the sidecar atomically so it commits to
        # the new tail (see _verify_manifest_head).
        line_count += len(events)
        _write_manifest_head_sidecar(
            self._manifest_head_path, head, line_count, events[-1])

    def _fold_manifest(self):
        """{pack_id: {"versions": {n: descriptor}, "latest": n,
        "retired": bool}}. Descriptors carry NO derived level —
        level is a serve-time computation, never stamped (§1.2)."""
        packs = {}
        for ev in self._read_manifest_events():
            pid = ev.get("pack_id")
            if pid is None:
                continue
            slot = packs.setdefault(
                pid, {"versions": {}, "latest": 0, "retired": False})
            if ev.get("event") == "assemble":
                slot["versions"][ev["version"]] = ev
                slot["latest"] = max(slot["latest"], ev["version"])
            elif ev.get("event") == "supersede":
                old = slot["versions"].get(ev.get("version"))
                if old is not None:
                    old["invalid_at"] = ev.get("invalid_at")
                    old["superseded_by"] = ev.get("superseded_by")
            elif ev.get("event") == "retire":
                slot["retired"] = True
        return packs

    def _get_version(self, packs, pack_id, version):
        slot = packs.get(pack_id)
        if slot is None or not slot["versions"]:
            raise PackNotFoundError(f"unknown pack: {pack_id!r}")
        n = slot["latest"] if version is None else version
        desc = slot["versions"].get(n)
        if desc is None:
            raise PackNotFoundError(
                f"pack {pack_id!r} has no version {n}")
        return slot, desc

    # ------------------------------------------------------------ ledger

    def _emit_ledger(self, event):
        if self._ledger_sink is None:
            return
        ctx = self._ledger_context
        ev = {
            "ts": _now_iso(),
            "host": ctx.get("host", "vm"),
            "lane_id": ctx.get("lane_id", "pack-assembler"),
            "run_id": ctx.get("run_id", "pack-run"),
            "consumer": event.pop("consumer", "pack-assembler"),
        }
        if ctx.get("brief_id"):
            ev["brief_id"] = ctx["brief_id"]
        else:
            ev["brief_id"] = None
            ev["unjoined_reason"] = ctx.get(
                "unjoined_reason",
                "pack library event; no codex-cp brief joined")
        ev.update(event)
        self._ledger_sink.append(ev)

    # ---------------------------------------------------------- assemble

    def assemble(self, pack_id, members=None, cabinet_id=None,
                 purpose="", domain="", task_type="", author="",
                 budgets=None, created_at=None):
        """Assemble (or re-assemble) a pack version.

        members: iterable of (system, id) pairs (or {"system","id"}
        dicts). cabinet_id: alternatively, take the member list
        from a cabinet through the read API (kept members plus
        tombstone-posture purged members). budgets: optional
        {"default": {...}, (system, id) or "system:id": {...}} with
        char_budget / token_budget per section.

        Budgets are COUNTED HERE, before assembly completes
        (contract rule 2): each section plan records the full
        counted chars/bytes/tokens, its declared budget, and
        whether the served segment is bounded (truncated).

        Returns the version descriptor. Re-assembling with an
        unchanged manifest (same sources, hashes, budgets,
        purpose) returns the current version without minting;
        any change mints version+1 and supersedes the old one.
        """
        if not pack_id or not isinstance(pack_id, str):
            raise PackError("pack_id must be a non-empty string")
        if not domain or not task_type:
            raise PackError("domain and task_type are required "
                            "(packs are keyed by (domain, task-type))")
        budgets = budgets or {}
        api, owned = self._fresh_api()
        try:
            if cabinet_id is not None:
                cab = api.cabinet(cabinet_id)
                if not cab.get("found"):
                    raise PackError(f"cabinet not found: {cabinet_id!r}")
                member_list = [(normalize_system(m["system"]), m["id"])
                               for m in cab.get("members", [])]
                member_list += [(normalize_system(m["system"]), m["id"])
                                for m in cab.get("purged_members", [])]
            elif members is not None:
                member_list = []
                for m in members:
                    if isinstance(m, dict):
                        member_list.append(
                            (normalize_system(m["system"]), m["id"]))
                    else:
                        sys_, mid = m
                        member_list.append((normalize_system(sys_), mid))
            else:
                raise PackError("assemble needs members or cabinet_id")
            resolved = self._resolve_all(api, member_list)
        finally:
            self._release(api, owned)

        created = created_at or _now_iso()
        sources, plans, cache_texts = [], [], {}
        for sys_, mid in member_list:
            r = resolved[(sys_, mid)]
            chash = content_hash_of(r)
            sources.append({"system": sys_, "id": mid,
                            "anchor": anchor_of(r),
                            "content_hash": chash})
            spec = dict(budgets.get("default") or {})
            spec.update(budgets.get((sys_, mid))
                        or budgets.get(f"{sys_}:{mid}") or {})
            char_budget = int(spec.get("char_budget",
                                       DEFAULT_CHAR_BUDGET))
            token_budget = int(spec.get("token_budget",
                                        DEFAULT_TOKEN_BUDGET))
            plan = {"system": sys_, "id": mid,
                    "char_budget": char_budget,
                    "token_budget": token_budget}
            if r.get("forgotten"):
                plan.update({"posture": "tombstone",
                             "counted_chars": 0, "counted_bytes": 0,
                             "counted_tokens": 0, "truncated": False})
            elif sys_ in POINTER_SYSTEMS:
                plan.update({"posture": "pointer",
                             "counted_chars": 0, "counted_bytes": 0,
                             "counted_tokens": 0, "truncated": False})
            elif r.get("content") is not None:
                text = content_text_of(r["content"])
                cache_texts[f"{sys_}:{mid}"] = text
                try:
                    _seg, _nxt, truncated = _bounded_segment(
                        text, 0, char_budget, token_budget)
                except PackBudgetError as exc:
                    raise PackBudgetError(
                        f"{exc} (section {sys_}:{mid}, "
                        f"char_budget={char_budget}, "
                        f"token_budget={token_budget})") from exc
                plan.update({
                    "posture": "content",
                    "counted_chars": len(text),
                    "counted_bytes": len(text.encode("utf-8")),
                    "counted_tokens": est_tokens(text),
                    "truncated": truncated})
            else:
                plan.update({"posture": "no-content",
                             "counted_chars": 0, "counted_bytes": 0,
                             "counted_tokens": 0, "truncated": False})
            plans.append(plan)

        set_hash = source_hash_set_hash(sources)
        packs = self._fold_manifest()
        slot = packs.get(pack_id)
        if slot and slot["versions"]:
            cur = slot["versions"][slot["latest"]]
            if cur["source_hash_set_hash"] == set_hash \
                    and cur["sections"] == plans \
                    and cur["purpose"] == purpose \
                    and cur["domain"] == domain \
                    and cur["task_type"] == task_type:
                self._cache[(pack_id, cur["version"], set_hash)] = \
                    cache_texts
                return cur
            version = slot["latest"] + 1
            supersede = {"event": "supersede", "pack_id": pack_id,
                         "version": slot["latest"],
                         "invalid_at": created,
                         "superseded_by": version}
        else:
            version = 1
            supersede = None
        desc = {"event": "assemble", "pack_id": pack_id,
                "version": version, "created_at": created,
                "valid_at": created, "invalid_at": None,
                "purpose": purpose, "domain": domain,
                "task_type": task_type, "author": author,
                "sources": sources, "sections": plans,
                "source_hash_set_hash": set_hash}
        self._append_manifest(
            ([supersede] if supersede else []) + [desc])
        self._cache[(pack_id, version, set_hash)] = cache_texts
        self._emit_ledger({
            "event_type": "assemble", "pack_id": pack_id,
            "pack_version": version,
            "requested_key": {"domain": domain,
                              "task_type": task_type},
            "sources_hash_set_hash": set_hash})
        return desc

    def retire(self, pack_id, at=None):
        packs = self._fold_manifest()
        if pack_id not in packs:
            raise PackNotFoundError(f"unknown pack: {pack_id!r}")
        self._append_manifest([{"event": "retire",
                                "pack_id": pack_id,
                                "at": at or _now_iso()}])

    # -------------------------------------------------------------- serve

    def _serve_time_state(self, api, desc):
        """Fresh resolutions + per-source freshness + serve-time
        derived level for one version descriptor. Forgotten members
        never contribute a level (read-API derivation rule)."""
        members = [(s["system"], s["id"]) for s in desc["sources"]]
        resolved = self._resolve_all(api, members)
        freshness, levels = [], {}
        for src in desc["sources"]:
            r = resolved[(src["system"], src["id"])]
            current_hash = content_hash_of(r)
            status = "FRESH" if current_hash == src["content_hash"] \
                else "STALE"
            freshness.append({
                "system": src["system"], "id": src["id"],
                "status": status,
                "content_hash_at_assembly": src["content_hash"],
                "content_hash_current": current_hash})
            if not r.get("forgotten"):
                lvl = r.get("effective_privacy") or "unknown"
                levels[(src["system"], src["id"])] = lvl
        if not levels or "unknown" in levels.values():
            derived = "unknown"
        else:
            derived = max(levels.values(), key=lambda l: _STRICTNESS[l])
        return resolved, freshness, levels, derived

    def serve(self, pack_id, consumer, version=None):
        """Serve one pack version to a consumer (F-2 model).

        EVERY serve re-resolves through the read API and re-checks
        entitlement + freshness, cache hit or not (dossier §1.4).
        Returns the contract-shaped package dict; a whole-serve
        denial is a returned dict with entitlement_result "denied",
        never an exception — the denial is data for the caller.

        Full refusal surface (deliberate asymmetry with resume(),
        adjudicated in the Slice 2 delta re-review): serve()
        reports a RETIRED pack as that denied dict (denial_reason
        "pack-retired", no content), and serves a superseded
        version only when it is explicitly requested by version;
        it raises no RetiredPackError / StaleCursorError. The
        exception shapes live on resume(): RetiredPackError on a
        retired pack, StaleCursorError on a superseded version or
        on source-hash-set drift. A manifest whose chain or head
        commitment fails verification raises PackError here (via
        the fold), before any denial dict is built.
        """
        consumer = _normalize_consumer(consumer)
        packs = self._fold_manifest()
        slot, desc = self._get_version(packs, pack_id, version)
        api, owned = self._fresh_api()
        try:
            resolved, freshness, levels, derived = \
                self._serve_time_state(api, desc)
        finally:
            self._release(api, owned)
        set_hash = desc["source_hash_set_hash"]
        cache_hit = (pack_id, desc["version"], set_hash) in self._cache
        # Fix-1 #2: the header manifest + freshness start FULLY
        # redacted (no member served yet — the denied posture).
        # The successful path below re-publishes hashes ONLY for
        # members actually served in that response.
        header = {"pack_id": pack_id, "version": desc["version"],
                  "created_at": desc["created_at"],
                  "purpose": desc["purpose"],
                  "source_manifest": _public_sources(
                      desc["sources"], set())}
        tombstones = [resolved[(s["system"], s["id"])]
                      for s in desc["sources"]
                      if resolved[(s["system"], s["id"])].get("forgotten")]
        # Tombstone entries are already the read API's purged shape
        # (rule-6 closed set) — carried verbatim, nothing added.
        base = {"pack_id": pack_id, "version": desc["version"],
                "header": header, "served_at": _now_iso(),
                "consumer": consumer["identity"],
                "snapshot_mode": self._snapshot_mode,
                "derived_level": derived,
                "freshness": _public_freshness(freshness, set()),
                "tombstones": tombstones}

        def denied(reason, exclusions, outcome="miss"):
            out = dict(base)
            out.update({
                "status": "denied",
                "entitlement_result": "denied",
                "denial_reason": reason,
                "sections": [], "exclusions": exclusions,
                "footer": self._footer(desc, 0, None, cache_hit)})
            self._emit_ledger({
                "event_type": "serve", "pack_id": pack_id,
                "pack_version": desc["version"],
                "consumer": consumer["identity"],
                "requested_key": {"domain": desc["domain"],
                                  "task_type": desc["task_type"]},
                "outcome": outcome, "derived_level": derived,
                "entitlement_result": "denied",
                "excluded": [{"system": e["system"], "id": e["id"]}
                             for e in exclusions],
                "context_tokens_served": 0,
                "token_counter": TOKEN_ESTIMATOR,
                "estimated_tokens": {"value": 0,
                                     "estimator": TOKEN_ESTIMATOR},
                "sources_hash_set_hash": set_hash})
            return out

        if slot["retired"]:
            return denied("pack-retired", [])
        unknown = [{"system": s["system"], "id": s["id"],
                    "reason": "unknown-privacy-level",
                    "level": "unknown"}
                   for s in desc["sources"]
                   if levels.get((s["system"], s["id"])) == "unknown"]
        if unknown:
            return denied("unknown-member-level: whole serve denied "
                          "(dossier §1.2)", unknown)
        if derived == "unknown":
            # Fix-1 #6: no live members remain (every manifest
            # member is forgotten) — §1.2 invalidates the version;
            # the serve returns the tombstone-only posture and can
            # NEVER report served_full. Invariant: served_full is
            # impossible with derived level unknown.
            return denied("all-members-forgotten: pack version "
                          "invalidated (dossier §1.2) — "
                          "tombstone-only posture", [])

        plans = {(p["system"], p["id"]): p for p in desc["sections"]}
        fresh_by_key = {(f["system"], f["id"]): f["status"]
                        for f in freshness}
        sections, exclusions, offsets = [], [], {}
        served_tokens = 0
        cached_texts = self._cache.get(
            (pack_id, desc["version"], set_hash), {})
        for src in desc["sources"]:
            key = (src["system"], src["id"])
            r = resolved[key]
            if r.get("forgotten"):
                continue  # tombstone posture only (base["tombstones"])
            level = levels[key]
            plan = plans[key]
            if _above(level, consumer["max_level"]):
                exclusions.append({
                    "system": src["system"], "id": src["id"],
                    "reason": "above-consumer-entitlement",
                    "level": level})
                continue
            if src["system"] in POINTER_SYSTEMS:
                sections.append({
                    "system": src["system"], "id": src["id"],
                    "section_type": "pointer", "level": level,
                    "anchor": src["anchor"],
                    "structure": {
                        "kind": r.get("kind"),
                        "namespace": r.get("namespace"),
                        "cabinets": [c["cabinet_id"]
                                     for c in r.get("cabinets", [])]},
                    "budget": {"char_budget": plan["char_budget"],
                               "token_budget": plan["token_budget"]},
                    "body": None})
                continue
            if fresh_by_key[key] == "STALE":
                # Contract rule 7: stale content is never presented
                # as current — the section is excluded and named.
                exclusions.append({
                    "system": src["system"], "id": src["id"],
                    "reason": "STALE: source changed since assembly",
                    "level": level})
                continue
            if r.get("content") is None:
                exclusions.append({
                    "system": src["system"], "id": src["id"],
                    "reason": r.get("content_excluded")
                    or r.get("content_note")
                    or "no-content",
                    "level": level})
                continue
            # Fix-1 #5: the body is ALWAYS re-serialized from the
            # fresh serve-time resolution — never copied from the
            # cached assembly body. The hash excludes `privacy`, so
            # a cached body could carry a stale privacy field while
            # the section is (correctly) labelled FRESH with the
            # new serve-time level. Cache membership still drives
            # the footer's hit/miss label; it no longer supplies
            # body text. (cached_texts is retained for that label
            # bookkeeping via self._cache presence, not content.)
            _ = cached_texts
            text = content_text_of(r["content"])
            segment, next_off, truncated = _bounded_segment(
                text, 0, plan["char_budget"], plan["token_budget"])
            if next_off is not None:
                offsets[f"{src['system']}:{src['id']}"] = next_off
            served_tokens += est_tokens(segment)
            sections.append({
                "system": src["system"], "id": src["id"],
                "section_type": "content", "level": level,
                "anchor": src["anchor"],
                "budget": {"char_budget": plan["char_budget"],
                           "token_budget": plan["token_budget"]},
                "counted": {"chars": plan["counted_chars"],
                            "bytes": plan["counted_bytes"],
                            "tokens": plan["counted_tokens"]},
                "served": {"chars": len(segment),
                           "bytes": len(segment.encode("utf-8")),
                           "tokens": est_tokens(segment)},
                "truncated": truncated,
                "freshness": "FRESH",
                "body": segment})
        cursor = None
        if offsets:
            cursor = _encode_cursor({
                "pack_id": pack_id, "version": desc["version"],
                "sources_hash_set_hash": set_hash,
                "offsets": offsets})
        # Fix-1 #2: publish hashes ONLY for members whose content
        # is served in THIS response (served content sections).
        served_keys = {(s["system"], s["id"]) for s in sections
                       if s["section_type"] == "content"}
        # Fix-1 #6 invariant: served_full is impossible when the
        # derived level is unknown (that posture is denied above).
        assert not (not exclusions and derived == "unknown"), \
            "served_full with derived level unknown"
        out = dict(base)
        out["header"] = dict(header)
        out["header"]["source_manifest"] = _public_sources(
            desc["sources"], served_keys)
        out["freshness"] = _public_freshness(freshness, served_keys)
        out.update({
            "status": "partial" if (offsets or exclusions) else "served",
            "entitlement_result": "served_with_exclusions"
            if exclusions else "served_full",
            "sections": sections, "exclusions": exclusions,
            "footer": self._footer(desc, served_tokens, cursor,
                                   cache_hit)})
        self._emit_ledger({
            "event_type": "serve", "pack_id": pack_id,
            "pack_version": desc["version"],
            "consumer": consumer["identity"],
            "requested_key": {"domain": desc["domain"],
                              "task_type": desc["task_type"]},
            "outcome": "partial" if offsets else (
                "cache_hit" if cache_hit else "hit"),
            "derived_level": derived,
            "entitlement_result": out["entitlement_result"],
            **({"excluded": [{"system": e["system"], "id": e["id"]}
                             for e in exclusions]} if exclusions
               else {}),
            "context_tokens_served": served_tokens,
            "token_counter": TOKEN_ESTIMATOR,
            "estimated_tokens": {"value": served_tokens,
                                 "estimator": TOKEN_ESTIMATOR},
            "sources_hash_set_hash": set_hash})
        return out

    @staticmethod
    def _footer(desc, served_tokens, cursor, cache_hit):
        """Contract footer: usage accounting (rule 4: reported and
        estimated kept separate, never summed — no provider meter
        exists at this layer, so reported is explicitly null) plus
        the continuation cursor (rule 5)."""
        return {
            "usage": {
                "context_tokens_served": served_tokens,
                "token_counter": TOKEN_ESTIMATOR,
                "reported_tokens": None,
                "estimated_tokens": {"value": served_tokens,
                                     "estimator": TOKEN_ESTIMATOR}},
            "continuation_cursor": cursor,
            "cache": "hit" if cache_hit else "miss",
            "sources_hash_set_hash": desc["source_hash_set_hash"]}

    # ------------------------------------------------------------- resume

    def resume(self, cursor, consumer):
        """Continue truncated sections from a footer cursor.

        The cursor is bound to its pack version's source-hash set:
        if ANY source's current content_hash differs, the resume
        fails loudly as STALE (StaleCursorError) and serves nothing
        (contract rule 5). Entitlement is re-checked exactly as in
        serve() — a member that has become `unknown` denies, a
        member now above the consumer is excluded by name.

        Full refusal surface (exceptions, never a denied dict —
        the deliberate asymmetry with serve()'s denied-dict
        posture, adjudicated in the Slice 2 delta re-review; every
        failure serves zero content):
        - RetiredPackError: the pack has been retired (checked
          first, before the supersede / drift checks).
        - StaleCursorError: the cursor's version has been
          superseded (no longer the latest version, or invalid_at
          set) — even when its source-hash set is unchanged.
        - StaleCursorError: hash-set drift — the cursor's
          sources_hash_set_hash differs from the version
          descriptor's set hash, or any source's current
          content_hash differs from the set the cursor was issued
          against.
        - PackError: malformed cursor, unknown pack/version, or a
          manifest whose chain or head commitment fails
          verification.
        """
        consumer = _normalize_consumer(consumer)
        payload = _decode_cursor(cursor)
        packs = self._fold_manifest()
        slot, desc = self._get_version(
            packs, payload["pack_id"], payload["version"])
        api, owned = self._fresh_api()
        try:
            resolved, freshness, levels, derived = \
                self._serve_time_state(api, desc)
        finally:
            self._release(api, owned)
        # Fix-1 #1 + coordinator ruling (dossier §1.3): a cursor is
        # honoured ONLY for the exact (pack_id, version,
        # source-hash-set) it was issued against AND only while
        # that version is live. Retired pack ⇒ resume refused
        # (RETIRED, no content), symmetric with serve().
        if slot["retired"]:
            raise RetiredPackError(
                f"RETIRED: pack {payload['pack_id']!r} is retired; "
                "resume refused and no content served (dossier "
                "§1.3: on retire, pack serves stop — a resume is "
                "a serve)")
        # Superseded version ⇒ resume fails STALE, even when the
        # source-hash set is unchanged.
        if desc["version"] != slot["latest"] \
                or desc.get("invalid_at") is not None:
            raise StaleCursorError(
                "STALE: continuation cursor was issued against "
                f"pack {payload['pack_id']!r} version "
                f"{desc['version']}, which has been superseded by "
                f"version {slot['latest']}; a cursor is honoured "
                "only while its version is live (dossier §1.3) — "
                "re-request the pack instead of resuming")
        if payload["sources_hash_set_hash"] \
                != desc["source_hash_set_hash"]:
            raise StaleCursorError(
                "STALE: continuation cursor was issued against "
                f"source revision "
                f"{payload['sources_hash_set_hash']} but pack "
                f"{payload['pack_id']!r} version {desc['version']} "
                f"is bound to {desc['source_hash_set_hash']} — "
                "re-request the pack instead of resuming")
        current_set_hash = source_hash_set_hash([
            {"system": f["system"], "id": f["id"],
             "content_hash": f["content_hash_current"]}
            for f in freshness])
        if current_set_hash != payload["sources_hash_set_hash"]:
            changed = [f"{f['system']}:{f['id']}" for f in freshness
                       if f["status"] == "STALE"]
            self._emit_ledger({
                "event_type": "resume",
                "pack_id": payload["pack_id"],
                "pack_version": desc["version"],
                "consumer": consumer["identity"],
                "requested_key": {"domain": desc["domain"],
                                  "task_type": desc["task_type"]},
                "outcome": "stale_rejected",
                "derived_level": derived,
                "sources_hash_set_hash": current_set_hash})
            raise StaleCursorError(
                "STALE: continuation cursor was issued against "
                f"source revision {payload['sources_hash_set_hash']}"
                f" but the current source-hash set is "
                f"{current_set_hash}; changed source(s): "
                f"{', '.join(changed) or 'unknown'} — re-request "
                "the pack instead of resuming")
        plans = {(p["system"], p["id"]): p for p in desc["sections"]}
        sections, exclusions, new_offsets = [], [], {}
        served_tokens = 0
        for key, offset in sorted(payload["offsets"].items()):
            sys_, _, mid = key.partition(":")
            # Native IDs may themselves contain ':' — the offsets
            # key was built as f"{system}:{id}" and system names
            # contain no ':', so the first ':' is the separator.
            r = resolved.get((sys_, mid))
            if r is None or r.get("forgotten"):
                exclusions.append({"system": sys_, "id": mid,
                                   "reason": "forgotten-tombstone"})
                continue
            level = levels.get((sys_, mid), "unknown")
            if level == "unknown":
                exclusions.append({"system": sys_, "id": mid,
                                   "reason": "unknown-privacy-level",
                                   "level": "unknown"})
                continue
            if _above(level, consumer["max_level"]):
                exclusions.append({
                    "system": sys_, "id": mid,
                    "reason": "above-consumer-entitlement",
                    "level": level})
                continue
            if r.get("content") is None:
                exclusions.append({"system": sys_, "id": mid,
                                   "reason": "no-content"})
                continue
            plan = plans[(sys_, mid)]
            text = content_text_of(r["content"])
            segment, next_off, truncated = _bounded_segment(
                text, offset, plan["char_budget"],
                plan["token_budget"])
            if next_off is not None:
                new_offsets[key] = next_off
            served_tokens += est_tokens(segment)
            sections.append({
                "system": sys_, "id": mid,
                "section_type": "content", "level": level,
                "budget": {"char_budget": plan["char_budget"],
                           "token_budget": plan["token_budget"]},
                "served": {"chars": len(segment),
                           "bytes": len(segment.encode("utf-8")),
                           "tokens": est_tokens(segment)},
                "truncated": truncated, "body": segment})
        new_cursor = None
        if new_offsets:
            new_cursor = _encode_cursor({
                "pack_id": payload["pack_id"],
                "version": desc["version"],
                "sources_hash_set_hash":
                    payload["sources_hash_set_hash"],
                "offsets": new_offsets})
        # Fix-1 #3: a resume must ALWAYS advance. If it cannot
        # deliver new content within budget it fails loudly —
        # never return a cursor identical to the one consumed, and
        # never report success while delivering nothing new for
        # every requested offset.
        if new_cursor is not None and (
                new_cursor == cursor or new_offsets == {
                    k: payload["offsets"][k] for k in new_offsets}):
            raise PackBudgetError(
                "PackBudgetError: resume could not advance any "
                "offset within the section budgets; refusing to "
                "return a non-advancing cursor")
        if new_offsets and not sections:
            raise PackBudgetError(
                "PackBudgetError: resume delivered no new content "
                "within the section budgets; failing loudly instead "
                "of minting a continuation cursor")
        # Fix-1 #2 (resume is a serve): hashes only for members
        # served in this response.
        served_keys = {(s["system"], s["id"]) for s in sections
                       if s["section_type"] == "content"}
        out = {"pack_id": payload["pack_id"],
               "version": desc["version"],
               "consumer": consumer["identity"],
               "snapshot_mode": self._snapshot_mode,
               "derived_level": derived,
               "status": "partial" if new_offsets else "served",
               "entitlement_result": "served_with_exclusions"
               if exclusions else "served_full",
               "sections": sections, "exclusions": exclusions,
               "freshness": _public_freshness(freshness, served_keys),
               "footer": self._footer(desc, served_tokens, new_cursor,
                                      False)}
        self._emit_ledger({
            "event_type": "resume", "pack_id": payload["pack_id"],
            "pack_version": desc["version"],
            "consumer": consumer["identity"],
            "requested_key": {"domain": desc["domain"],
                              "task_type": desc["task_type"]},
            "outcome": "partial" if new_offsets else "hit",
            "derived_level": derived,
            "entitlement_result": out["entitlement_result"],
            **({"excluded": [{"system": e["system"], "id": e["id"]}
                             for e in exclusions]} if exclusions
               else {}),
            "context_tokens_served": served_tokens,
            "token_counter": TOKEN_ESTIMATOR,
            "estimated_tokens": {"value": served_tokens,
                                 "estimator": TOKEN_ESTIMATOR},
            "sources_hash_set_hash":
                payload["sources_hash_set_hash"]})
        return out
