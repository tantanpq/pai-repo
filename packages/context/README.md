# packages/context — context compiler & usage ledger

Responsibility: One shared library for context packaging: compiler/reducer/cursor/bounded readers (converging Chief context-economy, Resident packet compiler, home-cp bounded readers) plus the unified usage ledger that keeps provider-reported and estimated tokens separate.

Contract dependencies: contracts/context-package.md · contracts/host-qualification.md

Status: Phase 4 implemented 2026-11-06 (Slices 1–5: usage-ledger core `ledger.py`/`rollup.py`, pack assembler `pack.py`, component adapters `components.py`, lane instrumentation + shadow mode `shadow.py`, gate machinery `gate.py` — machinery only; the real gate week and the GATE_METHOD freeze wait for the 2026-11-14 review). See `~/workspace/pai-repo-program/phase4/PHASE4_BUILD_CLOSURE_2026-11-06.md`.
