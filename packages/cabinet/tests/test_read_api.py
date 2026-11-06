#!/usr/bin/env python3
"""Tests for the Phase 3 Cabinet read API (read_api.py).

Everything runs on FIXTURE-LOCAL state built in temp directories: a
scratch registry (via the production Registrar's append path), a
fixture claims.jsonl (read through a staged copy of the canonical
claimreg module, supplied via the parameterized claimreg_path with
its LOG pointed at the fixture), and a fixture spine SQLite DB opened
read-only. No test touches live store state, and no expectation is a
hardcoded live-registry constant (gap G8 discipline).

Run: python3 -m unittest test_read_api -v   (from this directory)
"""
import ast
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)
import registrar as R  # noqa: E402
import read_api as A  # noqa: E402

AT = "2026-11-05T13:00:00-08:00"
EV = "sha256:" + "b" * 64 + "@2026-11-05T12:59:00-08:00"
ACTOR = "read-api-test"


def mint():
    return {"type": "MINT", "at": AT, "actor": ACTOR,
            "reason": "new-work-area"}


def link(cab, system, mid, kind, relation="primary"):
    return {"type": "LINK", "cabinet_id": cab, "at": AT, "actor": ACTOR,
            "member": {"system": system, "id": mid, "kind": kind},
            "relation": relation, "evidence": EV,
            "reason": "title-citation"}


def unlink(cab, system, mid, kind, corrects, reason="evidence-refuted",
           relation="primary"):
    return {"type": "UNLINK", "cabinet_id": cab, "at": AT, "actor": ACTOR,
            "member": {"system": system, "id": mid, "kind": kind},
            "relation": relation, "evidence": EV, "reason": reason,
            "corrects": str(corrects)}


def claim(cid, **kw):
    d = {"id": cid, "claim": f"fixture claim {cid}", "entity": "Fixture",
         "source": "fixture:1", "status": "current", "type": "STATUS"}
    d.update(kw)
    return d


# ------------------------------------------------------- AST scan (g)

# Attribute calls that would mutate a store or the filesystem. The one
# deliberate exception is the loader's exec_module on the hash-pinned
# claimreg dependency (audited loading, not a write path).
_FORBIDDEN_CALL_ATTRS = {
    "write", "writelines", "write_text", "write_bytes", "touch",
    "append_events", "forget_member", "project",
    "admit_batch", "remove", "unlink", "rmdir", "rename", "replace",
    "mkdir", "makedirs", "rmtree", "copyfile", "copy2", "copytree",
    "system", "popen",
}
_FORBIDDEN_IMPORTS = {"subprocess", "shutil"}
_FORBIDDEN_FROM_IMPORTS = {"append_events", "forget_member", "project",
                           "admit_batch"}
_OS_CALL_ALLOWLIST = {"os.environ.get"}


def _dotted(func):
    parts = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


_GAP = "\x00"  # sentinel for interpolated (non-constant) f-string spans


def _static_text(node):
    """Statically known text of a string expression: constants
    verbatim; an f-string's constant spans verbatim with each
    interpolation replaced by the _GAP sentinel. None when the text
    is not statically known (names, calls, ...)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append(_GAP)
        return "".join(parts)
    return None


def _effective_keywords(node):
    """(mapping, opaque) for a call's keyword arguments, with
    `**` unpackings resolved statically where possible. Python's
    AST represents a `**` unpacking as a keyword whose arg is
    None and whose value is the unpacked expression. When that
    expression is a literal dict with constant string keys, its
    entries are evaluated exactly as if they had been written as
    ordinary keywords. Any other `**` value — a name, a call, a
    dict with non-constant or non-string keys, a nested `**` —
    cannot be statically resolved: opaque is True, and every
    guarded call family in this scan treats an opaque `**` as a
    finding, because arguments that cannot be seen cannot be
    proved safe. (Fix round 4: Path(TARGET).open(**{'mode':
    'wb'}) truncated a file while the fix-3 scan, which inspected
    only keywords with arg == 'mode', never saw the mode and
    returned no findings.)"""
    mapping = {}
    opaque = False
    for kw in node.keywords:
        if kw.arg is not None:
            mapping[kw.arg] = kw.value
            continue
        value = kw.value
        if isinstance(value, ast.Dict) and all(
                isinstance(k, ast.Constant) and isinstance(k.value, str)
                for k in value.keys):
            for k, v in zip(value.keys, value.values):
                mapping[k.value] = v
        else:
            opaque = True
    return mapping, opaque


def _sqlite_connect_problem(node):
    """None when this sqlite3.connect(...) call is PROVABLY
    read-only, else a problem string. Provable means: the target is
    statically known text of a file: URI, the call passes uri=True,
    and the URI's query — parsed as a query string, never
    substring-matched — carries exactly one mode parameter whose
    value is fully constant and exactly 'ro' (immutable=1 and the
    inert comment parameter are the only other recognized
    parameters). The fix-1 scan's substring test was evaded by
    mode=rwc&comment=mode=ro; real parsing is immune to that.
    Query/fragment boundaries follow SQLite's own grammar: the
    query runs from the first '?' to the first '#' or end of
    string, and everything from '#' on is fragment, which SQLite
    never treats as query parameters — so a '?' that only appears
    after a '#' starts no query at all (fix round 3,
    counterexample A: file:{TARGET}#?mode=ro executed a writable
    connect while the fix-2 scan, which searched for '?' across the
    fragment boundary, returned no findings). Keyword arguments
    are read through _effective_keywords, so uri=True may arrive
    via a statically literal `**` dict — and an unpacking that
    cannot be statically resolved fails closed (fix round 4)."""
    keywords, opaque = _effective_keywords(node)
    if opaque:
        return ("sqlite3.connect **kwargs cannot be statically"
                " resolved — not provably read-only")
    target_node = node.args[0] if node.args \
        else keywords.get("database")
    if target_node is None:
        return "sqlite3.connect without a target argument"
    text = _static_text(target_node)
    if text is None:
        return "sqlite3.connect target is not statically known"
    uri_node = keywords.get("uri")
    if not (isinstance(uri_node, ast.Constant)
            and uri_node.value is True):
        return "sqlite3.connect without uri=True"
    if not text.startswith("file:"):
        return "sqlite3.connect target is not a file: URI"
    rest = text[len("file:"):]
    hashmark = rest.find("#")
    head = rest if hashmark < 0 else rest[:hashmark]
    qmark = head.find("?")
    if qmark < 0:
        if hashmark >= 0:
            return ("sqlite3.connect URI fragment precedes any query"
                    " string — not provably read-only")
        return "sqlite3.connect URI has no query string"
    params = {}
    for pair in head[qmark + 1:].split("&"):
        if not pair:
            continue
        key, _, val = pair.partition("=")
        params.setdefault(key, []).append(val)
    modes = params.get("mode")
    if modes is None or len(modes) != 1:
        return "sqlite3.connect URI mode missing or repeated"
    if _GAP in modes[0] or modes[0] != "ro":
        return ("sqlite3.connect URI mode is not provably 'ro': "
                f"{modes[0]!r}")
    for key, vals in params.items():
        if key in ("mode", "comment"):
            continue
        if key == "immutable" and vals == ["1"]:
            continue
        return ("sqlite3.connect URI parameter not provably inert: "
                f"{key!r}")
    return None


def _mode_problem(mode_node, label):
    """None when a SUPPLIED open mode is provably read-only, else
    a problem string. Provable means the mode text is fully
    statically known — a constant, or an f-string whose spans are
    all constant — and free of w/a/x/+. A supplied mode that
    cannot be statically proved safe — a write-ish constant, or
    any non-constant value (a name, a call, an interpolated
    f-string), whether written directly or arriving as the value
    inside an expanded literal `**` dict — fails closed. This one
    rule is shared verbatim by the bare open() branch and
    _method_open_problem: fix round 5 exists because the bare
    branch alone judged the mode with _const_str and treated a
    supplied-but-unprovable value as no mode at all (verdict
    counterexample: MODE = 'wb'; open(TARGET, **{'mode': MODE})
    truncated a file while the scan returned no findings; the
    method family already failed closed for the same value)."""
    text = _static_text(mode_node)
    if text is None or _GAP in text:
        return f"{label} mode is not statically known"
    if set(text) & set("wax+"):
        return f"{label} write mode {text!r}"
    return None


def _method_open_problem(node):
    """None when this <expr>.open(...) call is provably a read-mode
    open, else a problem string. This is the pathlib Path.open
    shape (fix round 3, counterexample B: Path(TARGET).open('wb')
    executed a truncating open while the fix-2 scan returned no
    findings — its mode check covered only a bare Name open). The
    mode is Path.open's first parameter: no mode argument means
    the default 'r'; a fully constant mode free of w/a/x/+ is a
    read; a write-ish constant mode, or a mode that is not
    statically known, fails closed. The mode keyword is read
    through _effective_keywords, so a statically literal
    `**{'mode': ...}` dict is evaluated like an ordinary keyword
    — and an unpacking that cannot be statically resolved fails
    closed, since the mode may be hiding inside it (fix round 4,
    counterexample: Path(TARGET).open(**{'mode': 'wb'})). The
    mode judgment itself is _mode_problem, shared verbatim with
    the bare open() branch so the two families cannot drift
    apart (fix round 5)."""
    keywords, opaque = _effective_keywords(node)
    if opaque:
        return (".open() **kwargs cannot be statically resolved"
                " — not provably a read open")
    mode_node = node.args[0] if node.args else None
    if "mode" in keywords:
        mode_node = keywords["mode"]
    if mode_node is None:
        return None  # Path.open() default mode is 'r'
    return _mode_problem(mode_node, ".open()")


def _write_path_problems(src):
    """AST scan of read_api.py for store/filesystem write paths.
    Checks, over the module's AST:
    - imports of subprocess/shutil, and from-imports of the
      Registrar's write entry points;
    - open(...) and method .open(...) calls (the pathlib
      Path.open shape) whose SUPPLIED mode is not provably
      read-only: a write-ish constant, or any value that is not
      fully statically known (a name, a call, an interpolated
      f-string), whether written directly or arriving as the
      value inside an expanded literal `**` dict — one rule
      (_mode_problem) for both families, so a supplied mode can
      never again be silently read as no mode in one family
      while failing closed in the other (fix round 5). An
      omitted mode is the default read and passes;
    - attribute calls named like a write/mutation entry point
      (including the pathlib mutation family: touch, write_text,
      write_bytes, mkdir, unlink, rename, replace, ...);
    - os.* calls other than os.path.* and os.environ.get;
    - sqlite3.connect(...) whose target is not a PROVABLY read-only
      file: URI (the query is parsed for real — mode exactly 'ro',
      immutable=1 allowed, uri=True required; a substring match is
      never used, and the query is delimited the way SQLite
      delimits it: first '?' to first '#', fragment never query).
    Keyword arguments of every guarded family above (bare open,
    method .open, sqlite3.connect) are read through
    _effective_keywords: a statically literal `**{...}` dict is
    expanded and evaluated exactly as if its entries were ordinary
    keywords, and any `**` unpacking that cannot be statically
    resolved is itself a finding — opaque arguments cannot be
    proved safe, so the scan fails closed on them (fix round 4).
    The sqlite family was audited for the same asymmetry in fix
    round 5 and already complies: an unprovable connect target
    is not a proven read-only URI, and a `uri` that is supplied
    but is not the constant True is not uri=True — both are
    findings, never skips.
    Returns a list of problem strings. An empty list means no write
    path was found BY THESE CHECKS — a broad net with executed
    negative controls, not a proof that none can exist."""
    problems = []
    tree = ast.parse(src)
    bare_sqlite_connect = any(
        isinstance(n, ast.ImportFrom) and n.module == "sqlite3"
        and any(a.name in ("connect", "*") for a in n.names)
        for n in ast.walk(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in _FORBIDDEN_IMPORTS:
                    problems.append(
                        f"import {a.name} (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _FORBIDDEN_IMPORTS:
                problems.append(
                    f"from-import {node.module} (line {node.lineno})")
            for a in node.names:
                if a.name in _FORBIDDEN_FROM_IMPORTS:
                    problems.append(
                        f"from-import of write entry point {a.name}"
                        f" (line {node.lineno})")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                keywords, opaque = _effective_keywords(node)
                if opaque:
                    problems.append(
                        "open() **kwargs cannot be statically"
                        f" resolved (line {node.lineno})")
                mode_node = None
                if len(node.args) >= 2:
                    mode_node = node.args[1]
                if "mode" in keywords:
                    mode_node = keywords["mode"]
                if mode_node is not None:
                    problem = _mode_problem(mode_node, "open()")
                    if problem is not None:
                        problems.append(
                            f"{problem} (line {node.lineno})")
            if bare_sqlite_connect and isinstance(func, ast.Name) \
                    and func.id == "connect":
                problem = _sqlite_connect_problem(node)
                if problem is not None:
                    problems.append(f"{problem} (line {node.lineno})")
            if isinstance(func, ast.Attribute):
                if func.attr in _FORBIDDEN_CALL_ATTRS:
                    problems.append(
                        f"call .{func.attr}() (line {node.lineno})")
                if func.attr == "open":
                    problem = _method_open_problem(node)
                    if problem is not None:
                        problems.append(
                            f"{problem} (line {node.lineno})")
                dotted = _dotted(func)
                if dotted is not None and dotted.startswith("os.") \
                        and not dotted.startswith("os.path.") \
                        and dotted not in _OS_CALL_ALLOWLIST:
                    problems.append(
                        f"os call {dotted}() (line {node.lineno})")
                if func.attr == "connect" and isinstance(
                        func.value, ast.Name) and func.value.id == "sqlite3":
                    problem = _sqlite_connect_problem(node)
                    if problem is not None:
                        problems.append(
                            f"{problem} (line {node.lineno})")
    return problems


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reg = os.path.join(self.tmp.name, "REGISTRY.jsonl")
        self.head = R.GENESIS_HASH
        self.claims_log = os.path.join(self.tmp.name, "claims.jsonl")
        self.spine_db = os.path.join(self.tmp.name, "spine.db")
        # The claimreg dependency runs through its parameterized
        # location in EVERY test: a fixture copy of the canonical
        # module staged in the temp dir (the staged off-VM
        # simulation), never the hardcoded default path.
        self.claimreg_copy = os.path.join(self.tmp.name,
                                          "claimreg_copy.py")
        canonical = A._resolve_claimreg_path()
        if not os.path.isfile(canonical):
            self.skipTest(
                f"canonical claimreg module unavailable at {canonical}")
        shutil.copyfile(canonical, self.claimreg_copy)

    def append(self, cands):
        out = R.append_events(self.reg, cands, self.head)
        self.head = out["head"]
        return out

    def write_claims(self, claims, extra_events=()):
        with open(self.claims_log, "w", encoding="utf-8") as f:
            for c in claims:
                f.write(json.dumps(
                    {"event": "ADMIT", "at": "2026-11-05T12:00:00+00:00",
                     "writer": ACTOR, "claim": c}) + "\n")
            for ev in extra_events:
                f.write(json.dumps(ev) + "\n")

    def write_spine(self, rows):
        conn = sqlite3.connect(self.spine_db)
        conn.execute(
            "CREATE TABLE tasks (task_id TEXT, title TEXT, state TEXT,"
            " program TEXT, owner_surface TEXT, registration_class TEXT,"
            " created_at TEXT, closed_at TEXT, deadline_at TEXT)")
        conn.executemany(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()

    def write_spine_privacy(self, rows):
        """tasks table WITH a privacy column; rows are the 9 content
        fields plus a privacy value (None / non-string / string). The
        column is declared without a type name (BLOB affinity) so a
        non-string value is stored as-is, not coerced to text."""
        conn = sqlite3.connect(self.spine_db)
        conn.execute(
            "CREATE TABLE tasks (task_id TEXT, title TEXT, state TEXT,"
            " program TEXT, owner_surface TEXT, registration_class TEXT,"
            " created_at TEXT, closed_at TEXT, deadline_at TEXT,"
            " privacy)")
        conn.executemany(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()

    def api(self, **kw):
        kw.setdefault("registry_path", self.reg)
        kw.setdefault("claims_log_path", self.claims_log)
        kw.setdefault("spine_db_path", self.spine_db)
        kw.setdefault("claimreg_path", self.claimreg_copy)
        api = A.ReadAPI(**kw)
        # Deterministic closure BEFORE the temp dir is cleaned up:
        # addCleanup is LIFO and setUp registered tmp.cleanup first,
        # so this close runs first. On Windows an open SQLite
        # connection blocks unlinking the fixture spine.db (WinError
        # 32 — the four cleanup errors of the fix-1 re-review).
        self.addCleanup(api.close)
        return api


class TestDefaultsAndContent(Fixture):
    def test_a_defaults_per_namespace(self):
        self.write_claims([claim("C-9001")])
        self.write_spine([("sp-fixture-1", "Fixture task", "QUEUED",
                           "prog", "surface", "proxy",
                           "2026-11-02T00:00:00Z", None, None)])
        self.append([mint(), link("cab-0001", "claim-register", "C-9001",
                                   "epistemic-claim")])
        self.append([mint(), link("cab-0002", "vm-spine", "sp-fixture-1",
                                   "planning-task")])
        self.append([mint(), link("cab-0003", "home-runloop", "wu-fixture:1",
                                   "work-unit")])
        self.append([mint(), link("cab-0004", "claim-service",
                                   "claim_fixture-0001", "execution-claim")])
        api = self.api()
        for system, mid in (("claim-register", "C-9001"),
                            ("vm-spine", "sp-fixture-1"),
                            ("home-runloop", "wu-fixture:1"),
                            ("claim-service", "claim_fixture-0001")):
            out = api.resolve(system, mid)
            self.assertEqual(out["effective_privacy"], "house", system)
            self.assertEqual(out["privacy_basis"], "namespace-default",
                             system)
            self.assertTrue(out["member"], system)
            self.assertEqual(
                out["cabinets"][0]["cabinet_derived_privacy"], "house",
                system)
        # Contract alias resolves to the same member.
        out = api.resolve("home-claim-service", "claim_fixture-0001")
        self.assertEqual(out["system"], "claim-service")
        self.assertEqual(out["namespace"], "home-claim-service")
        # Content: claims and spine tasks are served natively...
        self.assertEqual(api.resolve("claim-register", "C-9001")
                         ["content"]["id"], "C-9001")
        self.assertEqual(api.resolve("vm-spine", "sp-fixture-1")
                         ["content"]["title"], "Fixture task")
        # ...HOME members are registry-only, with the note saying so.
        out = api.resolve("home-runloop", "wu-fixture:1")
        self.assertIsNone(out["content"])
        self.assertIn("registry-only", out["content_note"])
        out = api.resolve("claim-service", "claim_fixture-0001")
        self.assertIsNone(out["content"])
        self.assertIn("registry-only", out["content_note"])

    def test_b_explicit_stricter_wins(self):
        self.write_claims([claim("C-9002", privacy="private"),
                           claim("C-9005", privacy="secret-pointer"),
                           claim("C-9006")])
        self.append([mint(), link("cab-0001", "claim-register", "C-9002",
                                   "epistemic-claim")])
        self.append([mint(),
                     link("cab-0002", "claim-register", "C-9005",
                          "epistemic-claim"),
                     link("cab-0002", "claim-register", "C-9006",
                          "epistemic-claim")])
        api = self.api()
        out = api.resolve("claim-register", "C-9002")
        self.assertEqual(out["effective_privacy"], "private")
        self.assertEqual(out["privacy_basis"], "explicit")
        self.assertEqual(out["cabinets"][0]["cabinet_derived_privacy"],
                         "private")
        # Strictest member governs the combined entry.
        cab = api.cabinet("cab-0002")
        self.assertEqual(cab["derived_privacy"], "secret-pointer")
        self.assertTrue(cab["content_entitled"])

    def test_e_secondary_resolves_both_cabinets(self):
        self.write_claims([claim("C-9007")])
        self.append([mint(), link("cab-0001", "claim-register", "C-9007",
                                   "epistemic-claim")])
        self.append([mint(), link("cab-0002", "claim-register", "C-9007",
                                   "epistemic-claim",
                                   relation="secondary")])
        api = self.api()
        out = api.resolve("claim-register", "C-9007")
        by_cab = {c["cabinet_id"]: c["relation"] for c in out["cabinets"]}
        self.assertEqual(by_cab, {"cab-0001": "primary",
                                  "cab-0002": "secondary"})
        cab2 = api.cabinet("cab-0002")
        self.assertEqual(cab2["members"][0]["relation"], "secondary")
        listing = api.members("claim-register")
        self.assertEqual(listing["count"], 1)
        self.assertEqual(len(listing["members"][0]["cabinets"]), 2)


class TestEntitlementEnforcement(Fixture):
    def test_c_no_default_namespace_denied(self):
        self.write_claims([claim("C-9001"),
                           claim("C-9002", privacy="private")])
        self.write_spine([("sp-fixture-1", "Fixture task", "QUEUED",
                           "prog", "surface", "proxy",
                           "2026-11-02T00:00:00Z", None, None)])
        self.append([mint(), link("cab-0001", "vm-spine", "sp-fixture-1",
                                   "planning-task")])
        self.append([mint(), link("cab-0002", "claim-register", "C-9001",
                                   "epistemic-claim")])
        self.append([mint(), link("cab-0003", "claim-register", "C-9002",
                                   "epistemic-claim")])
        # A defaults map with NO namespace defaults at all: only an
        # explicit field can entitle a read.
        api = self.api(namespace_defaults={})
        out = api.resolve("vm-spine", "sp-fixture-1")
        self.assertEqual(out["effective_privacy"], "unknown")
        self.assertEqual(out["privacy_basis"], "none")
        self.assertIsNone(out["content"])
        self.assertEqual(out["content_excluded"], "unknown-privacy-level")
        out = api.resolve("claim-register", "C-9001")
        self.assertEqual(out["effective_privacy"], "unknown")
        self.assertIsNone(out["content"])
        # Explicit field still wins over a missing default.
        out = api.resolve("claim-register", "C-9002")
        self.assertEqual(out["effective_privacy"], "private")
        self.assertEqual(out["content"]["id"], "C-9002")
        # Cabinet structure still lists; combined content is denied.
        cab = api.cabinet("cab-0001")
        self.assertTrue(cab["found"])
        self.assertEqual(len(cab["members"]), 1)
        self.assertEqual(cab["derived_privacy"], "unknown")
        self.assertFalse(cab["content_entitled"])
        self.assertIsNone(cab["contents"])

    def test_d_forgotten_member_excluded(self):
        self.write_claims(
            [claim("C-9003"), claim("C-9004")],
            extra_events=[{"event": "INVALIDATE", "id": "C-9004",
                           "reason": "forget",
                           "at": "2026-11-05T12:30:00+00:00",
                           "actor": ACTOR}])
        # Line 1 MINT, line 2 LINK C-9003, line 3 LINK C-9004.
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-9003",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9004",
                          "epistemic-claim")])
        # Registry-side forget of C-9003 (forget-consequence UNLINK).
        self.append([unlink("cab-0001", "claim-register", "C-9003",
                            "epistemic-claim", 2,
                            reason="forget-consequence")])
        api = self.api()
        out = api.resolve("claim-register", "C-9003")
        self.assertTrue(out["forgotten"])
        # Forgotten resolve returns the shared purged entry — the
        # exact five-key tombstone shape, with no content keys at
        # all (fix round 3: the round-2 hand-built variant added
        # content/content_excluded; the shared shape is the
        # contract).
        self.assertEqual(set(out), {"system", "namespace", "id",
                                    "forgotten", "tombstone"})
        self.assertEqual(out["tombstone"]["id"], "C-9003")
        # C-9004 is still LINKed in the registry but forgotten in its
        # own ledger: tombstone wins, content never readable.
        out = api.resolve("claim-register", "C-9004")
        self.assertTrue(out["forgotten"])
        self.assertEqual(set(out), {"system", "namespace", "id",
                                    "forgotten", "tombstone"})
        self.assertEqual(out["tombstone"]["id"], "C-9004")
        cab = api.cabinet("cab-0001")
        self.assertEqual(cab["members"], [])
        self.assertEqual([m["id"] for m in cab["purged_members"]],
                         ["C-9004"])
        self.assertIsNone(cab["contents"])

    def test_tombstone_purged_from_mixed_cabinet_derivation(self):
        # Verdict case (iv) with the canonical dependency in place: a
        # claim forgotten in its own ledger (rule 6 tombstone) whose
        # registry LINK is still active is purged from the cabinet's
        # members, its contents, AND its derived-level computation.
        self.write_claims(
            [claim("C-9201", privacy="private"),
             claim("C-9202", privacy="secret-pointer")],
            extra_events=[{"event": "INVALIDATE", "id": "C-9202",
                           "reason": "forget",
                           "at": "2026-11-05T12:30:00+00:00",
                           "actor": ACTOR}])
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-9201",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9202",
                          "epistemic-claim")])
        api = self.api()
        out = api.resolve("claim-register", "C-9202")
        self.assertTrue(out["forgotten"])
        self.assertEqual(set(out), {"system", "namespace", "id",
                                    "forgotten", "tombstone"})
        cab = api.cabinet("cab-0001")
        self.assertEqual([m["id"] for m in cab["members"]], ["C-9201"])
        self.assertEqual([m["id"] for m in cab["purged_members"]],
                         ["C-9202"])
        # The tombstone's secret-pointer level must NOT contaminate
        # the derivation: the surviving member alone governs.
        self.assertEqual(cab["derived_privacy"], "private")
        self.assertTrue(cab["content_entitled"])
        self.assertEqual(list(cab["contents"]),
                         ["claim-register:C-9201"])

    def test_forgotten_member_output_is_tombstone_only(self):
        # Fix round 2 (re-review verdict item 2): the forgotten
        # member's old privacy and linkage metadata must appear
        # NOWHERE in any serialized output; only rule-6 tombstone
        # fields may surface. Values are distinctive: the survivor
        # is 'private', so 'secret-pointer' could only come from the
        # forgotten member, whose LINK sits at registry line 3.
        self.write_claims(
            [claim("C-9201", privacy="private"),
             claim("C-9202", privacy="secret-pointer")],
            extra_events=[{"event": "INVALIDATE", "id": "C-9202",
                           "reason": "forget",
                           "at": "2026-11-05T12:30:00+00:00",
                           "actor": ACTOR}])
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-9201",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9202",
                          "epistemic-claim")])
        api = self.api()
        cab = api.cabinet("cab-0001")
        purged = cab["purged_members"]
        self.assertEqual(len(purged), 1)
        entry = purged[0]
        self.assertEqual(set(entry), {"system", "namespace", "id",
                                      "forgotten", "tombstone"})
        self.assertEqual(entry["id"], "C-9202")
        self.assertTrue(entry["forgotten"])
        self.assertLessEqual(set(entry["tombstone"]),
                             {"system", "id", "forget_at", "actor"})
        self.assertEqual(entry["tombstone"]["forget_at"],
                         "2026-11-05T12:30:00+00:00")
        self.assertEqual(entry["tombstone"]["actor"], ACTOR)
        # members(): the forgotten member lists tombstone-only too.
        listing = api.members("claim-register")
        by_id = {m["id"]: m for m in listing["members"]}
        self.assertEqual(set(by_id["C-9202"]),
                         {"system", "namespace", "id", "forgotten",
                          "tombstone"})
        # resolve(): the EXACT top-level key set is the shared
        # five-key purged shape — no privacy, basis, kind, linkage
        # or content keys at all. (Fix round 3: round 2 asserted
        # only selected absent keys here, and a hand-built variant
        # carrying content/content_excluded passed; the exact set
        # is the assertion that closes that gap.)
        out = api.resolve("claim-register", "C-9202")
        self.assertEqual(set(out), {"system", "namespace", "id",
                                    "forgotten", "tombstone"})
        self.assertEqual(set(out["tombstone"]),
                         {"system", "id", "forget_at", "actor"})
        # Serialized hunt on every surface: the stale privacy value
        # appears nowhere, and the forgotten member's LINK line (3)
        # is not published as a registry_line in the cabinet (the
        # survivor's line 2 legitimately appears).
        for name, surface in (("cabinet", cab), ("resolve", out),
                              ("members", listing)):
            self.assertNotIn("secret-pointer",
                             json.dumps(surface, sort_keys=True), name)
        self.assertNotIn('"registry_line": 3',
                         json.dumps(cab, sort_keys=True))

    def test_invalidated_claim_membership_without_content(self):
        self.write_claims(
            [claim("C-9008")],
            extra_events=[{"event": "INVALIDATE", "id": "C-9008",
                           "by": "C-9009",
                           "at": "2026-11-05T12:30:00+00:00"}])
        self.append([mint(), link("cab-0001", "claim-register", "C-9008",
                                   "epistemic-claim")])
        api = self.api()
        out = api.resolve("claim-register", "C-9008")
        self.assertTrue(out["member"])          # membership resolves
        self.assertFalse(out["forgotten"])      # ordinary INVALIDATE
        self.assertIsNone(out["content"])       # content does not serve
        self.assertEqual(out["content_excluded"],
                         "invalidated-not-retrievable-by-default")

    def test_read_only_stores_untouched(self):
        self.write_claims([claim("C-9001")])
        self.write_spine([("sp-fixture-1", "Fixture task", "QUEUED",
                           "prog", "surface", "proxy",
                           "2026-11-02T00:00:00Z", None, None)])
        self.append([mint(), link("cab-0001", "claim-register", "C-9001",
                                   "epistemic-claim"),
                     link("cab-0001", "vm-spine", "sp-fixture-1",
                          "planning-task")])

        def digest(path):
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        before = (digest(self.reg), digest(self.claims_log),
                  digest(self.spine_db))
        api = self.api()
        api.cabinets()
        api.cabinet("cab-0001")
        api.resolve("claim-register", "C-9001")
        api.resolve("vm-spine", "sp-fixture-1")
        api.members("claim-register")
        after = (digest(self.reg), digest(self.claims_log),
                 digest(self.spine_db))
        self.assertEqual(before, after)
        # And the module carries no write path the AST scan knows:
        # a broad scan (imports, open modes, mutation-named calls
        # incl. the pathlib family, os.* calls, sqlite connect
        # targets validated by real URI parsing) — not a grep.
        with open(os.path.join(PKG, "read_api.py"),
                  encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(_write_path_problems(src), [])
        # Negative control: the scan must catch a write path when one
        # is present, or the empty result above proves nothing.
        bad = ("import subprocess\n"
               "open('x', 'w')\n"
               "os.remove('y')\n"
               "sqlite3.connect('file:z.db')\n")
        self.assertTrue(_write_path_problems(bad))

    def test_g_scan_catches_fix2_evasions(self):
        # Fix round 2 (re-review verdict item 3): both evasions Codex
        # EXECUTED against the fix-1 scan must now produce findings,
        # plus the rest of the pathlib mutation family.
        touch = "from pathlib import Path\nPath(TARGET).touch()\n"
        self.assertTrue(_write_path_problems(touch))
        write_text = ("from pathlib import Path\n"
                      "Path(TARGET).write_text('x')\n")
        self.assertTrue(_write_path_problems(write_text))
        write_bytes = ("from pathlib import Path\n"
                       "Path(TARGET).write_bytes(b'x')\n")
        self.assertTrue(_write_path_problems(write_bytes))
        # Codex's exact sqlite counterexample: the real mode is rwc;
        # a decoy comment parameter carries the 'mode=ro' substring
        # that satisfied the old substring check.
        rwc = ("import sqlite3\n"
               "c = sqlite3.connect("
               "f'file:{TARGET}?mode=rwc&comment=mode=ro', uri=True)\n")
        self.assertTrue(_write_path_problems(rwc))
        # Other writable shapes are caught too: a constant rw URI,
        # and a non-URI connect (not provably read-only).
        self.assertTrue(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect('file:x.db?mode=rw', uri=True)\n"))
        self.assertTrue(_write_path_problems(
            "import sqlite3\nsqlite3.connect('plain.db')\n"))
        # Positive control: the production form parses as read-only.
        ro = ("import sqlite3\n"
              "c = sqlite3.connect("
              "f'file:{p}?mode=ro&immutable=1', uri=True)\n")
        self.assertEqual(_write_path_problems(ro), [])

    def test_g_scan_catches_fix3_evasions(self):
        # Fix round 3 (re-review verdict item 3): the two write
        # paths Codex EXECUTED against the fix-2 scan must now
        # produce findings. Both are also executed for real below,
        # against scratch targets in the fixture temp dir, to prove
        # they are genuine write paths and not theoretical shapes.
        # (A) SQLite fragment: in file:{TARGET}#?mode=ro the
        # '?mode=ro' sits in the FRAGMENT — SQLite applies no
        # read-only mode and opens a writable database.
        frag = ("import sqlite3\n"
                "c = sqlite3.connect(f'file:{TARGET}#?mode=ro',"
                " uri=True)\n")
        self.assertTrue(_write_path_problems(frag))
        # Fragment with no query anywhere is likewise not provably
        # read-only.
        self.assertTrue(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect('file:x.db#frag', uri=True)\n"))
        target_a = os.path.join(self.tmp.name, "frag_proof.db")
        conn = sqlite3.connect(f"file:{target_a}#?mode=ro", uri=True)
        conn.execute("CREATE TABLE proof(x)")
        conn.commit()
        conn.close()
        check = sqlite3.connect(f"file:{target_a}?mode=ro&immutable=1",
                                uri=True)
        try:
            self.assertEqual(
                check.execute("SELECT name FROM sqlite_master"
                              " WHERE name='proof'").fetchone()[0],
                "proof")
        finally:
            check.close()
        # (B) pathlib write-mode open: Path.open is an Attribute
        # call; the fix-2 mode check covered only a bare Name open.
        wb = ("from pathlib import Path\n"
              "Path(TARGET).open('wb').close()\n")
        self.assertTrue(_write_path_problems(wb))
        self.assertTrue(_write_path_problems(
            "from pathlib import Path\n"
            "Path(TARGET).open(mode='ab').close()\n"))
        # A mode that is not statically known fails closed.
        self.assertTrue(_write_path_problems(
            "from pathlib import Path\n"
            "Path(TARGET).open(MODE).close()\n"))
        target_b = os.path.join(self.tmp.name, "open_proof.bin")
        with open(target_b, "wb") as f:
            f.write(b"data")
        from pathlib import Path
        Path(target_b).open("wb").close()  # truncates, as Codex ran
        self.assertEqual(os.path.getsize(target_b), 0)
        # Positive controls: read-mode and default pathlib opens
        # are not findings, the production URI form stays accepted,
        # and a fragment AFTER a complete genuine query is inert
        # (SQLite ends the query at '#').
        self.assertEqual(_write_path_problems(
            "from pathlib import Path\n"
            "Path(TARGET).open('rb').close()\n"), [])
        self.assertEqual(_write_path_problems(
            "from pathlib import Path\n"
            "Path(TARGET).open().close()\n"), [])
        self.assertEqual(_write_path_problems(
            "import sqlite3\n"
            "c = sqlite3.connect("
            "f'file:{p}?mode=ro&immutable=1', uri=True)\n"), [])
        self.assertEqual(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect('file:x.db?mode=ro&immutable=1#frag',"
            " uri=True)\n"), [])

    def test_g_scan_catches_fix4_evasions(self):
        # Fix round 4 (re-review verdict item 2, the sole remaining
        # blocker): a `**` unpacking reaches a call as a keyword
        # with arg=None, so the fix-3 checks — which inspected only
        # keywords named 'mode'/'uri' — never saw the mode in
        # Path(TARGET).open(**{'mode': 'wb'}), a snippet Codex
        # EXECUTED for real (a 24-byte scratch file truncated to
        # 0). Rule now: statically literal dict unpackings are
        # expanded and evaluated as ordinary keywords; any
        # unpacking that cannot be statically resolved is itself a
        # finding, on every guarded family (bare open, method
        # .open, sqlite3.connect).
        kwargs_wb = ("from pathlib import Path\n"
                     "Path(TARGET).open(**{'mode': 'wb'}).close()\n")
        self.assertTrue(_write_path_problems(kwargs_wb))
        # Executed for real, like the fix-3 controls: the snippet
        # above truncates a pre-existing scratch file.
        target = os.path.join(self.tmp.name, "kwargs_open_proof.bin")
        with open(target, "wb") as f:
            f.write(b"x" * 24)
        from pathlib import Path
        Path(target).open(**{"mode": "wb"}).close()
        self.assertEqual(os.path.getsize(target), 0)
        # A literal read-mode unpacking expands and is accepted —
        # and the read itself works.
        kwargs_rb = ("from pathlib import Path\n"
                     "Path(TARGET).open(**{'mode': 'rb'}).close()\n")
        self.assertEqual(_write_path_problems(kwargs_rb), [])
        with open(target, "wb") as f:
            f.write(b"payload")
        with Path(target).open(**{"mode": "rb"}) as f:
            self.assertEqual(f.read(), b"payload")
        # An unpacking that cannot be statically resolved fails
        # closed — a bare name, or a call building the dict.
        self.assertTrue(_write_path_problems(
            "from pathlib import Path\n"
            "Path(TARGET).open(**OPTS).close()\n"))
        self.assertTrue(_write_path_problems(
            "from pathlib import Path\n"
            "Path(TARGET).open(**dict(mode='wb')).close()\n"))
        # The same expansion applies to the other guarded
        # families. Bare open: a literal write-mode dict is a
        # finding, a literal read-mode dict is not.
        self.assertTrue(_write_path_problems(
            "open(TARGET, **{'mode': 'w'})\n"))
        self.assertEqual(_write_path_problems(
            "open(TARGET, **{'mode': 'rb'})\n"), [])
        # sqlite3.connect: uri=True arriving through a literal
        # dict is honored — the production read-only URI form is
        # accepted through kwargs, a writable mode is not.
        self.assertEqual(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect('file:x.db?mode=ro&immutable=1',"
            " **{'uri': True})\n"), [])
        self.assertTrue(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect('file:x.db?mode=rw', **{'uri': True})\n"))
        # An unresolvable target is still a finding when uri
        # arrives through kwargs, and an opaque unpacking on a
        # connect fails closed even beside an explicit uri=True.
        self.assertTrue(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect(SOME_NAME, **{'uri': True})\n"))
        self.assertTrue(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect('file:x.db?mode=ro', uri=True,"
            " **OPTS)\n"))

    def test_g_scan_catches_fix5_evasions(self):
        # Fix round 5 (re-review verdict item 1, the sole remaining
        # blocker): _effective_keywords expands a literal `**` dict
        # by its constant string KEYS, but the bare-open branch
        # then judged the mode VALUE with _const_str and treated a
        # non-constant value as no mode at all — so the verdict's
        # executed counterexample
        #     MODE = 'wb'; open(TARGET, **{'mode': MODE})
        # truncated a 24-byte file while the scan returned []. The
        # method .open family already failed closed for the same
        # unknown value; the asymmetry was the defect. Rule now,
        # uniform across bare open() and method .open() through the
        # shared _mode_problem (and audited for sqlite3.connect):
        # a SUPPLIED safety-relevant value that cannot be
        # statically proved safe is a finding, never a skip.
        kwargs_name = ("MODE = 'wb'\n"
                       "open(TARGET, **{'mode': MODE}).close()\n")
        self.assertTrue(_write_path_problems(kwargs_name))
        # Executed for real, mirroring the verdict: the snippet
        # truncates a pre-existing 24-byte scratch file to 0.
        target = os.path.join(self.tmp.name,
                              "kwargs_mode_name_proof.bin")
        with open(target, "wb") as f:
            f.write(b"x" * 24)
        MODE = "wb"
        open(target, **{"mode": MODE}).close()
        self.assertEqual(os.path.getsize(target), 0)
        # The same unprovable mode fails closed in every position:
        # bare open positional, a direct non-constant keyword mode,
        # and the method family through an expanded literal dict
        # (alignment proof for the shared rule).
        self.assertTrue(_write_path_problems("open(TARGET, MODE)\n"))
        self.assertTrue(_write_path_problems(
            "open(TARGET, mode=MODE)\n"))
        self.assertTrue(_write_path_problems(
            "from pathlib import Path\n"
            "Path(TARGET).open(**{'mode': MODE}).close()\n"))
        # Acceptances preserved: a positional constant read mode,
        # and the omitted mode (the default read).
        self.assertEqual(_write_path_problems(
            "open(TARGET, 'rb')\n"), [])
        self.assertEqual(_write_path_problems("open(TARGET)\n"), [])
        # Connect-side audit: a target or uri supplied with an
        # unprovable value already failed closed before this round
        # — an unprovable target is not a proven read-only URI,
        # and a uri that is not the constant True is not uri=True.
        # These controls pin that behavior so the families cannot
        # drift apart again.
        self.assertTrue(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect('file:x.db?mode=ro',"
            " **{'uri': FLAG})\n"))
        self.assertTrue(_write_path_problems(
            "import sqlite3\n"
            "sqlite3.connect(**{'database': SOME_NAME,"
            " 'uri': True})\n"))

    def test_spine_connection_close_is_deterministic(self):
        # Fix round 2 (re-review verdict item 3): the API caches its
        # spine SQLite connection; callers must be able to close it
        # deterministically BEFORE temp-store cleanup. Windows
        # refuses to unlink a DB whose connection is still open
        # (WinError 32); the closest Linux-observable proxy asserted
        # here is that after close() the connection object is gone
        # and the DB file can be renamed and deleted — together with
        # the code path (close() swaps the cached connection out and
        # closes it; fixtures register it via addCleanup, which runs
        # before the temp-dir cleanup).
        self.write_claims([claim("C-9001")])
        row = ("sp-fixture-1", "Fixture task", "QUEUED", "prog",
               "surface", "proxy", "2026-11-02T00:00:00Z", None, None)
        self.write_spine([row])
        self.append([mint(), link("cab-0001", "vm-spine",
                                   "sp-fixture-1", "planning-task")])
        api = self.api()
        api.resolve("vm-spine", "sp-fixture-1")  # opens the connection
        self.assertIsNotNone(api._spine_conn)
        api.close()
        self.assertIsNone(api._spine_conn)
        api.close()  # idempotent: no error, still closed
        self.assertIsNone(api._spine_conn)
        moved = self.spine_db + ".moved"
        os.rename(self.spine_db, moved)
        os.unlink(moved)
        # Context-manager form: the connection closes on exit.
        self.write_spine([row])
        with self.api() as api2:
            api2.resolve("vm-spine", "sp-fixture-1")
            self.assertIsNotNone(api2._spine_conn)
        self.assertIsNone(api2._spine_conn)


class TestExplicitPrivacyPresence(Fixture):
    """Gate-review fix round 1: field PRESENCE is not field ABSENCE.
    A present null / non-string / out-of-vocabulary privacy fails
    closed as unknown — never the namespace default, never a
    TypeError (verdict items 2/5)."""

    def test_null_and_malformed_claim_privacy_fail_closed(self):
        self.write_claims([
            claim("C-9101", privacy=None),
            claim("C-9102", privacy=["house"]),
            claim("C-9103", privacy={"level": "house"}),
            claim("C-9104", privacy=42),
            claim("C-9105", privacy="bogus-level"),
            claim("C-9106", privacy="house")])
        self.append([mint(),
                     link("cab-0001", "claim-register", "C-9101",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9102",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9103",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9104",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9105",
                          "epistemic-claim"),
                     link("cab-0001", "claim-register", "C-9106",
                          "epistemic-claim")])
        api = self.api()
        for cid in ("C-9101", "C-9102", "C-9103", "C-9104", "C-9105"):
            out = api.resolve("claim-register", cid)  # must not raise
            self.assertEqual(out["effective_privacy"], "unknown", cid)
            self.assertEqual(out["privacy_basis"], "explicit-invalid",
                             cid)
            self.assertIsNone(out["content"], cid)
            self.assertEqual(out["content_excluded"],
                             "unknown-privacy-level", cid)
        # A valid explicit value still resolves normally.
        out = api.resolve("claim-register", "C-9106")
        self.assertEqual(out["effective_privacy"], "house")
        self.assertEqual(out["privacy_basis"], "explicit")
        self.assertEqual(out["content"]["id"], "C-9106")
        # One bad member makes the cabinet's combined read unknown,
        # while its structure still lists every member.
        cab = api.cabinet("cab-0001")
        self.assertEqual(len(cab["members"]), 6)
        self.assertEqual(cab["derived_privacy"], "unknown")
        self.assertFalse(cab["content_entitled"])
        self.assertIsNone(cab["contents"])

    def test_null_and_malformed_spine_privacy_fail_closed(self):
        base = ("QUEUED", "prog", "surface", "proxy",
                "2026-11-02T00:00:00Z", None, None)
        self.write_spine_privacy([
            ("sp-null", "Null privacy task") + base + (None,),
            ("sp-int", "Int privacy task") + base + (7,),
            ("sp-oov", "OOV privacy task") + base + ("public",),
            ("sp-ok", "Private task") + base + ("private",)])
        self.append([mint(),
                     link("cab-0001", "vm-spine", "sp-null",
                          "planning-task"),
                     link("cab-0001", "vm-spine", "sp-int",
                          "planning-task"),
                     link("cab-0001", "vm-spine", "sp-oov",
                          "planning-task"),
                     link("cab-0001", "vm-spine", "sp-ok",
                          "planning-task")])
        api = self.api()
        for tid in ("sp-null", "sp-int", "sp-oov"):
            out = api.resolve("vm-spine", tid)  # must not raise
            self.assertEqual(out["effective_privacy"], "unknown", tid)
            self.assertEqual(out["privacy_basis"], "explicit-invalid",
                             tid)
            self.assertIsNone(out["content"], tid)
        out = api.resolve("vm-spine", "sp-ok")
        self.assertEqual(out["effective_privacy"], "private")
        self.assertEqual(out["privacy_basis"], "explicit")
        self.assertEqual(out["content"]["title"], "Private task")


class TestClaimregDependency(Fixture):
    """Gate-review fix round 1: the claimreg dependency is located by
    parameter (every Fixture test already runs against a staged copy
    of the canonical module) and its bytes are verified against the
    deps.json pin before it is executed."""

    def test_pin_mismatch_fails_loudly(self):
        tampered = os.path.join(self.tmp.name, "claimreg_tampered.py")
        with open(self.claimreg_copy, encoding="utf-8") as f:
            src = f.read()
        with open(tampered, "w", encoding="utf-8") as f:
            f.write(src + "\n# tampered copy\n")
        self.write_claims([claim("C-9301")])
        self.append([mint(), link("cab-0001", "claim-register", "C-9301",
                                   "epistemic-claim")])
        api = self.api(claimreg_path=tampered)
        with self.assertRaises(A.ReadAPIError):
            api.resolve("claim-register", "C-9301")

    def test_missing_module_fails_loudly(self):
        self.write_claims([claim("C-9301")])
        api = self.api(claimreg_path=os.path.join(
            self.tmp.name, "no_such_module.py"))
        with self.assertRaises(A.ReadAPIError):
            api.resolve("claim-register", "C-9301")


if __name__ == "__main__":
    unittest.main()
