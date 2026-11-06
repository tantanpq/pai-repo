# read_api.py — Cabinet read API (Phase 3 gate surface)

One read-only API across the memory families with per-namespace
rights. Implementation: `read_api.py` in this directory, built on the
production Registrar's fold (`registrar.py` read functions only — the
module has no write path: it never appends, projects, or mutates any
store; the spine is opened `mode=ro&immutable=1`, the claim register is
read through the live claimreg module's read paths).

## Operations

| Op | Returns |
|---|---|
| `resolve(system, id)` | the member's cabinets + relations, each cabinet's derived privacy level, the member's effective level + basis, and its native content when entitled |
| `cabinet(cab_id)` | membership structure (always listable), per-member levels, the derived level, and member contents only when the combined read is entitled |
| `members(namespace)` | all members of a namespace with cabinets + effective levels (structure + levels, no content bodies) |
| `cabinets()` | every cabinet with member count, derived level, entitlement |

Systems are the registry spellings — `vm-spine`, `claim-register`,
`home-runloop`, `claim-service` — and the contract alias
`home-claim-service` is accepted for `claim-service`.

## Rights (contract rule 4, spec §6)

- Effective level = the record's explicit `privacy` field when present
  (explicit always wins; presence is tracked separately from value —
  a present value that is null, not a string, or out of vocabulary
  fails closed to `unknown`; only an absent field inherits the
  default), else the namespace default. Defaults in force:
  claim-register, home-runloop, home-claim-service and vm-spine are all
  `house` (C1 `41c90c6`; HOME extension `2ecdb80`; vm-spine adoption
  `881aa8dc` / `69d8c8c`).
- A namespace with no default and no explicit field yields `unknown`,
  and **unknown = no read entitlement**: content is excluded and the
  exclusion is reported; a cabinet containing an unknown member lists
  its structure but its combined content read is denied. A cabinet's
  derived level is the strictest member level.
- Forgotten members (rule 6 tombstones, registry forget-consequence
  UNLINKs) never appear as readable content; on every surface they
  appear ONLY as a tombstone — (system, ID, forget timestamp, actor),
  the rule-6 closed set. Their privacy level, basis, kind and
  registry linkage are never published. Invalidated claims keep
  their membership but serve no content (contract rule 2).
- `ReadAPI` holds one cached read-only SQLite connection to the
  spine store. Call `close()` (idempotent) or use the API as a
  context manager to release it deterministically — required on
  Windows before deleting a fixture/temp spine DB.
- HOME namespaces are served **registry-only** (spec §5.1): membership
  and derived rights, no content fetch — content stays with the owning
  systems on HOME.
- Coverage bound (gap G5): Memory Rooms deployment B on HOME (owner
  unknown, served by no consumer) is an **excluded family**, named here
  rather than silently omitted.
- Note: `cab-0018` is the empty check-7 pilot cabinet (0 members); it
  derives `unknown` — no members, no level, no content — which is the
  honest result, not an error.

## CLI

```bash
cd ~/workspace/pai-repo
python3 -m packages.cabinet.read_api cabinets
python3 -m packages.cabinet.read_api cabinet --id cab-0022
python3 -m packages.cabinet.read_api resolve --system claim-register --id C-0140
python3 -m packages.cabinet.read_api members --namespace vm-spine
# fixture/test overrides: --registry PATH --claims-log PATH --spine-db PATH
# claimreg dependency: --claimreg-module PATH (or $CABINET_CLAIMREG_PATH;
# default the canonical VM path). The module is NOT vendored here — its
# sha256 is pinned in deps.json and verified before it is executed.
```

Output is JSON. Tests: `tests/test_read_api.py` (fixture-local:
scratch registry + fixture claims log + fixture spine DB + a staged
copy of the canonical claimreg module supplied via `claimreg_path`;
covers default resolution, explicit-wins, no-default denial,
present-null/malformed fail-closed handling, both forget paths,
tombstone exclusion from cabinet derivation, tombstone-only output
for forgotten members on every surface, secondary resolution,
the claimreg pin/missing-module failures, deterministic connection
close, and a read-only byte-identity check with an AST write-path
scan — whose sqlite check parses URIs for real (mode exactly 'ro')
and whose negative controls include the pathlib/sqlite evasions
executed by the fix-1 re-review).
