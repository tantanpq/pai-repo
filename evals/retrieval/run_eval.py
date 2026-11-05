#!/usr/bin/env python3
"""Phase 2 golden-set measurement runner (filing-cabinet plan, section 8 gate).

Rebuilds the retrieval index, then for every question in questions.json:
  - runs the package query CLI in snippet mode (the front-door default),
  - correctness = the gold string appears in the union of returned snippets
    (the pilot's method, SPEC_V1 S6.2); full-mode correctness is also
    recorded as a diagnostic so snippet-selection losses are visible,
  - tokens: old = whole old_files read into context (for the spine .db,
    the tasks-table text dump — the no-index scan cost); new = the actual
    printed snippet-mode payload; same estimator both sides: ceil(chars/4),
  - latency per query (wall clock of the CLI call, freshness re-hash incl.).

Also runs the package test suite and reports the STALE/WAL gate tests by
name. Writes last_run.json next to this script and prints a summary.
Stdlib only.
"""
import json
import math
import os
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PKG = os.path.join(REPO, "packages", "retrieval")
sys.path.insert(0, PKG)
import retrieval_index  # noqa: E402


def est_tokens(s):
    return math.ceil(len(s) / 4)


def old_path_tokens(paths):
    total = 0
    for p in paths:
        if p.endswith(".db"):
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                rows = con.execute("SELECT * FROM tasks").fetchall()
                text = "\n".join(" | ".join("" if v is None else str(v) for v in row)
                                 for row in rows)
            finally:
                con.close()
            total += est_tokens(text)
        else:
            with open(p, encoding="utf-8") as f:
                total += est_tokens(f.read())
    return total


def run_cli(args):
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, os.path.join(PKG, "retrieval_query.py"), *args],
                       capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(f"query failed {args}: {r.stderr[:400]}")
    return r.stdout, dt


def main():
    with open(os.path.join(HERE, "questions.json"), encoding="utf-8") as f:
        spec = json.load(f)
    questions = spec["questions"]

    t0 = time.perf_counter()
    manifest = retrieval_index.build(os.path.join(PKG, "index"))
    index_seconds = time.perf_counter() - t0

    rows = []
    for q in questions:
        args = [q["q"], "--json", "--limit", str(q["limit"])]
        if q.get("kind"):
            args += ["--kind", q["kind"]]
        out, dt = run_cli(args)
        payload = json.loads(out)
        snips = [r["s"] for r in payload["results"]]
        correct = any(q["gold"] in s for s in snips)
        full_out, _ = run_cli(args + ["--full"])
        full_payload = json.loads(full_out)
        full_correct = any(q["gold"] in r["text"] for r in full_payload["results"])
        old_t = old_path_tokens(q["old_files"])
        new_t = est_tokens(out)
        rows.append({
            "id": q["id"], "kind": q.get("kind") or "cross", "q": q["q"],
            "gold": q["gold"], "freshness_probe": bool(q.get("freshness_probe")),
            "correct": correct, "full_mode_correct": full_correct,
            "old_tokens": old_t, "new_tokens": new_t,
            "token_win": new_t < old_t, "margin": old_t - new_t,
            "latency_s": round(dt, 3), "results": len(payload["results"]),
            "stale_sources": payload["stale"],
        })

    suite = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=PKG, capture_output=True, text=True)
    suite_tail = (suite.stderr or suite.stdout).strip().splitlines()[-3:]

    n = len(rows)
    correct_n = sum(r["correct"] for r in rows)
    wins = sum(r["token_win"] for r in rows)
    summary = {
        "questions": n,
        "correct": correct_n,
        "correctness": round(correct_n / n, 4) if n else 0,
        "full_mode_correct": sum(r["full_mode_correct"] for r in rows),
        "token_wins": wins,
        "worst_margin": min((r["margin"] for r in rows), default=0),
        "total_old_tokens": sum(r["old_tokens"] for r in rows),
        "total_new_tokens": sum(r["new_tokens"] for r in rows),
        "mean_latency_s": round(sum(r["latency_s"] for r in rows) / n, 3) if n else 0,
        "max_latency_s": max((r["latency_s"] for r in rows), default=0),
        "index_records": manifest["total_records"],
        "index_seconds": round(index_seconds, 2),
        "test_suite_ok": suite.returncode == 0,
        "test_suite_tail": suite_tail,
        "gate": {
            "correctness_gte_95pct": (correct_n / n >= 0.95) if n else False,
            "new_wins_every_question": wins == n,
            "note": "STALE/WAL gate status = the named tests in the package suite "
                    "(test_stale_gate_flags_exactly_the_modified_source, "
                    "test_spine_wal_only_change_trips_stale_gate); suite_ok covers them.",
        },
    }
    result = {"summary": summary, "rows": rows}
    with open(os.path.join(HERE, "last_run.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for r in rows:
        if not r["correct"] or not r["token_win"]:
            print("MISS:", r["id"], "correct=", r["correct"], "win=", r["token_win"],
                  "old=", r["old_tokens"], "new=", r["new_tokens"], "q=", r["q"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
