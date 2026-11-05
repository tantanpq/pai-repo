# Contract — Host Qualification

Purpose: define what an executor host (HOME, MSI, Muse VM) must prove
before PAI work is routed to it, per capability — with UNKNOWN preserved as
UNKNOWN, never guessed.

## Rules

1. Qualification is per (host, capability), never per host as a whole, and is
   recorded as dated evidence (who measured, when, by what check).
2. Before running work, a host proves, for the capability in question:
   (a) identity — named host and owning operator;
   (b) session context — the check ran in the session type the capability
       requires (e.g. interactive desktop session for UI automation);
       a headless/SSH probe neither qualifies nor disqualifies a
       session-bound capability;
   (c) deployment parity — installed generation/commit matches the
       deployment manifest in `adapters/<host>/`;
   (d) declared resources relevant to the capability (CPU/RAM/GPU/tools);
   (e) fresh health evidence — heartbeat or health endpoint fresh within
       the capability's stated window;
   (f) evidence channel — the host can write receipts/results back to the
       spine/evidence store.
3. A capability with no current evidence is `UNKNOWN`, and UNKNOWN is not
   qualified. Work MUST NOT be routed on assumed capability.
4. Qualification expires: evidence older than the capability's window is
   stale, and the capability reverts to `UNKNOWN` until re-measured.
5. Running processes, open ports, or a `Running` scheduled-task state are
   observations, not qualification; qualification requires the end-to-end
   check named by the capability.
6. Qualification never grants authority. Execution authority for spine work
   stays with HOME (locked decision 1) regardless of which hosts are
   qualified as workers.

## Non-goals

- No auto-remediation: a failed qualification is reported, not repaired,
  under this contract.
- No credential handling: qualification evidence references credential
  locations only, never contents.
- No performance ranking of hosts beyond qualified / UNKNOWN per capability.
