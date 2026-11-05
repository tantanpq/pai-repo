#!/usr/bin/env python3
"""PAI retrieval — deterministic indexer (Phase 2, pai-repo).

Port of the pai-query-layer pilot indexer (Codex PASS 2026-11-05) into the
repo, conformed to the repo contracts, plus the F4 goal/tracked-item source
kind. Sources are READ-ONLY; the index is a rebuildable catalogue, never a
source of truth.

Contract conformance:
  - contracts/identity.md: record IDs are namespaced by owning system
    (`claim-register:`, `vm-spine:`, `vm-workspace:`, `muse-memory:`,
    `goal-workspaces:`); content_hash detects change only, never identity;
    every record carries a `path#line` provenance anchor — a record without
    a resolvable anchor is an orphan and is dropped + counted (rule 6,
    mirroring Knowledge Room's ACTIVE-evidence requirement).
  - contracts/lifecycle.md: records carry `lifecycle` (unadmitted /
    admitted / invalidated / superseded / expired), `valid_at` /
    `invalid_at` where the source provides them.
  - contracts/admission-privacy-forget.md: every record carries exactly one
    `namespace` and a `privacy` level that travels into the index.

Sources:
  1. Claim register  ~/workspace/pai-continuity/claim-register/claims.jsonl (admitted)
                     ~/workspace/pai-continuity/claim-register/inbox.jsonl  (UNADMITTED)
  2. Spine tasks     ~/workspace/pai-continuity/spine/build/shadow-1a/runtime/spine.db
                     (only non-UNTRACKED tasks; read via snapshot copy —
                      WAL-aware content fingerprint, never opened in place)
  3. STATUS.md set   glob ~/workspace/**/STATUS.md, deduplicated by content
                     hash; goal workspaces are EXCLUDED here (owned by 5)
  4. MEMORY.md       ~/MEMORY.md
  5. Goal workspaces ~/workspace/goals/<slug>/GOAL.md and .../STATUS.md (F4)

Deterministic: same inputs -> same output bytes, except manifest/indexed_at
timestamps.

Usage: python3 retrieval_index.py [--out-dir DIR]
"""
import argparse
import contextlib
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
WORKSPACE = os.path.join(HOME, "workspace")
CLAIMS = os.path.join(WORKSPACE, "pai-continuity/claim-register/claims.jsonl")
INBOX = os.path.join(WORKSPACE, "pai-continuity/claim-register/inbox.jsonl")
SPINE_DB = os.path.join(WORKSPACE, "pai-continuity/spine/build/shadow-1a/runtime/spine.db")
MEMORY = os.path.join(HOME, "MEMORY.md")
GOALS_DIR = os.path.join(WORKSPACE, "goals")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_meta(path):
    st = os.stat(path)
    return {"sha256": sha256_file(path), "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
            "bytes": st.st_size}


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(s):
    return "-".join(str(s or "").lower().replace("/", " ").replace("_", " ").split())


# ---------------------------------------------------------- SQLite sources
# Ported unchanged from the pilot (Codex-reviewed): SQLite sources are never
# opened in place. Opening even a mode=ro WAL-mode database can create
# -wal/-shm sidecars in the source directory, and hashing only the main file
# misses committed changes that still live in the WAL. Instead, the main file
# and any -wal file are copied to a short-lived snapshot under the index
# output directory. Freshness is the deterministic content fingerprint of
# the indexed `tasks` table in that snapshot.
def _hash_sqlite_value(h, value):
    if value is None:
        h.update(b"N;")
    elif isinstance(value, bytes):
        h.update(b"B" + len(value).to_bytes(8, "big") + value + b";")
    elif isinstance(value, int):
        h.update(f"I{value};".encode())
    elif isinstance(value, float):
        h.update(f"F{value!r};".encode())
    else:
        raw = str(value).encode("utf-8")
        h.update(b"T" + len(raw).to_bytes(8, "big") + raw + b";")


def _fingerprint_tasks_copy(copy_path):
    h = hashlib.sha256()
    h.update(b"pai-sqlite-content-v1\0tasks\0")
    con = sqlite3.connect(copy_path)
    try:
        schema = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if schema is None:
            h.update(b"missing-table")
            return h.hexdigest()
        _hash_sqlite_value(h, schema[0])
        columns = con.execute("PRAGMA table_info(tasks)").fetchall()
        for column in columns:
            for value in column:
                _hash_sqlite_value(h, value)
        for row in con.execute("SELECT * FROM tasks ORDER BY task_id"):
            h.update(b"row\0")
            for value in row:
                _hash_sqlite_value(h, value)
    finally:
        con.close()
    return h.hexdigest()


@contextlib.contextmanager
def _sqlite_snapshot(path, parent_dir):
    os.makedirs(parent_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sqlite-snapshot-", dir=parent_dir) as td:
        copy_path = os.path.join(td, os.path.basename(path))
        shutil.copyfile(path, copy_path)
        wal_path = path + "-wal"
        if os.path.exists(wal_path):
            shutil.copyfile(wal_path, copy_path + "-wal")
        yield copy_path


def _read_spine_snapshot(path, staging_parent):
    with _sqlite_snapshot(path, staging_parent) as copy_path:
        content_sha = _fingerprint_tasks_copy(copy_path)
        con = sqlite3.connect(copy_path)
        try:
            total = con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            rows = con.execute(
                "SELECT task_id, title, state, program, owner_surface FROM tasks "
                "WHERE state != 'UNTRACKED' ORDER BY task_id").fetchall()
        finally:
            con.close()
    st = os.stat(path)
    wal_path = path + "-wal"
    wal_bytes = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
    meta = {
        "sha256": content_sha,
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        "bytes": st.st_size + wal_bytes,
        "freshness_mode": "sqlite-content-v1",
        "content_sha256": content_sha,
        "file_sha256": sha256_file(path),
        "wal_sha256": sha256_file(wal_path) if os.path.exists(wal_path) else None,
    }
    return rows, total, meta


# ---------------------------------------------------------------- records
# Plan SS5 tag axes: domain: / kind: / state: / src: (controlled vocabulary).
KIND_TAG = {"claim": "fact", "task": "state", "status": "state",
            "memory": "fact", "goal": "state"}
SRC_TAG = {"claim": "claim-register", "task": "spine", "status": "vm-workspace",
           "memory": "muse-memory", "goal": "goal-workspaces"}
NAMESPACE = {"claim": "room:decisions", "task": "owner:vm-spine",
             "status": "room:work-state", "memory": "owner:muse-memory",
             "goal": "owner:goal-workspaces"}
SOURCE_SYSTEM = {"claim": "claim-register", "task": "vm-spine",
                 "status": "vm-workspace", "memory": "muse-memory",
                 "goal": "goal-workspaces"}


def base_record(local_id, kind, domain, text, source_path, anchor, meta, indexed_at,
                lifecycle="admitted", privacy="house", valid_at=None, invalid_at=None):
    system = SOURCE_SYSTEM[kind]
    tags = [f"domain:{slugify(domain)}", f"kind:{KIND_TAG[kind]}", f"src:{SRC_TAG[kind]}"]
    return {
        "id": f"{system}:{local_id}",
        "source_system": system,
        "namespace": NAMESPACE[kind],
        "kind": kind,
        "domain": domain,
        "tags": tags,
        "text": text,
        "content_hash": content_hash(text),
        "source_path": source_path,
        "source_anchor": anchor,
        "source_mtime": meta["mtime"],
        "source_sha256": meta["sha256"],
        "lifecycle": lifecycle,
        "valid_at": valid_at,
        "invalid_at": invalid_at,
        "privacy": privacy,
        "evidence_against": [],
        # Knowledge Room applicability fields (validity.py gate inputs).
        # House sources today scope to project PAI and their own domain;
        # environment/release scopes stay empty (unconstrained) unless a
        # source populates them.
        "validity_project": "PAI",
        "validity_domains": [domain] if domain else [],
        "validity_environments": [],
        "validity_releases": [],
        "indexed_at": indexed_at,
    }


def admit(records, rec, orphans):
    """Identity contract rule 6 + Knowledge Room ACTIVE-evidence rule: a
    record without a resolvable source anchor is an orphan and MUST NOT be
    admitted. Counted, never silently dropped."""
    if not rec.get("source_path") or not rec.get("source_anchor"):
        orphans.append(rec.get("id"))
        return
    records.append(rec)


# ---------------------------------------------------------------- claims
def _register_events(path):
    """Pass 1 over a register file: collect INVALIDATE events by claim id,
    and (physical_lineno, parsed object) pairs for pass 2 — anchors must be
    true file line numbers (identity contract: anchors must resolve)."""
    invalidated = {}
    lines = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            lines.append((lineno, obj))
            if isinstance(obj, dict) and obj.get("event") == "INVALIDATE" and obj.get("id"):
                invalidated[obj["id"]] = obj
    return invalidated, lines


def index_claims(path, admitted_source, indexed_at, records, orphans):
    meta = file_meta(path)
    invalidated, lines = _register_events(path)
    n = 0
    for lineno, obj in lines:
        if not isinstance(obj, dict) or obj.get("event") == "INVALIDATE":
            continue
        claim = obj.get("claim")
        if not isinstance(claim, dict):
            claim = obj
        text = (claim.get("claim") or "").strip()
        if not text:
            continue
        cid = claim.get("id")
        local = cid if cid else f"inbox:L{lineno}"
        lifecycle = "admitted" if admitted_source else "unadmitted"
        invalid_at = None
        extra = {}
        if cid and cid in invalidated:
            lifecycle = "invalidated"
            ev = invalidated[cid]
            invalid_at = ev.get("date") or ev.get("ts")
            extra["invalidated_by"] = ev.get("by")
        elif claim.get("superseded_by"):
            lifecycle = "superseded"
            extra["superseded_by"] = claim["superseded_by"]
        rec = base_record(local, "claim", claim.get("entity") or "(no entity)", text,
                          path, f"line {lineno}", meta, indexed_at,
                          lifecycle=lifecycle, valid_at=claim.get("date"),
                          invalid_at=invalid_at)
        rec["admitted"] = admitted_source and lifecycle == "admitted"
        rec["claim_id"] = cid
        rec["claim_status"] = claim.get("status")
        rec["claim_type"] = claim.get("type")
        if claim.get("type"):
            rec["tags"][1] = "kind:decision" if claim["type"] == "DECISION" else "kind:fact"
        if isinstance(claim.get("evidence_against"), list):
            rec["evidence_against"] = claim["evidence_against"]
        rec.update(extra)
        admit(records, rec, orphans)
        n += 1
    return n, meta


# ---------------------------------------------------------------- spine
def index_spine(path, indexed_at, records, orphans, staging_parent):
    rows, total, meta = _read_spine_snapshot(path, staging_parent)
    for task_id, title, state, program, owner in rows:
        text = f"{title} [state={state}]"
        if program:
            text += f" [program={program}]"
        rec = base_record(str(task_id), "task", program or "spine", text,
                          path, f"tasks.task_id={task_id}", meta, indexed_at)
        rec["task_state"] = state
        admit(records, rec, orphans)
    info = {"total_tasks": total, "indexed_tasks": len(rows),
            "excluded_untracked": total - len(rows)}
    return len(rows), meta, info


# ---------------------------------------------------------------- markdown chunking
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
BULLET_RE = re.compile(r"^-\s+")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def chunk_markdown(text):
    """Yield (start_line, anchor_label, chunk_text) per heading-section preamble
    or top-level bullet block. Deterministic, line-based. (Pilot, unchanged.)
    Phase 2 addition: a file whose whole body is <=600 chars is indexed as
    ONE record — splitting a tiny file into heading chunks creates a
    ranking trap (the title chunk outranks the content chunk) while the
    whole file is already snippet-sized context."""
    text = COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    if len(text.strip()) <= 600:
        first = ""
        for raw in text.split("\n"):
            hm = HEADING_RE.match(raw.rstrip())
            if hm:
                first = hm.group(2).strip()
                break
        return [(1, f"heading: {first}" if first else "", text.strip())]
    lines = text.split("\n")
    chunks = []
    cur = None
    heading = ""
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        hm = HEADING_RE.match(line)
        if hm:
            if cur:
                chunks.append(cur)
            heading = hm.group(2).strip()
            cur = [i, f"heading: {heading}", [line]]
            continue
        if BULLET_RE.match(line):
            if cur:
                chunks.append(cur)
            label = line.lstrip("- ").strip()
            label = re.sub(r"\*\*", "", label)[:80]
            cur = [i, f"{heading} · {label}" if heading else label, [line]]
            continue
        if cur is not None:
            cur[2].append(line)
    if cur:
        chunks.append(cur)
    out = []
    for start, label, block in chunks:
        body = "\n".join(block).strip()
        if len(body) >= 15:
            out.append((start, label, body))
    return out


def domain_from_status(text, path):
    m = re.search(r"^#\s+STATUS\s*[—-]\s*(.+)$", text, re.M)
    if m:
        return m.group(1).strip()
    return os.path.basename(os.path.dirname(path))


def _rel(path):
    return os.path.relpath(path, WORKSPACE)


def index_status_files(indexed_at, records, orphans):
    paths = sorted(glob.glob(os.path.join(WORKSPACE, "**", "STATUS.md"), recursive=True))
    paths = [p for p in paths
             if f"{os.sep}node_modules{os.sep}" not in p and f"{os.sep}.git{os.sep}" not in p
             and not p.startswith(GOALS_DIR + os.sep)]  # F4: goal workspaces own their STATUS.md
    seen_hash = {}
    dups = []
    sources = []
    total_records = 0
    for p in paths:
        meta = file_meta(p)
        if meta["sha256"] in seen_hash:
            dups.append({"path": p, "same_as": seen_hash[meta["sha256"]]})
            continue
        seen_hash[meta["sha256"]] = p
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
        domain = domain_from_status(text, p)
        n = 0
        for start, label, body in chunk_markdown(text):
            rec = base_record(f"{_rel(p)}#L{start}", "status", domain, body,
                              p, f"line {start} · {label}", meta, indexed_at)
            admit(records, rec, orphans)
            n += 1
        sources.append({**{"path": p}, **meta, "records": n})
        total_records += n
    dedup = {"files_seen": len(paths), "unique_contents": len(seen_hash), "duplicates": dups}
    return sources, total_records, dedup


def index_memory(path, indexed_at, records, orphans):
    meta = file_meta(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    n = 0
    section = ""
    for start, label, body in chunk_markdown(text):
        if label.startswith("heading:"):
            section = label[len("heading:"):].strip()
        domain = section or "MEMORY"
        rec = base_record(f"MEMORY.md#L{start}", "memory", domain, body,
                          path, f"line {start} · {label}", meta, indexed_at,
                          privacy="private")
        admit(records, rec, orphans)
        n += 1
    return n, meta


# ---------------------------------------------------------------- goals (F4)
GOAL_ID_RE = re.compile(r"Goal ID:\s*(\S+)")


def index_goals(indexed_at, records, orphans):
    """F4: every goal workspace's GOAL.md (+ STATUS.md when present) as a
    first-class `goal` source kind, same chunking/freshness/admission
    discipline as every other source."""
    sources = []
    total = 0
    if not os.path.isdir(GOALS_DIR):
        return sources, 0
    for slug in sorted(os.listdir(GOALS_DIR)):
        gdir = os.path.join(GOALS_DIR, slug)
        if not os.path.isdir(gdir):
            continue
        goal_id = None
        goal_md = os.path.join(gdir, "GOAL.md")
        if os.path.exists(goal_md):
            with open(goal_md, encoding="utf-8", errors="replace") as f:
                m = GOAL_ID_RE.search(f.read())
            if m:
                goal_id = m.group(1)
        for fname in ("GOAL.md", "STATUS.md"):
            p = os.path.join(gdir, fname)
            if not os.path.exists(p):
                continue
            meta = file_meta(p)
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
            n = 0
            for start, label, body in chunk_markdown(text):
                rec = base_record(f"{slug}/{fname}#L{start}", "goal", slug, body,
                                  p, f"line {start} · {label}", meta, indexed_at)
                rec["goal_slug"] = slug
                rec["goal_id"] = goal_id
                admit(records, rec, orphans)
                n += 1
            sources.append({**{"path": p, "kind": "goal"}, **meta, "records": n})
            total += n
    return sources, total


# ---------------------------------------------------------------- main
def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    indexed_at = datetime.now(timezone.utc).isoformat()
    records = []
    orphans = []
    sources = []
    notes = []

    n, meta = index_claims(CLAIMS, True, indexed_at, records, orphans)
    sources.append({**{"path": CLAIMS, "kind": "claim", "admitted": True}, **meta, "records": n})

    if os.path.exists(INBOX):
        n, meta = index_claims(INBOX, False, indexed_at, records, orphans)
        sources.append({**{"path": INBOX, "kind": "claim", "admitted": False}, **meta, "records": n})
        notes.append("inbox.jsonl records are indexed with lifecycle=unadmitted and are "
                     "never presented as admitted facts by retrieval_query.py")

    n, meta, spine_info = index_spine(SPINE_DB, indexed_at, records, orphans, out_dir)
    sources.append({**{"path": SPINE_DB, "kind": "task"}, **meta, "records": n, **spine_info})
    notes.append(f"spine: indexed {spine_info['indexed_tasks']} non-UNTRACKED of "
                 f"{spine_info['total_tasks']} tasks; UNTRACKED receipt noise excluded by design")

    st_sources, _n, dedup = index_status_files(indexed_at, records, orphans)
    for s in st_sources:
        sources.append({**{"path": s["path"], "kind": "status"},
                        **{k: s[k] for k in ("sha256", "mtime", "bytes")},
                        "records": s["records"]})

    n, meta = index_memory(MEMORY, indexed_at, records, orphans)
    sources.append({**{"path": MEMORY, "kind": "memory"}, **meta, "records": n})

    goal_sources, goal_n = index_goals(indexed_at, records, orphans)
    sources.extend(goal_sources)
    notes.append(f"goals (F4): indexed {goal_n} records from {len(goal_sources)} goal-workspace "
                 "files (GOAL.md/STATUS.md under ~/workspace/goals/); goal-workspace STATUS.md "
                 "files are owned by this indexer and excluded from the generic STATUS glob")

    records.sort(key=lambda r: (r["kind"], r["source_path"], r["id"]))
    index_path = os.path.join(out_dir, "retrieval_index.jsonl")
    with open(index_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    by_kind = {}
    for r in records:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    manifest = {
        "tool": "retrieval_index.py v2 (pai-repo Phase 2; port of pai-query-layer pilot)",
        "built_at": indexed_at,
        "index_file": index_path,
        "total_records": len(records),
        "by_kind": by_kind,
        "orphans_dropped": orphans,
        "sources": sources,
        "status_dedup": dedup,
        "spine_live_path": SPINE_DB,
        "notes": notes,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    a = ap.parse_args()
    m = build(a.out_dir)
    print(json.dumps({"records": m["total_records"], "by_kind": m["by_kind"],
                      "sources": len(m["sources"]),
                      "status_files_seen": m["status_dedup"]["files_seen"],
                      "status_dupes": len(m["status_dedup"]["duplicates"]),
                      "orphans_dropped": len(m["orphans_dropped"])}, ensure_ascii=False))
