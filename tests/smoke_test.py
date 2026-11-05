#!/usr/bin/env python3
"""Phase 1 validation smoke test for pai-repo.

Checks:
1. Directory tree matches FILING_CABINET_PLAN_V1 §6.
2. All five contract files exist and are non-empty.
3. Every package/adapter/domain dir holds a README (so git tracks the tree).
4. The decision record for the plan lock exists and is non-empty.
5. ASSET_REGISTER.md parses: every table entry row has a non-empty Owner and
   Path cell (rows under the '## Gaps' heading are exempt — they are prose).

Exit 0 = PASS. Run: python3 tests/smoke_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# 1. Tree per plan §6
TREE = [
    "contracts",
    "packages/spine", "packages/cabinet", "packages/retrieval", "packages/context",
    "adapters/home", "adapters/msi", "adapters/muse-vm",
    "domains/tom", "domains/scoring", "domains/solution-knowledge",
    "docs/asset-register", "docs/decisions",
    "evals/retrieval",
]
for d in TREE:
    check(os.path.isdir(os.path.join(ROOT, d)), f"missing dir: {d}")

# 2. Five contracts, non-empty
CONTRACTS = ["identity.md", "lifecycle.md", "admission-privacy-forget.md",
             "context-package.md", "host-qualification.md"]
for c in CONTRACTS:
    p = os.path.join(ROOT, "contracts", c)
    check(os.path.isfile(p) and os.path.getsize(p) > 200,
          f"contract missing/too small: contracts/{c}")

# 3. README in every package/adapter/domain dir + evals/retrieval
for d in TREE:
    if d.startswith(("packages/", "adapters/", "domains/")) or d == "evals/retrieval":
        p = os.path.join(ROOT, d, "README.md")
        check(os.path.isfile(p) and os.path.getsize(p) > 50,
              f"missing README: {d}/README.md")

# 4. Decision record
dec = os.path.join(ROOT, "docs/decisions",
                   "DECISION_2026-11-05_FILING_CABINET_PLAN_LOCK.md")
check(os.path.isfile(dec) and os.path.getsize(dec) > 200,
      "decision record missing/too small")

# 5. Asset register parse
reg_path = os.path.join(ROOT, "docs/asset-register/ASSET_REGISTER.md")
check(os.path.isfile(reg_path), "ASSET_REGISTER.md missing")
entries = 0
if os.path.isfile(reg_path):
    in_gaps = False
    with open(reg_path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if line.startswith("## "):
                in_gaps = line.startswith("## Gaps")
                continue
            if in_gaps or not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 5:
                failures.append(f"register line {i}: expected 5 cells, got {len(cells)}")
                continue
            if cells[0] in ("Name",) or set(cells[1]) <= set("-: "):
                continue  # header / separator
            entries += 1
            if not cells[1]:
                failures.append(f"register line {i}: entry '{cells[0]}' has empty Owner")
            if not cells[3]:
                failures.append(f"register line {i}: entry '{cells[0]}' has empty Path")
    check(entries >= 100, f"register has only {entries} entries (expected >=100)")

if failures:
    print("SMOKE FAIL")
    for f_ in failures:
        print(" -", f_)
    sys.exit(1)
print(f"SMOKE PASS — tree OK, 5 contracts OK, register entries parsed: {entries}")
