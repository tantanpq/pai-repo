#!/usr/bin/env python3
"""PAI retrieval — query CLI (Phase 2, pai-repo).

Port of the pai-query-layer pilot query (Codex PASS 2026-11-05), conformed
to the repo contracts, with two Phase 2 additions:

  - The Knowledge Room validity gate (validity.py) runs BEFORE lexical
    ranking, in KR's order: state -> project/domain validity -> freshness
    -> counterevidence -> relevance -> budget. Gate exclusions are reported
    with KR reason strings, never silent.
  - F2 snippet mode (default): results are bounded snippets around the
    matched evidence instead of whole records. --full restores the pilot's
    whole-record output.

Deterministic, stdlib-only, no LLM. Retrieval is advisory: sources are the
truth; every result carries its source path + anchor, and any source that
changed after indexing is gated STALE instead of being answered from
silently.

Usage:
  retrieval_query.py "free text question" [--limit N] [--json] [--stats]
  retrieval_query.py --claim C-0128 [--include-unadmitted]
  retrieval_query.py --domain Trading [--kind status]
  retrieval_query.py --kind goal "olympus"
  retrieval_query.py "question" --full          # whole records (pilot mode)
"""
import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validity  # noqa: E402

DEFAULT_INDEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
AUTHORITY = "ADVISORY_ONLY_SOURCES_ARE_TRUTH"
EXCLUDED_CAP_FULL = 64   # KR caps the excluded report at 64
EXCLUDED_CAP_SNIPPET = 10


def est_tokens(s):
    """Shared token estimator (pilot): ceil(chars/4). An estimator, not a
    tokenizer — used identically for old/new comparisons in evals."""
    return math.ceil(len(s) / 4)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_index(index_dir):
    records = []
    with open(os.path.join(index_dir, "retrieval_index.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    with open(os.path.join(index_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    return records, manifest


# ---------------------------------------------------------- SQLite sources
# Ported unchanged from the pilot (Codex-reviewed): the source database is
# never opened in place; main file + -wal are copied into a temporary
# snapshot under the index directory and fingerprinted there.
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


def _sqlite_content_fingerprint(path, index_dir):
    with _sqlite_snapshot(path, index_dir) as copy_path:
        return _fingerprint_tasks_copy(copy_path)


def freshness(manifest, index_dir):
    """Per-source freshness state: {path: FRESH|STALE|INVALID_FRESHNESS|MISSING}.
    A source is STALE when its current fingerprint differs from the indexed
    fingerprint; SQLite sources use the WAL-aware content fingerprint; a
    fingerprint failure is INVALID_FRESHNESS (KR vocabulary); a disappeared
    source is MISSING (the gate maps it to STALE — freshness unverifiable)."""
    states = {}
    for src in manifest["sources"]:
        p = src["path"]
        if not os.path.exists(p):
            states[p] = "MISSING"
            continue
        if src.get("freshness_mode") == "sqlite-content-v1":
            indexed = src.get("content_sha256") or src["sha256"]
            try:
                cur = _sqlite_content_fingerprint(p, index_dir)
            except Exception:
                states[p] = "INVALID_FRESHNESS"
                continue
            states[p] = "FRESH" if cur == indexed else "STALE"
            continue
        try:
            states[p] = "FRESH" if sha256_file(p) == src["sha256"] else "STALE"
        except Exception:
            # Any fingerprint failure — SQLite or plain hash — is
            # INVALID_FRESHNESS, as the KR import table claims (fix
            # round 1, Codex review area 5 row 4 caveat).
            states[p] = "INVALID_FRESHNESS"
    return states


def tokenize(s):
    return TOKEN_RE.findall(s.lower())


class BM25:
    def __init__(self, docs_tokens):
        self.docs = docs_tokens
        self.N = len(docs_tokens)
        self.avgdl = sum(len(d) for d in docs_tokens) / self.N if self.N else 0.0
        df = Counter()
        for d in docs_tokens:
            for t in set(d):
                df[t] += 1
        self.idf = {t: math.log(1 + (self.N - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, qtokens, idx, k1=1.5, b=0.75):
        doc = self.docs[idx]
        if not doc:
            return 0.0
        tf = Counter(doc)
        dl = len(doc)
        s = 0.0
        for t in set(qtokens):
            if t not in tf:
                continue
            f = tf[t]
            s += self.idf.get(t, 0.0) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / self.avgdl))
        return s


# ---------------------------------------------------------------- snippets (F2)
# Sentence split points for over-long lines: terminal punctuation splits
# ONLY when followed by whitespace or end-of-line, so decimals ("25.0%"),
# versions ("v2.6.1") and dotted names ("base_rag.json") stay intact.
# The splitter SLICES at split points — it is lossless by construction
# (a findall-based splitter silently dropped segments whose punctuation
# failed the lookahead; measured on the golden set, fixed here).
SENTENCE_SPLIT_RE = re.compile(r"[.!?…]+(?=\s|$)")
UNIT_HARD_CAP = 420


def _split_sentences(line):
    parts = []
    last = 0
    for m in SENTENCE_SPLIT_RE.finditer(line):
        parts.append(line[last:m.end()])
        last = m.end()
    parts.append(line[last:])
    return [p.strip() for p in parts if p.strip()]


def _units(text):
    units = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(line) <= UNIT_HARD_CAP:
            units.append(line)
        else:
            units.extend(_split_sentences(line))
    return units


def _term_weights(units, qtokens):
    """Unit-document-frequency weights within the record: a query term
    spread across many of the record's units (title, slug, body) is less
    locative than one concentrated in a single unit.
    w(t) = log(1 + n_units / (1 + units_containing(t)))."""
    qset = set(qtokens)
    df = Counter()
    for u in units:
        for t in qset & set(tokenize(u)):
            df[t] += 1
    n = max(len(units), 1)
    return {t: math.log(1 + n / (1 + df.get(t, 0))) for t in qset}


def _digit_bonus(seg):
    # Factoid bias (documented house heuristic): PAI questions usually ask
    # for a number, date, price or count, so among near-equal windows the
    # one carrying digits is more likely to hold the answer. Small and
    # capped so it only breaks near-ties.
    n = sum(1 for tok in tokenize(seg) if any(c.isdigit() for c in tok))
    return 0.25 * min(n, 5)


def _best_window(unit, qset, weights, cap):
    """Best <=cap window of a unit: the one maximizing (weighted query-term
    hits, distinct query terms), earliest on ties. Anchored at a hit token
    so the window starts cleanly on evidence."""
    hits = [(m.start(), m.group(0).lower())
            for m in TOKEN_RE.finditer(unit.lower()) if m.group(0).lower() in qset]
    if not hits:
        return None, 0.0, 0
    if len(unit) <= cap:
        score = sum(weights[t] for _s, t in hits) + _digit_bonus(unit)
        return unit, score, len({t for _s, t in hits})
    best = None
    for i, (start, _t) in enumerate(hits):
        end = start + cap
        inside = [t for s, t in hits[i:] if s < end]
        score = sum(weights[t] for t in inside) + _digit_bonus(unit[start:end])
        key = (score, len(set(inside)), -start)
        if best is None or key > best[0]:
            best = (key, start, score, len(set(inside)))
    _key, start, score, distinct = best
    seg = unit[start:start + cap]
    if start > 0:
        seg = "…" + seg
    if start + cap < len(unit):
        sp = seg.rfind(" ")
        if len(seg) - sp < 30 and sp > 0:
            seg = seg[:sp]
        seg = seg + "…"
    return seg, score, distinct


def make_snippet(text, qtokens, cap, weights=None):
    """Bounded excerpt around the matched evidence. Deterministic: units
    are scored by their best weighted window (record-local inverse
    frequency weights + the factoid digit bonus); the best units are
    kept whole, in original order, until the char cap is filled.
    (`weights` is accepted for interface stability and currently unused:
    corpus-IDF weighting was tried and measured WORSE on the golden set —
    see evals/retrieval/RESULTS.md.)"""
    units = _units(text)
    if not units:
        return text[:cap]
    if qtokens:
        qset = set(qtokens)
        weights = _term_weights(units, qtokens)
        candidates = []
        for idx, u in enumerate(units):
            win, score, distinct = _best_window(u, qset, weights, cap)
            if win is not None and distinct:
                candidates.append((score, distinct, idx, win))
        if candidates:
            candidates.sort(key=lambda x: (-x[0], -x[1], x[2]))
            chosen = []
            used = 0
            for _s, _d, idx, win in candidates:
                add = len(win) + (3 if chosen else 0)
                if chosen and used + add > cap:
                    continue
                chosen.append((idx, win))
                used += add
                if used >= cap:
                    break
            chosen.sort()
            return " … ".join(p for _i, p in chosen)
    flat = " ".join(text.split())
    if len(flat) <= cap:
        return flat
    cut = flat[:cap].rsplit(" ", 1)[0]
    return cut + "…"


# ---------------------------------------------------------------- main query flow
def run_query(a):
    try:
        validity.check_budget(a.limit)
    except validity.BudgetInvalid as e:
        print(str(e), file=sys.stderr)
        return 2

    records, manifest = load_index(a.index_dir)
    states = freshness(manifest, a.index_dir)
    stale_sources = sorted(p for p, s in states.items() if s != "FRESH")

    context = {"project_id": a.project or "PAI", "domain": a.domain,
               "environment": a.environment, "release": a.release}

    pool = list(records)
    if a.kind:
        pool = [r for r in pool if r["kind"] == a.kind]

    excluded = []

    if a.claim:
        # Explicit lifecycle-inspection lookup (pilot semantics, kept):
        # state/freshness are annotated, not excluded — EXCEPT admission,
        # which is uniform (fix round 1, blocker 1): admission is decided
        # by SOURCE (the record's `admitted` flag), on every path and
        # every lifecycle — an inbox record in a terminal lifecycle
        # (superseded/invalidated) is still unadmitted material and still
        # requires --include-unadmitted here.
        pool = [r for r in pool
                if r.get("claim_id") == a.claim or r["id"] == f"claim-register:{a.claim}"]
        if not a.include_unadmitted:
            kept = []
            for r in pool:
                if r.get("admitted") is False:
                    excluded.append({"id": r["id"], "reason": "STATE_CANDIDATE"})
                else:
                    kept.append(r)
            pool = kept
        results = pool[: a.limit]
        return _emit(a, results, excluded, stale_sources, states, context, None)

    # Default path: Knowledge Room gate order — state -> validity ->
    # freshness -> counterevidence, all before relevance/budget.
    gated = []
    for r in pool:
        # Admission precedes the KR state stage and is source-decided:
        # unadmitted-source records are excluded as STATE_CANDIDATE on
        # EVERY lifecycle, so a terminal-state inbox record cannot slip
        # in through the --history waiver either (blocker 1).
        if r.get("admitted") is False and not a.include_unadmitted:
            excluded.append({"id": r["id"], "reason": "STATE_CANDIDATE"})
            continue
        src_state = states.get(r["source_path"], "MISSING")
        gate_state = "STALE" if src_state == "MISSING" else src_state
        reason = validity.gate(r, context, gate_state)
        if reason is None:
            gated.append(r)
            continue
        # Documented opt-ins waive ONLY the state reason they name: the
        # record is re-gated with the state stage skipped and must still
        # pass applicability, freshness and counterevidence (blocker 2).
        waived = (reason == "STATE_CANDIDATE" and a.include_unadmitted) or \
            (reason in ("STATE_REVOKED", "STATE_SUPERSEDED")
             and (a.history or a.include_invalidated))
        if waived:
            reason2 = validity.gate(r, context, gate_state, waive_state=True)
            if reason2 is None:
                gated.append(r)
            else:
                excluded.append({"id": r["id"], "reason": reason2})
        else:
            excluded.append({"id": r["id"], "reason": reason})

    weights = None
    qtokens = tokenize(a.query) if a.query else []
    if qtokens and gated:
        bm = BM25([tokenize(r["text"]) for r in gated])
        weights = bm.idf  # corpus IDF also drives snippet window scoring
        qset = set(qtokens)
        scored = []
        for j, r in enumerate(gated):
            s = bm.score(qtokens, j)
            if s > 0:
                # Query-coverage factor: a record covering more of the
                # question's distinct terms outranks a shorter record that
                # merely repeats fewer of them (heading-chunk trap).
                coverage = len(qset & set(bm.docs[j])) / len(qset) if qset else 0.0
                s *= (0.35 + 0.65 * coverage)
            # KR reports EVERY below-threshold exclusion when the query is
            # tokenized — a zero-overlap record is LOW_RELEVANCE, never a
            # silent omission (fix round 1, blocker 4).
            if validity.normalize_bm25(s) < validity.RELEVANCE_THRESHOLD:
                excluded.append({"id": r["id"], "reason": "LOW_RELEVANCE"})
            else:
                scored.append((s, r))
        # KR compile sort: score desc, salience desc, knowledgeId asc.
        scored.sort(key=lambda x: (-x[0], -(x[1].get("salience") or 0.0), x[1]["id"]))
        results = [r for _s, r in scored[: a.limit]]
    else:
        results = sorted(gated, key=lambda r: r["id"])[: a.limit]

    return _emit(a, results, excluded, stale_sources, states, context, weights)


_LINE_ANCHOR_RE = re.compile(r"line (\d+)")


def _short_path(p):
    """Path relative to the home directory when possible (the snippet
    payload stays lean; full mode keeps absolute paths)."""
    home = os.path.expanduser("~")
    if p.startswith(home + os.sep):
        return p[len(home) + 1:]
    return p


def _short_src(r):
    m = _LINE_ANCHOR_RE.search(r["source_anchor"] or "")
    anchor = f"#L{m.group(1)}" if m else "#tasks-row" if r["kind"] == "task" else ""
    return _short_path(r["source_path"]) + anchor


def _emit(a, results, excluded, stale_sources, states, context, weights):
    def fresh_of(r):
        return states.get(r["source_path"], "MISSING")

    if a.json and a.full:
        out_results = []
        for r in results:
            o = dict(r)
            o["freshness"] = fresh_of(r)
            out_results.append(o)
        payload = {"query": a.query, "claim": a.claim, "context": context,
                   "stale_sources": stale_sources,
                   "excluded": excluded[:EXCLUDED_CAP_FULL],
                   "excluded_count": len(excluded),
                   "authority": AUTHORITY, "results": out_results}
        text = json.dumps(payload, ensure_ascii=False, indent=1)
        print(text)
        if a.stats:
            print(f"[stats] answer_context_tokens_est={est_tokens(text)}", file=sys.stderr)
        return 0

    if a.json:
        qtokens = tokenize(a.query) if a.query else []
        out_results = []
        for r in results:
            # F2 proportional cap: the per-result snippet budget scales
            # with the source file it replaces — at least the flat cap,
            # at most a sixth of the file, never above 900 chars, and
            # never above a third of a tiny file (floor 120). Reading the
            # file is the old path; the snippet must stay a small,
            # bounded fraction of it at every file size (Codex's F2 note
            # on the pilot: a fixed cap loses at both ends — too big for
            # tiny files, too small to hold the evidence in big ones).
            cap = a.snippet_chars
            try:
                fchars = os.path.getsize(r["source_path"])
                cap = min(max(cap, fchars // 6), max(120, fchars // 3), 900)
            except OSError:
                pass
            # Labels travel in EVERY output mode (fix round 1, blockers
            # 1+5): lifecycle, admission, privacy and namespace ride the
            # snippet payload too, verbatim from the record — an opted-in
            # unadmitted or private result is never unlabelled.
            entry = {"i": r["id"], "k": r["kind"],
                     "lc": r["lifecycle"], "adm": bool(r.get("admitted", True)),
                     "p": r["privacy"], "ns": r["namespace"],
                     "s": make_snippet(r["text"], qtokens, cap, weights),
                     "src": _short_src(r)}
            if fresh_of(r) != "FRESH":
                entry["f"] = fresh_of(r)
            out_results.append(entry)
        payload = {"stale": [_short_path(p) for p in stale_sources],
                   "excluded_count": len(excluded),
                   "excluded_reasons": dict(Counter(e["reason"] for e in excluded)),
                   "authority": AUTHORITY, "results": out_results}
        if a.show_excluded:
            payload["excluded"] = [{"i": e["id"], "r": e["reason"]}
                                   for e in excluded[:EXCLUDED_CAP_SNIPPET]]
        text = json.dumps(payload, ensure_ascii=False)
        print(text)
        if a.stats:
            print(f"[stats] answer_context_tokens_est={est_tokens(text)}", file=sys.stderr)
        return 0

    lines = []
    if stale_sources:
        lines.append("!! GATE: these sources changed after indexing — their records are "
                     "excluded by the freshness gate (the live file wins):")
        for p in stale_sources:
            lines.append(f"!!   {states[p]}: {p}")
        lines.append("")
    if excluded:
        lines.append(f"({len(excluded)} record(s) excluded by the validity gate; "
                     f"first reasons: {Counter(e['reason'] for e in excluded)})")
        lines.append("")
    if not results:
        lines.append("(no results)")
    qtokens = tokenize(a.query) if a.query else []
    for n, r in enumerate(results, 1):
        tag = f"{r['kind']} · {r['domain']} · {r['lifecycle']}"
        if r["kind"] == "claim":
            tag += f" · status={r.get('claim_status')}"
            if r.get("forgotten"):
                tag += f" · ☠ FORGOTTEN at {r.get('forget_at')} by {r.get('forget_actor')}"
            elif r.get("lifecycle") == "invalidated":
                tag += f" · ☠ INVALIDATED by {r.get('invalidated_by')}"
            if r.get("superseded_by"):
                tag += f" · superseded_by={r['superseded_by']}"
        if fresh_of(r) != "FRESH":
            tag += f" · ⚠ {fresh_of(r)}"
        lines.append(f"[{n}] {tag}")
        lines.append(r["text"] if a.full else make_snippet(r["text"], qtokens, a.snippet_chars, weights))
        lines.append(f"    ↳ {r['source_path']} · {r['source_anchor']} · {fresh_of(r)}")
        lines.append("")
    text = "\n".join(lines)
    print(text)
    if a.stats:
        print(f"[stats] answer_context_tokens_est={est_tokens(text)} results={len(results)} "
              f"stale_sources={len(stale_sources)} excluded={len(excluded)}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--claim", help="exact claim id, e.g. C-0128 (explicit lifecycle-inspection lookup)")
    ap.add_argument("--include-unadmitted", action="store_true",
                    help="include unadmitted (inbox) records — waives only the STATE_CANDIDATE gate")
    ap.add_argument("--include-invalidated", action="store_true",
                    help="include invalidated/superseded records (alias of --history)")
    ap.add_argument("--history", action="store_true",
                    help="include invalidated/superseded records, marked as such")
    ap.add_argument("--domain", help="domain context for the validity gate (KR applicability)")
    ap.add_argument("--project", help="project context for the validity gate (default PAI)")
    ap.add_argument("--environment", help="environment context for the validity gate")
    ap.add_argument("--release", help="release context for the validity gate")
    ap.add_argument("--kind", choices=["claim", "task", "status", "memory", "goal"])
    ap.add_argument("--limit", type=int, default=5, help="budget: max results, integer in [1, 32] (KR)")
    ap.add_argument("--full", action="store_true", help="return whole records instead of snippets")
    ap.add_argument("--show-excluded", action="store_true",
                    help="snippet mode: also list the first excluded records with their gate reasons")
    ap.add_argument("--snippet-chars", type=int, default=260, help="per-result snippet char cap (F2)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stats", action="store_true", help="print estimated context tokens of the answer block")
    ap.add_argument("--index-dir", default=DEFAULT_INDEX_DIR)
    a = ap.parse_args()
    return run_query(a)


if __name__ == "__main__":
    sys.exit(main())
