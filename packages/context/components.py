#!/usr/bin/env python3
"""Component consolidation behind adapters — Phase 4, Slice 3.

One adapter interface over the four components named in the Phase 4
dossier §5 Slice 3 + §4.3 LQ3 (wrap first; no rewrites), characterized
in `pai-repo-program/phase4/SLICE3_RECON.md`:

  1. Chief context-economy (HOME, generation-pinned): the FROZEN
     generation's `context-capsule.js` + `cursor-continuity.js`, and
     the CURRENT generation's `tool-result-reducer.js` +
     `typed-outward-contracts.js`. The two reducers carry one JS name
     (`reduceToolResult`) with incompatible signatures, so the
     adapter exposes them under DISTINCT names: `reduce_envelope`
     (frozen envelope) vs `reduce_receipt` (current structured
     receipt). `context-budget-ledger.js` is deliberately NOT wrapped
     as a usage source (recon §1.6: caller-supplied telemetry ring,
     no provider tokens, no estimator).
  2. Resident packet compiler (HOME r27
     `compile-executor-context-packet-r16.cjs` — there is NO MSI
     deployment; recon §2.1 corrected the dossier's attribution).
  3. home-cp bounded readers (HOME `C:\\temp\\home-cp\\pai-terminal`:
     `result-reader.mjs` + `bridge.mjs` `bounded()`).
  4. Retrieval snippet assembly (this repo's `packages/retrieval`:
     `make_snippet` / `run_query`).

Every adapter honours the context-package contract
(`contracts/context-package.md`) at its own boundary:

  (a) the declared budget is validated and the input counted BEFORE
      the component is invoked (rule 2);
  (b) the component is invoked only through a pluggable transport;
  (c) the output is post-checked against the declared budget — an
      over-budget component output raises `AdapterBudgetError`
      loudly. The adapter NEVER truncates silently (recon §7 global
      invariant; contract rule 3);
  (d) continuation cursors are opaque tokens bound to the
      component's revision evidence (content hash / bundle hash /
      page sha256 / source fingerprint); resuming against changed
      evidence raises `StaleCursorError` whose message carries the
      loud STALE marker (rule 5).

Transports:
  - `FixtureTransport` — replays the captured golden fixtures in
    `tests/fixtures/` (deterministic, offline; what the test suite
    uses). The Chief cursor discipline and the home-cp paging
    semantics are re-implemented faithfully inside it (the cursor
    bundleHash is sha256-deterministic and reproduces exactly).
  - `InProcessRetrievalTransport` — calls the repo's own retrieval
    package in-process.
  - `LiveNodeTransport` — SSH + node base64-bootstrap against HOME
    (recon §6 pattern, one SSH call per invocation). Used for live
    reproduction evidence only; tests must NOT require the network
    (live tests are guarded by `PAI_SLICE3_LIVE=1`, skipped by
    default).

Characterization is read-only against HOME: the live transport only
ever invokes pure functions; nothing here reconfigures, restarts, or
replaces a deployment, and nothing writes to the claim register, the
Registrar, or any production store.

Residual-scope decisions (recon §5 item 3): `material-delta.js`
(QA copy only) and `seed-kit-r8/task-readback.js` were read by the
builder lane and are EXCLUDED from the adapter surface — see
SLICE3_BUILD_NOTES.md for the reasons.

Stdlib only; Python 3.11+.
"""
import base64
import copy
import hashlib
import json
import os
import subprocess
import sys

# ---------------------------------------------------------------- errors


class AdapterError(Exception):
    """Base adapter failure. `.code` carries the component's own
    error code when the failure came from a component, so loud
    component errors survive the adapter boundary unsoftened."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class AdapterBudgetError(AdapterError):
    """A declared budget was invalid, or a component output exceeded
    its declared budget. Raised loudly — never a silent truncation."""


class StaleCursorError(AdapterError):
    """A continuation cursor was resumed against changed revision
    evidence. The message always carries the STALE marker
    (contract rule 5)."""


class ComponentError(AdapterError):
    """The wrapped component itself failed loudly (its code and
    message are preserved verbatim)."""


# ---------------------------------------------------------------- helpers


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _js_json(obj):
    """JSON.stringify equivalent for the flat shapes hashed here:
    insertion order preserved, compact separators, no ASCII escape."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def codepoints(value):
    """Unicode code points of a string — the capsule's unit
    (`[...str].length` in JS == len(str) in Python)."""
    if not isinstance(value, str):
        value = _js_json(value)
    return len(value)


def utf8_bytes(value):
    if isinstance(value, bytes):
        return len(value)
    if not isinstance(value, str):
        value = _js_json(value)
    return len(value.encode("utf-8"))


def _require_budget(name, value):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AdapterBudgetError(
            f"declared budget {name} must be a positive integer, "
            f"got {value!r} — a budget must be declared before load "
            "(contract rule 2)")
    return value


# ---------------------------------------------------------------- cursors
# Adapter-level continuation cursors: opaque tokens bound to revision
# evidence, borrowing CursorContinuity's fail-loud hash discipline
# (recon §1.5/§1.7). The evidence is hashed into the token; resume
# re-hashes the CURRENT evidence and fails STALE on any mismatch.

def revision_of(evidence):
    """Stable revision hash of cursor evidence (a string is hashed
    as text; anything else as canonical JSON)."""
    if isinstance(evidence, str):
        return _sha256_text(evidence)
    return _sha256_text(_canonical(evidence))


def issue_cursor(component, evidence, position):
    payload = {"component": component,
               "revision": revision_of(evidence),
               "position": position}
    raw = _canonical(payload).encode("utf-8")
    return "cur_" + base64.urlsafe_b64encode(raw).decode("ascii")


def check_cursor(cursor, component, current_evidence):
    """Verify a cursor against current evidence; returns the payload.

    Raises StaleCursorError (message carries STALE) when the revision
    evidence changed, and AdapterError for malformed/foreign tokens."""
    if not isinstance(cursor, str) or not cursor.startswith("cur_"):
        raise AdapterError("malformed continuation cursor")
    try:
        payload = json.loads(base64.urlsafe_b64decode(
            cursor[4:].encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — reported, not hidden
        raise AdapterError(f"malformed continuation cursor: {exc}")
    if not isinstance(payload, dict) or payload.get("component") != component:
        raise AdapterError(
            f"continuation cursor was not issued for {component!r}")
    current = revision_of(current_evidence)
    if payload.get("revision") != current:
        raise StaleCursorError(
            f"STALE: {component} continuation cursor was issued "
            f"against revision {payload.get('revision')} but the "
            f"current revision evidence hashes to {current} — "
            "re-request instead of resuming")
    return payload


# ---------------------------------------------------------------- transports


class Transport:
    """Pluggable component transport: invoke(component, operation,
    payload) -> result. Component failures raise ComponentError with
    the component's own code/message."""

    def invoke(self, component, operation, payload):
        raise NotImplementedError


class CallableTransport(Transport):
    """Transport backed by a plain callable — the stub seam the
    adapter-behaviour tests use (e.g. a stub returning oversized
    output, or one raising a component change error)."""

    def __init__(self, fn):
        self._fn = fn

    def invoke(self, component, operation, payload):
        return self._fn(component, operation, payload)


# --- Fixture replay -------------------------------------------------

# Frozen-generation capsule PROTECTED field list (recon §1.3).
_CAPSULE_PROTECTED = (
    "authority", "truth_refs", "expected_revision", "fence",
    "read_scope", "write_scope", "capabilities", "data_mode",
    "effect_mode", "privacy_class", "acceptance", "stop_gates",
    "output_contract", "expiry")


class _PyCursorContinuity:
    """Faithful Python port of the frozen generation's
    CursorContinuity (recon §1.5). The bundleHash discipline is
    sha256 over JSON.stringify({threadRef, previousBundleHash,
    cursor, events}) — verified to reproduce the golden fixture's
    bundleHash 39f8c42b…4956d1 exactly."""

    def __init__(self):
        self._threads = {}
        self._replays = {}

    @staticmethod
    def _hash(value):
        return hashlib.sha256(_js_json(value).encode("utf-8")).hexdigest()

    def _state(self, thread_ref):
        return self._threads.get(
            thread_ref, {"cursor": 0, "bundleHash": None, "events": []})

    def commit(self, inp):
        if not inp or not inp.get("threadRef"):
            raise ComponentError("THREAD_REQUIRED", code="THREAD_REQUIRED")
        if not inp.get("events"):
            raise ComponentError("EVENTS_REQUIRED", code="EVENTS_REQUIRED")
        if not inp.get("idempotencyKey"):
            raise ComponentError("IDEMPOTENCY_KEY_REQUIRED",
                                 code="IDEMPOTENCY_KEY_REQUIRED")
        replay_key = f"{inp['threadRef']}:{inp['idempotencyKey']}"
        fingerprint = self._hash(inp)
        if replay_key in self._replays:
            prior = self._replays[replay_key]
            if prior["fingerprint"] != fingerprint:
                raise ComponentError("IDEMPOTENCY_CONFLICT",
                                     code="IDEMPOTENCY_CONFLICT")
            return prior["receipt"]
        current = self._state(inp["threadRef"])
        if inp.get("fromCursor") != current["cursor"]:
            raise ComponentError("CURSOR_GAP", code="CURSOR_GAP")
        if (inp.get("previousBundleHash") or None) != current["bundleHash"]:
            raise ComponentError("PRIOR_HASH_MISMATCH",
                                 code="PRIOR_HASH_MISMATCH")
        for index, event in enumerate(inp["events"]):
            if event.get("threadRef") != inp["threadRef"]:
                raise ComponentError("WRONG_THREAD", code="WRONG_THREAD")
            if event.get("sequence") != current["cursor"] + index + 1:
                raise ComponentError("NON_CONTIGUOUS_SEQUENCE",
                                     code="NON_CONTIGUOUS_SEQUENCE")
            if event.get("role") != "user":
                raise ComponentError("ROLE_INVALID", code="ROLE_INVALID")
        events = current["events"] + [dict(e) for e in inp["events"]]
        cursor = current["cursor"] + len(inp["events"])
        bundle_hash = self._hash({
            "threadRef": inp["threadRef"],
            "previousBundleHash": current["bundleHash"],
            "cursor": cursor, "events": inp["events"]})
        receipt = {"schema": "prompt-range-commit/v1",
                   "threadRef": inp["threadRef"],
                   "fromCursor": current["cursor"], "toCursor": cursor,
                   "eventCount": len(inp["events"]),
                   "previousBundleHash": current["bundleHash"],
                   "bundleHash": bundle_hash}
        self._threads[inp["threadRef"]] = {
            "cursor": cursor, "bundleHash": bundle_hash, "events": events}
        self._replays[replay_key] = {
            "fingerprint": fingerprint, "receipt": receipt}
        return receipt

    def compact(self, thread_ref, keep=32):
        current = self._state(thread_ref)
        retained = current["events"][-keep:] if keep else []
        return {"threadRef": thread_ref, "cursor": current["cursor"],
                "bundleHash": current["bundleHash"], "retained": retained}


class FixtureTransport(Transport):
    """Deterministic offline replay of the golden fixtures captured
    in recon §6 (copied into tests/fixtures/, except the real home-cp
    receipt fixture — the synthetic content-free variant is used, per
    recon §6.3 hygiene).

    Matching discipline: Chief capsule / reducers replay only on a
    deep-equal match with the fixture's recorded input, so a fixture
    can never silently answer a different question. The cursor and
    home-cp paging semantics are stateful faithful ports (above /
    below), not recordings. The Resident compiler replays on the
    fixture inputs' identity (TASK_ID + body size + body hash for the
    heavy artifact, whose body the recon recorded by size + packet
    hash; the builder reconstructed it and verified its sha256
    against the packet's INPUT_SHA256)."""

    def __init__(self, fixtures_dir):
        self.fixtures_dir = str(fixtures_dir)
        self._fx = {}
        for name in os.listdir(self.fixtures_dir):
            if name.endswith(".json"):
                with open(os.path.join(self.fixtures_dir, name),
                          encoding="utf-8") as f:
                    self._fx[name[:-5]] = json.load(f)
        self._cursor = _PyCursorContinuity()
        syn = self._fx["home-cp-readers-synthetic"]
        self._synthetic_content = base64.b64decode(
            syn["syntheticContentBase64"])
        self._synthetic_ref = syn["usedResultRefRelative"]

    # test seam: simulate the underlying home-cp file changing
    def replace_synthetic_content(self, content_bytes):
        self._synthetic_content = bytes(content_bytes)

    def _fixture(self, name):
        if name not in self._fx:
            raise ComponentError(f"no fixture recorded for {name}",
                                 code="FIXTURE_NOT_FOUND")
        return self._fx[name]

    def invoke(self, component, operation, payload):
        handler = getattr(self, f"_do_{component}_{operation}", None)
        if handler is None:
            raise ComponentError(
                f"FixtureTransport has no replay for "
                f"{component}.{operation}", code="FIXTURE_NOT_FOUND")
        return handler(payload)

    # -- Chief ------------------------------------------------------
    def _do_chief_capsule(self, payload):
        for name in ("chief-capsule-ready", "chief-capsule-context-miss"):
            fx = self._fixture(name)
            if payload.get("input") == fx["input"]:
                return copy.deepcopy(fx["output"])
        raise ComponentError("no capsule fixture for this input",
                             code="FIXTURE_NOT_FOUND")

    def _do_chief_cursor_commit(self, payload):
        return self._cursor.commit(payload["input"])

    def _do_chief_cursor_compact(self, payload):
        return self._cursor.compact(payload["threadRef"],
                                    payload.get("keep", 32))

    def _do_chief_cursor_sequence(self, payload):
        """The recon §6.1 capture sequence, run against the port."""
        cc = _PyCursorContinuity()
        base = {"threadRef": "t-fix",
                "events": [{"threadRef": "t-fix", "sequence": 1,
                            "role": "user", "text": "hello"}]}
        commit1 = cc.commit({**base, "fromCursor": 0,
                             "previousBundleHash": None,
                             "idempotencyKey": "fixture-1"})
        out = {"commit1": commit1}
        try:
            cc.commit({"threadRef": "t-fix", "fromCursor": 0,
                       "previousBundleHash": commit1["bundleHash"],
                       "idempotencyKey": "fixture-2",
                       "events": [{"threadRef": "t-fix", "sequence": 2,
                                   "role": "user", "text": "again"}]})
            out["gapError"] = None
        except ComponentError as exc:
            out["gapError"] = exc.code
        try:
            cc.commit({"threadRef": "t-fix", "fromCursor": 1,
                       "previousBundleHash": "0" * 64,
                       "idempotencyKey": "fixture-3",
                       "events": [{"threadRef": "t-fix", "sequence": 2,
                                   "role": "user", "text": "again"}]})
            out["hashError"] = None
        except ComponentError as exc:
            out["hashError"] = exc.code
        out["compact"] = cc.compact("t-fix", 32)
        return out

    def _do_chief_reduce_envelope(self, payload):
        fx = self._fixture("chief-reducer-frozen-envelope")
        if payload.get("input") == fx["input"] \
                and payload.get("options") == fx["options"]:
            return copy.deepcopy(fx["output"])
        raise ComponentError("no frozen-envelope fixture for this input",
                             code="FIXTURE_NOT_FOUND")

    def _do_chief_reduce_receipt(self, payload):
        fx = self._fixture("chief-reducer-current")
        if payload.get("input") == fx["input"]:
            return copy.deepcopy(fx["output"])
        raise ComponentError("no current-receipt fixture for this input",
                             code="FIXTURE_NOT_FOUND")

    def _do_chief_paginate(self, payload):
        fx = self._fixture("chief-reducer-current")["paginate"]
        if payload.get("items") == list(range(1, 11)) \
                and payload.get("page") == fx["page"] \
                and payload.get("pageSize") == fx["page_size"]:
            return copy.deepcopy(fx)
        raise ComponentError("no paginate fixture for this input",
                             code="FIXTURE_NOT_FOUND")

    def _do_chief_typed_outward(self, payload):
        fx = self._fixture("chief-typed-outward")
        case = payload.get("case")
        if case == "fetch":
            out = copy.deepcopy(fx["fetch"]["output"])
            text = (payload.get("result") or {}).get("text", "")
            out["text"] = text[:out["textLen"]]
            return out
        if case == "terminal":
            return copy.deepcopy(fx["terminal"]["output"])
        raise ComponentError(f"no typed-outward fixture for {case!r}",
                             code="FIXTURE_NOT_FOUND")

    # -- Resident ---------------------------------------------------
    def _do_resident_compile(self, payload):
        fx = self._fixture("resident-packet-compiler")
        art = payload.get("artifact") or {}
        header = art.get("header") or {}
        body = art.get("body") or art.get("task") or ""
        task_id = header.get("TASK_ID")
        if task_id == "FIX-SMALL" and body == fx["inputs"]["small"]["body"]:
            return copy.deepcopy(fx["output"]["small"])
        if task_id == "FIX-HEAVY" \
                and len(body) == fx["inputs"]["heavyBodyChars"] \
                and _sha256_text(body) == fx["output"]["heavy"]["inputSha256"]:
            return copy.deepcopy(fx["output"]["heavy"])
        if len(body) >= fx["inputs"]["fuseBodyChars"] - 22:
            err = fx["output"]["fuse"]
            raise ComponentError(err["error"], code=err["code"])
        raise ComponentError("no resident fixture for this artifact",
                             code="FIXTURE_NOT_FOUND")

    def _do_resident_fidelity(self, payload):
        compiled = payload.get("compiled") or {}
        return {"ok": True, "missing": [],
                "expected_fields_count": None, "matched_fields_count": None,
                "protected_semantic_field_fidelity":
                    compiled.get("protected_semantic_field_fidelity")}

    def _do_resident_bounded_artifact(self, payload):
        fx = self._fixture("resident-packet-compiler")
        return {"tail": fx["output"]["boundedArtifact"]}

    # -- home-cp ----------------------------------------------------
    def _do_home_cp_validate(self, payload):
        """Mirror of result-reader.mjs validateResultRead."""
        request = payload.get("request") or {}
        if "idempotency_key" in request and \
                request["idempotency_key"] is not None:
            raise ComponentError("HOME_CP_READ_REQUIRES_FRESH_UNKEYED_REQUEST",
                                 code="HOME_CP_READ_REQUIRES_FRESH_UNKEYED_REQUEST")
        p = request.get("params")
        if not isinstance(p, dict) \
                or any(k not in ("result_ref", "cursor", "max_bytes")
                       for k in p) \
                or not isinstance(p.get("result_ref"), str):
            raise ComponentError("HOME_CP_RESULT_READ_SCHEMA",
                                 code="HOME_CP_RESULT_READ_SCHEMA")
        cursor = p.get("cursor", 0)
        max_bytes = p.get("max_bytes", 768)
        for key, value, lo in (("cursor", cursor, 0),
                               ("max_bytes", max_bytes, 1)):
            if not isinstance(value, int) or isinstance(value, bool) \
                    or value < lo or (key == "max_bytes" and value > 3072):
                raise ComponentError("HOME_CP_RESULT_RANGE",
                                     code="HOME_CP_RESULT_RANGE")
        return {"action": "result.read",
                "params": {"result_ref": p["result_ref"],
                           "cursor": cursor, "max_bytes": max_bytes}}

    def _do_home_cp_read_page(self, payload):
        """Mirror of result-reader.mjs readResultPage over the staged
        synthetic content (scope/link checks are properties of the
        real deployment's filesystem and are not replayed)."""
        validated = self._do_home_cp_validate({"request": {
            "action": "result.read",
            "params": {"result_ref": payload["result_ref"],
                       "cursor": payload.get("cursor", 0),
                       "max_bytes": payload.get("max_bytes", 768)}}})
        p = validated["params"]
        content = self._synthetic_content
        if p["cursor"] > len(content):
            raise ComponentError("HOME_CP_RESULT_BUDGET",
                                 code="HOME_CP_RESULT_BUDGET")
        page = content[p["cursor"]:p["cursor"] + p["max_bytes"]]
        return {"result_ref": payload["result_ref"], "cursor": p["cursor"],
                "next_cursor": p["cursor"] + len(page), "bytes": len(page),
                "total_bytes": len(content), "encoding": "base64",
                "content": base64.b64encode(page).decode("ascii"),
                "sha256": _sha256_bytes(content),
                "has_more": p["cursor"] + len(page) < len(content)}

    def _do_home_cp_bounded(self, payload):
        fx = self._fixture("home-cp-readers-synthetic")["bounded"]
        return copy.deepcopy(fx)


# --- In-process retrieval transport -----------------------------------

class InProcessRetrievalTransport(Transport):
    """Calls this repo's own `packages/retrieval` in-process (stdlib
    import; the package is never modified — Slice 3 wraps it)."""

    def __init__(self, retrieval_dir=None):
        if retrieval_dir is None:
            retrieval_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "retrieval")
        self.retrieval_dir = os.path.abspath(retrieval_dir)
        if self.retrieval_dir not in sys.path:
            sys.path.insert(0, self.retrieval_dir)
        import retrieval_query  # noqa: E402 — sibling package import
        self._q = retrieval_query

    def invoke(self, component, operation, payload):
        if component != "retrieval":
            raise ComponentError(
                f"InProcessRetrievalTransport only serves 'retrieval', "
                f"got {component!r}", code="TRANSPORT_MISMATCH")
        handler = getattr(self, f"_do_{operation}", None)
        if handler is None:
            raise ComponentError(f"no retrieval operation {operation!r}",
                                 code="FIXTURE_NOT_FOUND")
        return handler(payload)

    def _do_tokenize(self, payload):
        return {"tokens": self._q.tokenize(payload["text"])}

    def _do_make_snippet(self, payload):
        snippet = self._q.make_snippet(
            payload["text"], payload["qtokens"], payload["cap"])
        return {"snippet": snippet,
                "est_tokens": self._q.est_tokens(snippet)}

    def _do_snippet_detail(self, payload):
        """The snippet PLUS the unit indices make_snippet selected,
        derived with the package's own internals (_units /
        _term_weights / _best_window, same selection algorithm) so
        the adapter can issue a continuation cursor over the units
        NOT yet served."""
        text, qtokens, cap = payload["text"], payload["qtokens"], payload["cap"]
        q = self._q
        snippet = q.make_snippet(text, qtokens, cap)
        units = q._units(text)
        chosen = []
        if qtokens:
            qset = set(qtokens)
            weights = q._term_weights(units, qtokens)
            candidates = []
            for idx, unit in enumerate(units):
                win, score, distinct = q._best_window(unit, qset, weights, cap)
                if win is not None and distinct:
                    candidates.append((score, distinct, idx, win))
            candidates.sort(key=lambda x: (-x[0], -x[1], x[2]))
            picked, used = [], 0
            for _s, _d, idx, win in candidates:
                add = len(win) + (3 if picked else 0)
                if picked and used + add > cap:
                    continue
                picked.append((idx, win))
                used += add
                if used >= cap:
                    break
            chosen = sorted(idx for idx, _w in picked)
            remaining = [(idx, win) for _s, _d, idx, win in candidates
                         if idx not in set(chosen)]
            remaining.sort(key=lambda x: x[0])
            cont, used = [], 0
            for _idx, win in remaining:
                add = len(win) + (3 if cont else 0)
                if cont and used + add > cap:
                    continue
                cont.append(win)
                used += add
                if used >= cap:
                    break
            continuation = " … ".join(cont)
        else:
            continuation = ""
        return {"snippet": snippet,
                "est_tokens": q.est_tokens(snippet),
                "chosen_unit_indices": chosen,
                "continuation": continuation,
                "has_more": bool(continuation)}

    def _do_run_query(self, payload):
        import argparse
        import contextlib
        import io
        args = argparse.Namespace(
            query=payload.get("query", ""), claim=payload.get("claim"),
            include_unadmitted=False, include_invalidated=False,
            history=False, domain=payload.get("domain"),
            project=payload.get("project"), environment=None,
            release=None, kind=payload.get("kind"),
            limit=payload.get("limit", 5), full=False,
            show_excluded=False,
            snippet_chars=payload.get("snippet_chars", 260),
            json=True, stats=False,
            index_dir=payload.get("index_dir", self._q.DEFAULT_INDEX_DIR))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self._q.run_query(args)
        text = buf.getvalue().strip()
        return {"returncode": rc,
                "payload": json.loads(text) if text else None}


# --- Live Node/SSH transport (HOME) ------------------------------------

_HOME_HOST = os.environ.get("PAI_HOME_HOST", "")  # live-scaffolding target; set PAI_HOME_HOST to the HOME SSH target when reproducing
_SSH_OPTS = ("-o", "ProxyCommand=nc -X connect -x hatch-egress-proxy:3130 %h %p",
             "-o", "ConnectTimeout=20",
             "-o", "UserKnownHostsFile=/home/hatch/.ssh/known_hosts",
             "-i", os.path.expanduser("~/.ssh/id_ed25519"))
_FROZEN_DIR = ("C:\\ProgramData\\PAI_CHIEF\\generations\\"
               "context-carrier-economy-r1-c987c82738e7944f\\PAI_PROJECT\\"
               "CORE\\chief_chat_bridge_v1\\src\\context-economy")
_CURRENT_DIR = ("C:\\ProgramData\\PAI_CHIEF\\generations\\"
                "one-pai-source-9125efab237d-2894760a0e3c\\src\\one_pai\\"
                "chief\\CORE\\chief_chat_bridge_v1\\src\\context-economy")
_RESIDENT_LIB = ("C:\\ProgramData\\PAI_SIMPLE_BODY_R1\\HOME\\components\\"
                 "resident\\generations\\"
                 "resident-one-pai-55e60d42-20261019-r27-incremental\\"
                 "payload\\src\\one_pai\\body\\resident\\lib\\"
                 "compile-executor-context-packet-r16.cjs")

# Each script receives the payload as JSON in process.env.P (passed
# base64url in argv via the bootstrap) — scripts here get it as the
# global `P` set by the wrapper in _run_js. Scripts print exactly one
# base64 line: {ok:true,result} or {ok:false,error,code}.
_LIVE_SCRIPTS = {
    ("chief", "capsule"): (
        f"const m=require({_js_json(_FROZEN_DIR + chr(92) + 'context-capsule.js')});"
        "out(m.buildContextCapsule(P.input));"),
    ("chief", "reduce_envelope"): (
        f"const m=require({_js_json(_FROZEN_DIR + chr(92) + 'tool-result-reducer.js')});"
        "out(m.reduceToolResult(P.input,P.options||{}));"),
    ("chief", "reduce_receipt"): (
        f"const m=require({_js_json(_CURRENT_DIR + chr(92) + 'tool-result-reducer.js')});"
        "out(m.reduceToolResult(P.input,P.options||{}));"),
    ("chief", "paginate"): (
        f"const m=require({_js_json(_CURRENT_DIR + chr(92) + 'tool-result-reducer.js')});"
        "out(m.paginateOutput(P.items,{page:P.page,pageSize:P.pageSize}));"),
    ("chief", "typed_outward"): (
        f"const m=require({_js_json(_CURRENT_DIR + chr(92) + 'typed-outward-contracts.js')});"
        "out(m.formatTypedOutwardResult(P.call));"),
    ("chief", "cursor_sequence"): (
        f"const {{CursorContinuity}}=require({_js_json(_FROZEN_DIR + chr(92) + 'cursor-continuity.js')});"
        "const cc=new CursorContinuity();const ev=[{threadRef:'t-fix',sequence:1,role:'user',text:'hello'}];"
        "const commit1=cc.commit({threadRef:'t-fix',fromCursor:0,previousBundleHash:null,idempotencyKey:'fixture-1',events:ev});"
        "let gapError=null;try{cc.commit({threadRef:'t-fix',fromCursor:0,previousBundleHash:commit1.bundleHash,idempotencyKey:'fixture-2',events:[{threadRef:'t-fix',sequence:2,role:'user',text:'again'}]});}catch(e){gapError=e.message;}"
        "let hashError=null;try{cc.commit({threadRef:'t-fix',fromCursor:1,previousBundleHash:'0'.repeat(64),idempotencyKey:'fixture-3',events:[{threadRef:'t-fix',sequence:2,role:'user',text:'again'}]});}catch(e){hashError=e.message;}"
        "out({commit1,gapError,hashError,compact:cc.compact('t-fix',32)});"),
    ("resident", "compile"): (
        f"const m=require({_js_json(_RESIDENT_LIB)});"
        "try{out(m.compileExecutorContextPacket(P.artifact));}"
        "catch(e){fail(e);}"),
    ("resident", "fidelity"): (
        f"const m=require({_js_json(_RESIDENT_LIB)});"
        "out(m.fidelityCheck(P.artifact,P.compiled));"),
    ("resident", "bounded_artifact"): (
        f"const m=require({_js_json(_RESIDENT_LIB)});"
        "const s=m.boundedArtifact(P.text,P.ceiling);"
        "out({full:s,tail:s.slice(-80),bytes:Buffer.byteLength(s,'utf8')});"),
}


class LiveNodeTransport(Transport):
    """TEST/REPRODUCTION SCAFFOLDING ONLY — not a production library
    transport; do not wire it as a default transport. Live transport
    to the HOME components over SSH, using the
    recon §6 base64-bootstrap pattern (one SSH call per invocation;
    batched loops broke the proxy during recon). Invokes PURE
    functions only — read-only characterization. Tests must not
    require it: guard with PAI_SLICE3_LIVE=1."""

    def __init__(self, host=_HOME_HOST, timeout=60):
        self.host = host
        self.timeout = timeout

    def invoke(self, component, operation, payload):
        script = _LIVE_SCRIPTS.get((component, operation))
        if script is None:
            raise ComponentError(
                f"LiveNodeTransport has no script for "
                f"{component}.{operation}", code="FIXTURE_NOT_FOUND")
        return self._run_js(script, payload)

    def _run_js(self, body, payload):
        wrapper = (
            "const P=JSON.parse(require('node:zlib').gunzipSync("
            "Buffer.from(process.argv[2],'base64url')).toString('utf8'));"
            "const out=r=>console.log(Buffer.from(JSON.stringify("
            "{ok:true,result:r})).toString('base64'));"
            "const fail=e=>console.log(Buffer.from(JSON.stringify("
            "{ok:false,error:String(e&&e.message||e),"
            "code:(e&&e.code)||String(e&&e.message||e)})"
            ").toString('base64'));"
            "try{" + body + "}catch(e){fail(e);}")
        script_b64 = base64.urlsafe_b64encode(
            wrapper.encode("utf-8")).decode("ascii")
        # The payload travels gzipped: raw base64 of a 20k-char body
        # exceeds the Windows command-line limit ("The command line
        # is too long") — measured during the builder live repro.
        import gzip
        payload_b64 = base64.urlsafe_b64encode(
            gzip.compress(_canonical(payload).encode("utf-8"))
        ).decode("ascii")
        bootstrap = ("eval(Buffer.from(process.argv[1]"
                     ".split('-').join('+').split('_').join('/'),"
                     "'base64').toString('utf8'))")
        remote = (f'powershell -NoProfile -Command "node -e '
                  f'\\"{bootstrap}\\" {script_b64} {payload_b64}"')
        proc = subprocess.run(
            ["ssh", "-n", *_SSH_OPTS, self.host, remote],
            capture_output=True, text=True, timeout=self.timeout)
        line = (proc.stdout or "").strip().splitlines()
        if proc.returncode != 0 or not line:
            raise ComponentError(
                f"live transport failed (rc={proc.returncode}): "
                f"{(proc.stderr or '')[:300]}", code="LIVE_TRANSPORT_FAILED")
        try:
            envelope = json.loads(base64.b64decode(line[-1]).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ComponentError(f"live transport reply unparsable: {exc}",
                                 code="LIVE_TRANSPORT_FAILED")
        if not envelope.get("ok"):
            raise ComponentError(envelope.get("error", "component error"),
                                 code=envelope.get("code"))
        return envelope["result"]


# ---------------------------------------------------------------- adapters


class ChiefAdapter:
    """Generation-pinned Chief context-economy (recon §1).

    Frozen generation: capsule + CursorContinuity + envelope reducer.
    Current generation: structured receipt reducer + typed outward.
    The revision-bound READ cursor is new adapter-layer code (recon
    §1.7): it borrows CursorContinuity's hash discipline — a cursor
    is issued against a revision evidence hash and resume against
    changed evidence fails STALE.
    """

    # current-reducer field maps: structured input -> receipt output
    _COUNT_FIELDS = (("keyFindings", "key_findings"),
                     ("materialDeltas", "material_deltas"),
                     ("changedFiles", "changed_files"),
                     ("evidenceRefs", "evidence_refs"))
    OUTWARD_BUDGETS = {
        "CONTROL_RECEIPT": {"preferredBytes": 1024, "maxBytes": 1843},
        "TERMINAL_READ_CHUNK": {"maxBytes": 4096, "maxLines": 40},
        "EXACT_FETCH_CHUNK": {"preferredBytes": 8192, "maxBytes": 12288},
        "HEAVY_ACTION_RESULT": {"maxBytes": 1843},
    }

    def __init__(self, transport):
        self.transport = transport

    # -- capsule (frozen) -------------------------------------------
    def build_capsule(self, capsule_input):
        """Validate + count the declared budget BEFORE invoking
        (contract rule 2, in the capsule's own unit — Unicode code
        points): protected fields must fit total − output_reserve,
        every source must carry a declared cap. Post-check: no
        emitted source exceeds its cap (rule 3 at the boundary)."""
        if not isinstance(capsule_input, dict):
            raise AdapterBudgetError("capsule input must be an object")
        budget = capsule_input.get("context_budget") or {}
        total = _require_budget("context_budget.total", budget.get("total"))
        reserve = budget.get("output_reserve")
        if not isinstance(reserve, int) or isinstance(reserve, bool) \
                or reserve < 0 or total <= reserve:
            raise AdapterBudgetError(
                f"context_budget invalid: total ({total}) must exceed "
                f"output_reserve ({reserve!r})")
        caps = budget.get("source_caps") or {}
        protected = {k: capsule_input[k] for k in _CAPSULE_PROTECTED
                     if k in capsule_input}
        protected_units = codepoints(_js_json(protected))
        if protected_units > total - reserve:
            raise AdapterBudgetError(
                f"PROTECTED_FIELD_BUDGET_EXCEEDED: protected fields "
                f"count {protected_units} code points before load, "
                f"over the declared {total - reserve} available",
                code="PROTECTED_FIELD_BUDGET_EXCEEDED")
        sources = capsule_input.get("sources") or []
        for src in sources:
            if src.get("id") not in caps:
                raise AdapterBudgetError(
                    f"SOURCE_CAP_REQUIRED:{src.get('id')} — every "
                    "source must declare its cap before load",
                    code=f"SOURCE_CAP_REQUIRED:{src.get('id')}")
        out = self.transport.invoke("chief", "capsule",
                                    {"input": capsule_input})
        for src in out.get("sources") or []:
            cap = caps.get(src.get("id"))
            if cap is not None and codepoints(src.get("content", "")) > cap:
                raise AdapterBudgetError(
                    f"capsule source {src.get('id')!r} emitted "
                    f"{codepoints(src.get('content', ''))} code points "
                    f"over its declared cap {cap} — refusing to "
                    "truncate silently")
        return out

    # -- cursor continuity (frozen) ----------------------------------
    def commit_bundle(self, commit_input):
        return self.transport.invoke("chief", "cursor_commit",
                                     {"input": commit_input})

    def compact_bundle(self, thread_ref, keep=32):
        return self.transport.invoke(
            "chief", "cursor_compact",
            {"threadRef": thread_ref, "keep": keep})

    def cursor_sequence(self):
        """The recon §6.1 deterministic capture (commit + CURSOR_GAP
        + PRIOR_HASH_MISMATCH + compact) through the transport."""
        return self.transport.invoke("chief", "cursor_sequence", {})

    # -- revision-bound READ cursor (adapter-layer, new) --------------
    def issue_read_cursor(self, revision_evidence, position=0):
        return issue_cursor("chief-read", revision_evidence, position)

    def resume_read_cursor(self, cursor, current_revision_evidence):
        """Resume a read cursor; changed revision evidence fails
        loudly as STALE (contract rule 5). Returns the position."""
        payload = check_cursor(cursor, "chief-read",
                               current_revision_evidence)
        return payload["position"]

    # -- frozen envelope reducer (DISTINCT name) -----------------------
    def reduce_envelope(self, envelope_input, options=None):
        """Frozen generation's reduceToolResult: raw string ->
        tool-result-envelope/v1. Declared budget = maxBytes, counted
        before invocation; the excerpt is post-checked against it."""
        options = dict(options or {})
        max_bytes = _require_budget(
            "maxBytes", options.get("maxBytes", 1024))
        if not isinstance(envelope_input, dict) \
                or not isinstance(envelope_input.get("raw"), str):
            raise AdapterBudgetError(
                "envelope input must carry a raw string")
        counted = utf8_bytes(envelope_input["raw"])  # counted before load
        out = self.transport.invoke(
            "chief", "reduce_envelope",
            {"input": envelope_input, "options": options})
        if utf8_bytes(out.get("excerpt", "")) > max_bytes:
            raise AdapterBudgetError(
                f"envelope excerpt is {utf8_bytes(out.get('excerpt', ''))} "
                f"bytes over its declared budget {max_bytes} bytes")
        out = dict(out)
        out["adapter_counted_input_bytes"] = counted
        return out

    # -- current structured reducer (DISTINCT name) --------------------
    def reduce_receipt(self, structured_input, options=None):
        """Current generation's reduceToolResult: structured result
        -> pai-tool-result-receipt/v1. The component applies its
        count caps SILENTLY (recon §1.4a); the adapter compensates:
        in/out item counts are compared per field and any field the
        component sliced without flagging is named in
        `sliced_fields`, with the wrapper's `truncated` set True."""
        options = dict(options or {})
        max_bytes = _require_budget(
            "maxBytes", options.get("maxBytes", 1800))
        counted_in = {src: len(structured_input.get(src) or [])
                      for src, _dst in self._COUNT_FIELDS}
        out = self.transport.invoke(
            "chief", "reduce_receipt",
            {"input": structured_input, "options": options})
        receipt_bytes = utf8_bytes(_js_json(out))
        if receipt_bytes > max_bytes:
            raise AdapterBudgetError(
                f"receipt output is {receipt_bytes} bytes over its "
                f"declared budget {max_bytes} bytes — refusing to "
                "truncate silently")
        sliced = []
        counts = {}
        for src, dst in self._COUNT_FIELDS:
            n_in, n_out = counted_in[src], len(out.get(dst) or [])
            counts[src] = {"in": n_in, "out": n_out}
            if n_out < n_in:
                sliced.append(src)
        component_flag = bool(out.get("truncated"))
        return {"receipt": out,
                "truncated": component_flag or bool(sliced),
                "component_truncated_flag": component_flag,
                "sliced_fields": sliced,
                "counts": counts,
                "receipt_bytes": receipt_bytes}

    def paginate(self, items, page=1, page_size=8):
        """Current generation's paginateOutput, wrapped as-is. Its
        bare-offset cursor is NOT revision-bound (recon §1.4a) — pair
        it with issue_read_cursor/resume_read_cursor over the item
        list when a resumable, STALE-loud cursor is needed."""
        return self.transport.invoke(
            "chief", "paginate",
            {"items": list(items), "page": page, "pageSize": page_size})

    # -- typed outward contracts (current) ------------------------------
    def format_typed_outward(self, case, call=None):
        """Typed outward bounds, post-checked against OUTWARD_BUDGETS:
        EXACT_FETCH_CHUNK text is bounded to the 8192-byte preferred
        size; TERMINAL_READ_CHUNK to 4096 bytes AND 40 lines with
        next_cursor == cursor + delivered bytes exactly."""
        if case not in ("fetch", "terminal"):
            raise AdapterError(f"unknown typed-outward case {case!r}")
        payload = {"case": case}
        if call is not None:
            payload["call"] = call
            payload["result"] = call.get("result") or {}
        out = self.transport.invoke("chief", "typed_outward", payload)
        ctype = out.get("contract_type")
        budget = self.OUTWARD_BUDGETS.get(ctype)
        if budget is not None:
            delivered = out.get("bytes", utf8_bytes(out.get("text", "")))
            if delivered > budget["maxBytes"]:
                raise AdapterBudgetError(
                    f"{ctype} delivered {delivered} bytes over its "
                    f"declared max {budget['maxBytes']} bytes")
            if ctype == "TERMINAL_READ_CHUNK":
                lines = out.get("text", "").count("\n")
                if lines > budget["maxLines"]:
                    raise AdapterBudgetError(
                        f"TERMINAL_READ_CHUNK delivered {lines} lines "
                        f"over its declared max {budget['maxLines']}")
                if out.get("next_cursor") != out.get("cursor", 0) + delivered:
                    raise AdapterBudgetError(
                        "TERMINAL_READ_CHUNK next_cursor does not "
                        "strictly match cursor + delivered bytes")
        return out


class ResidentAdapter:
    """HOME r27 compileExecutorContextPacket (recon §2). Units are
    BYTES and are named bytes — the ceilings are never called tokens.
    The adapter enforces the 8192-byte PREFERRED ceiling as a flagged
    warning (the component treats it as advisory metadata), surfaces
    the component's HARD-ceiling fuse error loudly as an
    AdapterBudgetError carrying the component's own code/message, and
    surfaces fidelityCheck().missing (the compiler itself surfaces
    only the fidelity ratio). The continuation cursor binds to the
    packet's inputSha256."""

    PREFERRED_CEILING_BYTES = 8192
    HARD_CEILING_BYTES = 12288

    def __init__(self, transport):
        self.transport = transport

    def compile_packet(self, artifact,
                       hard_ceiling_bytes=HARD_CEILING_BYTES,
                       preferred_ceiling_bytes=PREFERRED_CEILING_BYTES):
        _require_budget("hard_ceiling_bytes", hard_ceiling_bytes)
        _require_budget("preferred_ceiling_bytes", preferred_ceiling_bytes)
        if preferred_ceiling_bytes > hard_ceiling_bytes:
            raise AdapterBudgetError(
                "preferred ceiling must not exceed the hard ceiling")
        art = (artifact or {}).get("artifact") or artifact or {}
        body = art.get("body") or art.get("task") or ""
        counted_body_bytes = utf8_bytes(body)  # counted before invoking
        try:
            out = self.transport.invoke("resident", "compile",
                                        {"artifact": artifact})
        except ComponentError as exc:
            if exc.code == "CONTEXT_BUDGET_OVERRIDE_REQUIRED":
                raise AdapterBudgetError(str(exc), code=exc.code)
            raise
        packet_bytes = utf8_bytes(out.get("packet", ""))
        if packet_bytes != out.get("bytes"):
            raise AdapterError(
                f"resident packet byte count mismatch: adapter "
                f"counted {packet_bytes} bytes, component reported "
                f"{out.get('bytes')}")
        if packet_bytes > hard_ceiling_bytes:
            raise AdapterBudgetError(
                f"resident packet is {packet_bytes} bytes over its "
                f"declared hard ceiling {hard_ceiling_bytes} bytes — "
                "refusing to truncate silently")
        fidelity = self.transport.invoke(
            "resident", "fidelity",
            {"artifact": artifact, "compiled": out})
        warnings = []
        if packet_bytes > preferred_ceiling_bytes:
            warnings.append(
                f"PREFERRED_CEILING_EXCEEDED: packet is {packet_bytes} "
                f"bytes, over the {preferred_ceiling_bytes}-byte "
                "preferred ceiling (hard ceiling "
                f"{hard_ceiling_bytes} bytes)")
        result = dict(out)
        result.update({
            "unit": "bytes",
            "counted_body_bytes": counted_body_bytes,
            "warnings": warnings,
            "preferred_ceiling_exceeded": bool(warnings),
            "fidelity_missing": (fidelity or {}).get("missing", []),
            "fidelity": fidelity,
            "cursor": issue_cursor("resident", out.get("inputSha256"), 0),
        })
        return result

    def resume_packet(self, cursor, current_input_sha256):
        """Resume against the body revision the packet was compiled
        from; a changed inputSha256 fails loudly as STALE."""
        check_cursor(cursor, "resident", current_input_sha256)
        return {"status": "ok", "inputSha256": current_input_sha256}

    def bounded_artifact(self, text, ceiling_bytes=HARD_CEILING_BYTES):
        _require_budget("ceiling_bytes", ceiling_bytes)
        return self.transport.invoke(
            "resident", "bounded_artifact",
            {"text": text, "ceiling": ceiling_bytes})


class HomeCpAdapter:
    """home-cp bounded readers (recon §3) — wrapped nearly as-is.
    The adapter binds each page cursor to the page's whole-file
    sha256: resume re-verifies the hash, and the component's
    HOME_CP_RESULT_CHANGED translates to the contract's STALE
    failure. The component's 3072-byte page cap is a request-schema
    constant — the adapter never edits it; larger reads are chunked
    at the adapter boundary into ≤3072-byte pages."""

    MAX_PAGE_BYTES = 3072
    DEFAULT_PAGE_BYTES = 768

    def __init__(self, transport):
        self.transport = transport

    def validate_read(self, request):
        return self.transport.invoke("home_cp", "validate",
                                     {"request": request})

    def _page(self, result_ref, offset, max_bytes, bound_sha256):
        try:
            page = self.transport.invoke(
                "home_cp", "read_page",
                {"result_ref": result_ref, "cursor": offset,
                 "max_bytes": max_bytes})
        except ComponentError as exc:
            if exc.code == "HOME_CP_RESULT_CHANGED":
                raise StaleCursorError(
                    "STALE: home-cp result changed during read "
                    f"({exc.code}) — re-request instead of resuming")
            raise
        if bound_sha256 is not None and page.get("sha256") != bound_sha256:
            raise StaleCursorError(
                f"STALE: home-cp page sha256 {page.get('sha256')} does "
                f"not match the revision the cursor was issued "
                f"against ({bound_sha256}) — re-request instead of "
                "resuming")
        # Post-check (F1): a delivered page must never exceed the
        # requested max_bytes, nor the component's own page cap —
        # an oversized delivery fails loudly, never passes through.
        delivered_bytes = page.get("bytes")
        if not isinstance(delivered_bytes, int) \
                or isinstance(delivered_bytes, bool) \
                or delivered_bytes < 0:
            raise AdapterError(
                f"home-cp page carries an invalid byte count "
                f"{delivered_bytes!r}")
        if delivered_bytes > max_bytes \
                or delivered_bytes > self.MAX_PAGE_BYTES:
            raise AdapterBudgetError(
                f"home-cp page delivered {delivered_bytes} bytes "
                f"over the requested max_bytes {max_bytes} "
                f"(component page cap {self.MAX_PAGE_BYTES}) — "
                "refusing to pass an oversized page through")
        return page

    def read_page(self, result_ref, max_bytes=DEFAULT_PAGE_BYTES,
                  cursor=None, expected_sha256=None):
        """Read one adapter page of a home-cp result.

        `cursor` is an adapter cursor token from a previous read (or
        None for page 0). Requests larger than the component's
        3072-byte cap are chunked. Returns the page envelope with the
        base64 content decoded-then-re-encoded as one segment, plus
        `adapter_cursor` bound to (offset, whole-file sha256)."""
        _require_budget("max_bytes", max_bytes)
        offset, bound = 0, expected_sha256
        if cursor is not None:
            # The home-cp token is self-bound: it carries (offset,
            # whole-file sha256) in its position payload. There is no
            # independent evidence to hash-compare at issue time —
            # the binding is enforced in _page, where every resumed
            # page's live sha256 must equal the token's bound hash
            # (and HOME_CP_RESULT_CHANGED translates to STALE).
            payload = _decode_cursor_payload(cursor, "home-cp")
            offset = payload["position"]["offset"]
            bound = payload["position"]["sha256"]
        chunks, delivered, total_bytes, has_more = [], 0, None, False
        remaining = max_bytes
        while remaining > 0:
            page = self._page(result_ref, offset,
                              min(self.MAX_PAGE_BYTES, remaining), bound)
            bound = page["sha256"]
            total_bytes = page["total_bytes"]
            raw = base64.b64decode(page["content"])
            if len(raw) != page["bytes"]:
                raise AdapterError(
                    "home-cp page content length does not match its "
                    "declared byte count")
            chunks.append(raw)
            delivered += len(raw)
            offset = page["next_cursor"]
            has_more = page["has_more"]
            remaining -= len(raw)
            if not has_more or len(raw) == 0:
                break
        content = b"".join(chunks)
        if delivered > max_bytes:
            raise AdapterBudgetError(
                f"home-cp read delivered {delivered} bytes over "
                f"the requested max_bytes {max_bytes} — refusing "
                "to pass an oversized delivery through")
        adapter_cursor = None
        if has_more:
            adapter_cursor = issue_cursor(
                "home-cp", {"offset": offset, "sha256": bound},
                {"offset": offset, "sha256": bound})
        return {"result_ref": result_ref, "cursor": offset - delivered,
                "next_cursor": offset, "bytes": delivered,
                "total_bytes": total_bytes, "encoding": "base64",
                "content": base64.b64encode(content).decode("ascii"),
                "sha256": bound, "has_more": has_more,
                "adapter_cursor": adapter_cursor}

    def bounded(self, result, limit=12000):
        _require_budget("limit", limit)
        return self.transport.invoke("home_cp", "bounded",
                                     {"result": result, "limit": limit})


def _decode_cursor_payload(cursor, component):
    """Decode an adapter cursor token and check its component,
    WITHOUT a revision comparison (for self-bound tokens whose
    evidence travels inside the token — see HomeCpAdapter)."""
    if not isinstance(cursor, str) or not cursor.startswith("cur_"):
        raise AdapterError("malformed continuation cursor")
    try:
        payload = json.loads(base64.urlsafe_b64decode(
            cursor[4:].encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — reported, not hidden
        raise AdapterError(f"malformed continuation cursor: {exc}")
    if not isinstance(payload, dict) or payload.get("component") != component:
        raise AdapterError(
            f"continuation cursor was not issued for {component!r}")
    return payload


class RetrievalAdapter:
    """Retrieval snippet assembly (recon §4) — wraps the repo's own
    packages/retrieval. Budget-before-load and the named estimator
    (est_tokens = ceil(chars/4)) are the package's own; the adapter
    adds the one clear gap: a continuation cursor in
    packages/context keyed to the source fingerprint the package
    already computes — a changed fingerprint at resume fails STALE.
    """

    ESTIMATOR = "ceil(chars/4)"

    def __init__(self, transport=None):
        self.transport = transport or InProcessRetrievalTransport()

    def make_snippet(self, text, query, cap=260, budget_chars=None):
        """Bounded snippet through the package. The declared budget
        (chars) is validated and the cap checked against it BEFORE
        the package is invoked; the snippet is post-checked against
        the cap."""
        budget = _require_budget("budget_chars",
                                 budget_chars if budget_chars is not None
                                 else cap)
        _require_budget("cap", cap)
        if cap > budget:
            raise AdapterBudgetError(
                f"snippet cap {cap} chars exceeds the declared budget "
                f"{budget} chars — counted before load")
        if isinstance(query, str):
            qtokens = self.transport.invoke(
                "retrieval", "tokenize", {"text": query})["tokens"]
        else:
            qtokens = list(query)
        out = self.transport.invoke(
            "retrieval", "make_snippet",
            {"text": text, "qtokens": qtokens, "cap": cap})
        if len(out["snippet"]) > cap:
            raise AdapterBudgetError(
                f"snippet is {len(out['snippet'])} chars over its "
                f"declared cap {cap} chars — refusing to truncate "
                "silently")
        return {"snippet": out["snippet"],
                "est_tokens": out["est_tokens"],
                "estimator": self.ESTIMATOR, "qtokens": qtokens}

    def snippet_with_cursor(self, record_id, text, query,
                            source_fingerprint, cap=260):
        """Snippet + continuation cursor over (record id, source
        fingerprint). The fingerprint is the package's own source
        fingerprint (retrieval_query.freshness mechanism)."""
        _require_budget("cap", cap)
        if isinstance(query, str):
            qtokens = self.transport.invoke(
                "retrieval", "tokenize", {"text": query})["tokens"]
        else:
            qtokens = list(query)
        detail = self.transport.invoke(
            "retrieval", "snippet_detail",
            {"text": text, "qtokens": qtokens, "cap": cap})
        if len(detail["snippet"]) > cap:
            raise AdapterBudgetError(
                f"snippet is {len(detail['snippet'])} chars over its "
                f"declared cap {cap} chars")
        cursor = issue_cursor(
            "retrieval",
            {"record_id": record_id, "fingerprint": source_fingerprint},
            {"record_id": record_id,
             "chosen_unit_indices": detail["chosen_unit_indices"]})
        return {"snippet": detail["snippet"],
                "est_tokens": detail["est_tokens"],
                "estimator": self.ESTIMATOR,
                "record_id": record_id,
                "source_fingerprint": source_fingerprint,
                "has_more": detail["has_more"],
                "cursor": cursor}

    def resume_snippet(self, cursor, text, query,
                       current_source_fingerprint, cap=260):
        """Continue a snippet cursor. A changed source fingerprint
        fails loudly as STALE (contract rule 5); otherwise the
        continuation segment (units not served in the first snippet)
        is returned."""
        _require_budget("cap", cap)
        if isinstance(query, str):
            qtokens = self.transport.invoke(
                "retrieval", "tokenize", {"text": query})["tokens"]
        else:
            qtokens = list(query)
        detail = self.transport.invoke(
            "retrieval", "snippet_detail",
            {"text": text, "qtokens": qtokens, "cap": cap})
        # The cursor's record binding is read from its payload; the
        # revision check compares fingerprints for that record.
        raw = _decode_cursor_payload(cursor, "retrieval")
        record_id = (raw.get("position") or {}).get("record_id")
        check_cursor(cursor, "retrieval",
                     {"record_id": record_id,
                      "fingerprint": current_source_fingerprint})
        return {"continuation": detail["continuation"],
                "has_more": False,
                "record_id": record_id,
                "source_fingerprint": current_source_fingerprint}

    def run_query(self, query, index_dir=None, limit=5, kind=None,
                  domain=None):
        """The package's run_query path (validity gate + freshness +
        snippet serve) through the transport."""
        _require_budget("limit", limit)
        if limit > 32:
            raise AdapterBudgetError(
                f"limit {limit} exceeds the Knowledge Room budget "
                "ceiling 32 — counted before load")
        payload = {"query": query, "limit": limit, "kind": kind,
                   "domain": domain}
        if index_dir is not None:
            payload["index_dir"] = index_dir
        return self.transport.invoke("retrieval", "run_query", payload)
