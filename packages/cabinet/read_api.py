#!/usr/bin/env python3
"""read_api.py — the Phase 3 read API: one read surface across the
memory families (Cabinet namespaces) with per-namespace rights.

Gate definition (FILING_CABINET_PLAN_V1 §8 Phase 3): one read API
across families with per-namespace rights; NO raw DB merge. This module
is that surface for the Cabinet layer. It reads:

- the Cabinet Registrar's accepted fold (`docs/cabinet-registry/
  REGISTRY.jsonl`, via registrar.py's own read/fold functions — the
  fold is the membership source of truth, spec §4);
- native claim records from the VM claim register, through the live
  claimreg module's read paths (load_events / fold / forget_tombstones).
  The claimreg module is an EXTERNAL dependency with one canonical
  source (it is not vendored here — the claim fold must not fork);
  its location is parameterizable (constructor `claimreg_path`, CLI
  `--claimreg-module`, env `CABINET_CLAIMREG_PATH`; default the
  canonical VM path) and its sha256 is pinned in deps.json beside
  this module — the loader verifies the pin before executing the
  module and fails loudly on a missing file or a pin mismatch;
- native task records from the VM spine read-model, opened read-only
  (`mode=ro&immutable=1` — a main-checkpoint read, the same scope the
  Step 4/5 censuses used). The spine `tasks` table carries no `privacy`
  column today (verified 2026-11-05, STEP3_F02_DEMONSTRATION); an
  explicit field would be picked up from the row if one ever appears;
- HOME namespaces (`home-runloop`, `claim-service` in registry spelling)
  are served REGISTRY-ONLY per spec §5.1/§5.3/§5.4: membership and
  derived rights, never content — content stays with the owning systems
  on HOME, and an explicit `privacy` field on a HOME record is therefore
  unobserved from here (the Step 2 F02 demonstration scanned the HOME
  records and found none).

Coverage bound (PHASE3_GAP_REPORT G5): Memory Rooms deployment B
(standalone `rooms.sqlite` on HOME, owner unknown) is served by no
consumer and is NOT part of this API's families. It is named here as an
excluded family, not silently omitted.

Rights model (contracts/admission-privacy-forget.md rule 4; spec §6):

- a member's effective level is its record's explicit `privacy` field
  when present (field PRESENCE is tracked separately from its value:
  a present value that is null, not a string, or outside the
  contract's level set fails closed — unknown, never house, never an
  exception; only an ABSENT field may inherit the namespace default);
- otherwise the namespace default applies. Ratified/adopted defaults:
  claim-register -> house (C1, DECISION_2026-11-05_UNMARKED_DEFAULT_
  HOUSE, commit 41c90c6); home-runloop and home-claim-service -> house
  (DECISION_2026-11-05_HOME_NAMESPACES_HOUSE_DEFAULT, commit 2ecdb80);
  vm-spine -> house (ADOPTION_2026-11-05_VMSPINE_HOUSE_DEFAULT,
  sha256 881aa8dc..., commit 69d8c8c);
- a namespace with NO default and no explicit field yields `unknown`,
  and unknown = NO read entitlement (the permanent form of ruling 6(a)'s
  interim rule in CODEX_REVIEW_STEP3_2026-11-05): the member's content
  is excluded and the exclusion is reported; a cabinet holding an
  unknown member still lists its membership structure (structure is
  registry data) but its combined content read is denied;
- a cabinet's derived level is the strictest effective level among its
  active members (house < private < secret-pointer; unknown is
  strictest of all for entitlement purposes);
- forgotten members never appear as readable content: registry-side
  forgets (forget-consequence UNLINKs) remove the membership from the
  fold itself, and a claim-register member forgotten in its own ledger
  (rule 6 tombstone) is reported as a tombstone and purged from cabinet
  content and derived-level computation even if a registry LINK were
  still active. On EVERY output surface a forgotten member appears
  ONLY as a tombstone — (system, ID, forget timestamp, actor), the
  rule-6 closed set; its privacy level, basis, kind and registry
  linkage are never published (gate re-review fix round 2, item 2);
- invalidated (superseded) claims are not retrievable by default
  (contract rule 2; spec §5.1) — their membership still resolves, their
  content does not.

READ-ONLY: this module never appends, projects, or mutates any store.
It calls only registrar read functions (read_registry / verify_chain /
fold_events / forgotten_members / head_of), claimreg read functions,
and read-only SQLite. There is deliberately no write path to wrap.

Usage (CLI):
  python3 -m packages.cabinet.read_api cabinets
  python3 -m packages.cabinet.read_api cabinet --id cab-0022
  python3 -m packages.cabinet.read_api resolve --system claim-register --id C-0140
  python3 -m packages.cabinet.read_api members --namespace vm-spine
Options: --registry PATH --claims-log PATH --spine-db PATH
--claimreg-module PATH (defaults are the live stores; the overrides
exist for fixtures/tests and for staged environments off the VM).
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:
    from . import registrar as R
except ImportError:  # direct-module context (dir on sys.path)
    import registrar as R

REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_REGISTRY = os.path.join(
    REPO, "docs", "cabinet-registry", "REGISTRY.jsonl")
CLAIMREG_PATH = os.path.expanduser(
    "~/workspace/pai-continuity/claim-register/claimreg.py")
# The claimreg dependency is parameterizable (gate-review fix round 1):
# constructor argument > env var > canonical default above. Its bytes
# are pinned in deps.json (the module is NOT vendored — one canonical
# fold source); the loader verifies the pin before executing it.
ENV_CLAIMREG_PATH = "CABINET_CLAIMREG_PATH"
DEPS_PIN_PATH = os.path.join(_HERE, "deps.json")
DEFAULT_SPINE_DB = os.path.expanduser(
    "~/workspace/pai-continuity/spine/build/shadow-1a/runtime/spine.db")

# Contract levels, loosest to strictest (admission contract rule 4).
LEVELS = ("house", "private", "secret-pointer")
_STRICTNESS = {lvl: i for i, lvl in enumerate(LEVELS)}

# Registry system -> contract namespace (spec §5.4: the registry spells
# the HOME Claim Service system "claim-service"; the contract's
# namespace is "home-claim-service"). Identity for the other three.
CONTRACT_NAMESPACE = {
    "vm-spine": "vm-spine",
    "claim-register": "claim-register",
    "home-runloop": "home-runloop",
    "claim-service": "home-claim-service",
}
# Inverse aliases accepted on input (contract name -> registry system).
SYSTEM_ALIASES = {"home-claim-service": "claim-service"}

# Ratified/adopted unmarked-record defaults (see module docstring for
# the decision records and commits). Keyed by REGISTRY system name.
NAMESPACE_DEFAULTS = {
    "claim-register": "house",
    "home-runloop": "house",
    "claim-service": "house",
    "vm-spine": "house",
}

# Native spine task fields served as content (a read-model projection;
# the registry never writes to the spine, spec §5.2).
_SPINE_CONTENT_FIELDS = (
    "task_id", "title", "state", "program", "owner_surface",
    "registration_class", "created_at", "closed_at", "deadline_at")


class ReadAPIError(Exception):
    pass


def normalize_system(system):
    return SYSTEM_ALIASES.get(system, system)


def _claimreg_pin():
    """The sha256 pinned for the canonical claimreg module in
    deps.json, or None when no pin is configured."""
    try:
        with open(DEPS_PIN_PATH, encoding="utf-8") as f:
            deps = json.load(f)
        pin = deps.get("claimreg", {}).get("sha256")
        return pin if isinstance(pin, str) else None
    except (OSError, ValueError):
        return None


def _resolve_claimreg_path(explicit=None):
    """claimreg module location: explicit argument >
    $CABINET_CLAIMREG_PATH > the canonical VM path."""
    if explicit:
        return explicit
    env = os.environ.get(ENV_CLAIMREG_PATH)
    if env:
        return env
    return CLAIMREG_PATH


def _load_claimreg(claimreg_path, claims_log_path):
    """Load the claimreg module (its read paths only) from the given
    location, verifying the deps.json sha256 pin first when one is
    configured; for fixtures, point its LOG at the given claims.jsonl.
    Fails loudly (ReadAPIError) on a missing file or a pin mismatch —
    never silently substitutes another module."""
    path = _resolve_claimreg_path(claimreg_path)
    if not os.path.isfile(path):
        raise ReadAPIError(
            f"claimreg module not found at {path!r} (point at the"
            f" canonical module via claimreg_path / --claimreg-module"
            f" / ${ENV_CLAIMREG_PATH})")
    pin = _claimreg_pin()
    if pin is not None:
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if digest != pin:
            raise ReadAPIError(
                f"claimreg module at {path!r} does not match the"
                f" deps.json pin (sha256 {digest} != {pin}); refusing"
                " to execute an unpinned claim fold")
    spec = importlib.util.spec_from_file_location(
        "cabinet_read_api_claimreg", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if claims_log_path:
        mod.LOG = claims_log_path
    return mod


# Contract rule 6: the ONLY fields of a forgotten record that may
# appear on an operative surface (tombstone-grade). Everything else —
# privacy level, basis, kind, registry linkage — is purged from every
# output (gate re-review fix round 2, item 2).
_TOMBSTONE_OPTIONAL_FIELDS = ("forget_at", "actor")


def _tombstone_public(tombstone, system, native_id):
    """Project an internal tombstone onto the rule-6 closed field
    set: (system, ID) always; forget timestamp / actor when recorded.
    Internal annotations (e.g. the registry-side 'source' note) are
    deliberately dropped."""
    out = {"system": system, "id": native_id}
    if tombstone:
        for key in _TOMBSTONE_OPTIONAL_FIELDS:
            if tombstone.get(key) is not None:
                out[key] = tombstone[key]
    return out


def _purged_entry(system, native_id, tombstone):
    """The only output shape in which a forgotten member may appear,
    on any surface (cabinet purged_members, members listings,
    resolve): tombstone-grade fields and nothing else."""
    return {"system": system,
            "namespace": CONTRACT_NAMESPACE[system],
            "id": native_id,
            "forgotten": True,
            "tombstone": _tombstone_public(tombstone, system, native_id)}


class ReadAPI:
    """One read surface over the Cabinet fold + reachable native stores.

    All state is loaded once at construction and treated as immutable
    thereafter; nothing here writes anywhere.
    """

    def __init__(self, registry_path=DEFAULT_REGISTRY, claims_log_path=None,
                 spine_db_path=DEFAULT_SPINE_DB, namespace_defaults=None,
                 claimreg_path=None):
        lines, events = R.read_registry(registry_path)
        R.verify_chain(lines, events)
        self._state = R.fold_events(events)
        self._forgotten_registry = R.forgotten_members(events)
        self.registry_head = R.head_of(lines) if lines else R.GENESIS_HASH
        self.registry_lines = len(lines)
        self._defaults = dict(NAMESPACE_DEFAULTS if namespace_defaults
                              is None else namespace_defaults)
        # Member index built from the cabinets section of the fold —
        # never by splitting the fold's "system:id" member keys (native
        # IDs themselves contain ':').
        self._index = {}
        for cab, cdata in self._state["cabinets"].items():
            for m in cdata["members"]:
                self._index.setdefault((m["system"], m["id"]), []).append({
                    "cabinet_id": cab, "relation": m["relation"],
                    "registry_line": m["registry_line"], "kind": m["kind"]})
        for lst in self._index.values():
            lst.sort(key=lambda e: e["registry_line"])
        # Native claim store (lazy): {claim_id: claim dict} + tombstones.
        self._claims_log_path = claims_log_path
        self.claimreg_path = _resolve_claimreg_path(claimreg_path)
        self._claims = None
        self._claim_tombstones = None
        # Native spine store (lazy read-only connection).
        self._spine_db_path = spine_db_path
        self._spine_conn = None
        self._spine_unavailable = None

    # ------------------------------------------------ lifecycle

    def close(self):
        """Deterministically release the cached spine connection.
        Idempotent. That connection's file handle is the only OS
        resource this API holds — and the handle Windows refuses to
        unlink while open (the fix-1 re-review's four fixture
        cleanup errors, WinError 32); everything else is immutable
        in-memory state. After close(), a later read simply reopens
        the connection lazily."""
        conn, self._spine_conn = self._spine_conn, None
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # ------------------------------------------------ native stores

    def _load_claims(self):
        if self._claims is None:
            mod = _load_claimreg(self.claimreg_path, self._claims_log_path)
            events = mod.load_events()
            self._claims = {}
            for claim in mod.fold(events):
                self._claims[claim["id"]] = claim
            self._claim_tombstones = mod.forget_tombstones(events)
        return self._claims, self._claim_tombstones

    def _spine_row(self, task_id):
        """The spine task row as a dict, or None (absent or the store
        cannot be opened read-only — reported, never faked)."""
        if self._spine_unavailable is not None:
            return None
        if self._spine_conn is None:
            path = self._spine_db_path
            if not path or not os.path.exists(path):
                self._spine_unavailable = "spine-db-not-found"
                return None
            try:
                self._spine_conn = sqlite3.connect(
                    f"file:{path}?mode=ro&immutable=1", uri=True)
                self._spine_conn.row_factory = sqlite3.Row
            except sqlite3.Error as e:
                self._spine_unavailable = f"spine-open-failed: {e}"
                return None
        try:
            row = self._spine_conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,)).fetchone()
        except sqlite3.Error as e:
            self._spine_unavailable = f"spine-read-failed: {e}"
            return None
        return dict(row) if row is not None else None

    # ------------------------------------------------ rights core

    def _explicit_privacy(self, system, native_id):
        """(present, value) for the record's own `privacy` field.
        Presence is tracked separately from the value: a field present
        with a null or malformed value is NOT absent and must never
        inherit the namespace default. HOME namespaces are
        registry-only: their records are not read from here, so the
        field is unobserved and (False, None) is returned."""
        if system == "claim-register":
            claims, _ = self._load_claims()
            claim = claims.get(native_id)
            if claim is None or "privacy" not in claim:
                return False, None
            return True, claim["privacy"]
        if system == "vm-spine":
            row = self._spine_row(native_id)
            if row is None or "privacy" not in row:
                return False, None
            return True, row["privacy"]
        return False, None

    def _effective_level(self, system, native_id):
        """(level_or_None, basis). level None == unknown == no read
        entitlement. A PRESENT explicit value that is null, not a
        string, or outside the contract level set fails closed as
        unknown with basis 'explicit-invalid'; only an ABSENT field
        inherits the namespace default."""
        present, explicit = self._explicit_privacy(system, native_id)
        if present:
            if isinstance(explicit, str) and explicit in _STRICTNESS:
                return explicit, "explicit"
            return None, "explicit-invalid"
        default = self._defaults.get(system)
        if default is not None:
            return default, "namespace-default"
        return None, "none"

    def _forgotten(self, system, native_id):
        """(forgotten_bool, tombstone_dict_or_None). Registry-side
        forgets already removed the membership from the fold; the
        tombstone is reconstructed from the member's own store when it
        has one (claim register), else reported registry-side."""
        reg_forgotten = (system, native_id) in self._forgotten_registry
        if system == "claim-register":
            _, tombstones = self._load_claims()
            tomb = tombstones.get(native_id)
            if tomb is not None:
                return True, tomb
        if reg_forgotten:
            return True, {"system": system, "id": native_id,
                          "source": "registry forget-consequence UNLINK"}
        return False, None

    def _content(self, system, native_id):
        """(content_or_None, note_or_None, exclusion_or_None) for a
        member already known to be entitled (not forgotten, level
        known). Native-store-level bars (invalidated claims) apply
        here, per contract rule 2."""
        if system == "claim-register":
            claims, _ = self._load_claims()
            claim = claims.get(native_id)
            if claim is None:
                return None, "not-in-live-claim-fold", None
            if claim.get("status") == "superseded":
                return None, None, "invalidated-not-retrievable-by-default"
            return dict(claim), None, None
        if system == "vm-spine":
            row = self._spine_row(native_id)
            if row is None:
                note = self._spine_unavailable or "not-in-spine-tasks"
                return None, note, None
            return {k: row.get(k) for k in _SPINE_CONTENT_FIELDS}, None, None
        # home-runloop / claim-service: registry-only (spec §5.1).
        return None, "registry-only: content served by the owning " \
                     "system on HOME (spec §5.1)", None

    # ------------------------------------------------ operations

    def resolve(self, system, native_id):
        """One member across the families: its cabinets and roles, its
        effective privacy level, its cabinets' derived levels, and its
        native content when entitled."""
        system = normalize_system(system)
        if system not in CONTRACT_NAMESPACE:
            raise ReadAPIError(f"unknown system: {system!r}")
        forgotten, tombstone = self._forgotten(system, native_id)
        if forgotten:
            # Rule 6: a forgotten record surfaces ONLY as a
            # tombstone, in the single shared purged-entry shape —
            # the same object cabinet() and members() publish. Its
            # privacy level and basis are not even computed here,
            # and no kind, linkage, or content metadata is added
            # (gate re-review fix rounds 2–3, item 1/2: an earlier
            # hand-built variant added content/content_excluded
            # keys; the shared shape is the contract).
            return _purged_entry(system, native_id, tombstone)
        entries = self._index.get((system, native_id), [])
        level, basis = self._effective_level(system, native_id)
        out = {
            "system": system,
            "namespace": CONTRACT_NAMESPACE[system],
            "id": native_id,
            "kind": entries[0]["kind"] if entries else None,
            "member": bool(entries),
            "cabinets": [
                {"cabinet_id": e["cabinet_id"], "relation": e["relation"],
                 "registry_line": e["registry_line"],
                 "cabinet_derived_privacy":
                     self._derived_level(e["cabinet_id"])}
                for e in entries],
            "effective_privacy": level if level is not None else "unknown",
            "privacy_basis": basis,
            "forgotten": False,
        }
        if level is None:
            out["content"] = None
            out["content_excluded"] = "unknown-privacy-level"
            return out
        content, note, exclusion = self._content(system, native_id)
        out["content"] = content
        if note is not None:
            out["content_note"] = note
        if exclusion is not None:
            out["content_excluded"] = exclusion
        return out

    def _member_summary(self, system, native_id, kind):
        level, basis = self._effective_level(system, native_id)
        forgotten, _ = self._forgotten(system, native_id)
        entitled = (not forgotten and level is not None)
        if entitled and system == "claim-register":
            claims, _ = self._load_claims()
            claim = claims.get(native_id)
            if claim is not None and claim.get("status") == "superseded":
                entitled = False
        return {"system": system, "namespace": CONTRACT_NAMESPACE[system],
                "id": native_id, "kind": kind,
                "effective_privacy":
                    level if level is not None else "unknown",
                "privacy_basis": basis, "forgotten": forgotten,
                "content_entitled": entitled}

    def _cabinet_members(self, cab_id):
        cdata = self._state["cabinets"].get(cab_id)
        if cdata is None:
            return None
        kept, purged = [], []
        for m in cdata["members"]:
            forgotten, tombstone = self._forgotten(m["system"], m["id"])
            if forgotten:
                # Tombstone-only: the forgotten member's privacy,
                # basis, kind and linkage never reach the output
                # (gate re-review fix round 2, item 2).
                purged.append(_purged_entry(m["system"], m["id"],
                                            tombstone))
                continue
            summary = self._member_summary(m["system"], m["id"], m["kind"])
            summary["relation"] = m["relation"]
            summary["registry_line"] = m["registry_line"]
            kept.append(summary)
        return cdata, kept, purged

    def _derived_level(self, cab_id):
        """Strictest effective level among a cabinet's active,
        non-forgotten members; 'unknown' if any member's level is
        unknown (or the cabinet has no live members)."""
        got = self._cabinet_members(cab_id)
        if got is None:
            return "unknown"
        _, kept, _ = got
        if not kept:
            return "unknown"
        worst = -1
        for s in kept:
            lvl = s["effective_privacy"]
            if lvl == "unknown":
                return "unknown"
            worst = max(worst, _STRICTNESS[lvl])
        return LEVELS[worst]

    def cabinet(self, cab_id):
        """A work area: membership structure (always listable — it is
        registry data), per-member levels, the derived level, and
        member contents only when the combined read is entitled."""
        got = self._cabinet_members(cab_id)
        if got is None:
            return {"cabinet_id": cab_id, "found": False}
        cdata, kept, purged = got
        derived = self._derived_level(cab_id)
        entitled = derived != "unknown"
        out = {
            "cabinet_id": cab_id,
            "found": True,
            "mint_line": cdata["mint_line"],
            "derived_privacy": derived,
            "content_entitled": entitled,
            "members": kept,
        }
        if purged:
            out["purged_members"] = purged
        if not entitled:
            out["contents"] = None
            out["contents_excluded"] = \
                "cabinet-derived-privacy-unknown: no entitled combined " \
                "read (a member's level is unknown, or no live members " \
                "remain)"
            return out
        contents = {}
        for s in kept:
            if not s["content_entitled"]:
                continue
            content, _, _ = self._content(s["system"], s["id"])
            if content is not None:
                contents[f"{s['system']}:{s['id']}"] = content
        out["contents"] = contents
        return out

    def members(self, namespace):
        """All members of one namespace (registry system name, or the
        contract alias 'home-claim-service'), with cabinets and levels.
        Structure + levels only — use resolve() for content."""
        system = normalize_system(namespace)
        if system not in CONTRACT_NAMESPACE:
            raise ReadAPIError(f"unknown namespace: {namespace!r}")
        out = []
        for (sys_, mid), entries in sorted(self._index.items()):
            if sys_ != system:
                continue
            forgotten, tombstone = self._forgotten(sys_, mid)
            if forgotten:
                out.append(_purged_entry(sys_, mid, tombstone))
                continue
            summary = self._member_summary(sys_, mid, entries[0]["kind"])
            summary["cabinets"] = [
                {"cabinet_id": e["cabinet_id"], "relation": e["relation"],
                 "registry_line": e["registry_line"]} for e in entries]
            out.append(summary)
        return {"system": system, "namespace": CONTRACT_NAMESPACE[system],
                "count": len(out), "members": out}

    def cabinets(self):
        """Every cabinet with its derived privacy level."""
        out = []
        for cab_id in sorted(self._state["cabinets"],
                             key=lambda c: int(c[4:])):
            cdata = self._state["cabinets"][cab_id]
            derived = self._derived_level(cab_id)
            out.append({
                "cabinet_id": cab_id, "mint_line": cdata["mint_line"],
                "member_count": len(cdata["members"]),
                "derived_privacy": derived,
                "content_entitled": derived != "unknown"})
        return {"registry_head": self.registry_head,
                "registry_lines": self.registry_lines,
                "count": len(out), "cabinets": out}


# ------------------------------------------------------------ CLI

def _add_store_opts(p):
    p.add_argument("--registry", default=DEFAULT_REGISTRY)
    p.add_argument("--claims-log", default=None,
                   help="claims.jsonl path (default: the live register)")
    p.add_argument("--spine-db", default=DEFAULT_SPINE_DB)
    p.add_argument("--claimreg-module", default=None,
                   help="path to the canonical claimreg.py (default:"
                        " $CABINET_CLAIMREG_PATH or the canonical VM"
                        " path; sha256 verified against deps.json)")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="read_api", description="Phase 3 Cabinet read API (read-only)")
    sub = ap.add_subparsers(dest="op", required=True)
    p = sub.add_parser("resolve"); _add_store_opts(p)
    p.add_argument("--system", required=True)
    p.add_argument("--id", required=True)
    p = sub.add_parser("cabinet"); _add_store_opts(p)
    p.add_argument("--id", required=True)
    p = sub.add_parser("members"); _add_store_opts(p)
    p.add_argument("--namespace", required=True)
    p = sub.add_parser("cabinets"); _add_store_opts(p)
    args = ap.parse_args(argv)
    try:
        with ReadAPI(registry_path=args.registry,
                     claims_log_path=args.claims_log,
                     spine_db_path=args.spine_db,
                     claimreg_path=args.claimreg_module) as api:
            if args.op == "resolve":
                out = api.resolve(args.system, args.id)
            elif args.op == "cabinet":
                out = api.cabinet(args.id)
                if not out.get("found"):
                    print(json.dumps(out, ensure_ascii=False, indent=1,
                                     sort_keys=True))
                    return 2
            elif args.op == "members":
                out = api.members(args.namespace)
            else:
                out = api.cabinets()
    except (ReadAPIError, R.RegistryError) as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False, indent=1, sort_keys=True))
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
