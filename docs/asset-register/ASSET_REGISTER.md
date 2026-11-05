# ASSET REGISTER — seed (Phase 1)

**Seeded:** 2026-11-05, as part of Phase 1 of the LOCKED FILING_CABINET_PLAN_V1.
**Sources:** `~/workspace/lane-ops/TOOL_REGISTRY.md` (census 2026-11-04) and
Workstream A `~/workspace/pai-repo-program/INVENTORY_AND_CONSOLIDATION_MAP.md`
(Codex census, observation date 2026-11-05).

**This is a pointer register only.** Every entry points at an asset where it
lives today (name · owner · machine · path · state with its evidence date).
NO data was moved, copied, or modified to build this register.

**Supersession note:** Phase 0's source/owner/deployment manifest will
SUPERSEDE and merge this seed — entries will gain installed-generation/commit
fields and crosswalk IDs there. Until then this register is the widest single
list, not the final manifest. Entries appearing in two sections (tool view +
system view) are cross-noted, not double-counted as systems.

**How to read state:** registry vocabulary — IN-USE / TESTED-UNUSED /
UNTESTED / BROKEN / DUPLICATE / DORMANT — or the inventory's evidence wording
(LIVE / persisted / source-only / UNKNOWN), always with its date. DORMANT
scoring entries reflect Tân's standing order, not faults.

## A. Tools — MSI control planes & workers (TOOL_REGISTRY §1–2, 2026-11-04)

| Name | Owner | Machine | Path | State (dated) |
|---|---|---|---|---|
| chatgpt-cp | PAI ops | MSI | C:\temp\chatgpt-cp | IN-USE — audit ran 2026-10-12, files live 2026-11-02 |
| msi-cp | PAI ops | MSI | C:\temp\msi-cp | IN-USE — live 2026-10-29 |
| codex-cp | PAI ops | MSI | C:\temp\codex-cp | IN-USE — live 2026-10-30 → 2026-11-02 |
| youtube-cp | PAI ops | MSI | C:\temp\youtube-cp | IN-USE — live 2026-11-02 |
| meta-cp | PAI ops | MSI | C:\temp\meta-cp | IN-USE — live 2026-11-04 |
| dom-cp | PAI ops | MSI | C:\temp\dom-cp\domcp.mjs | IN-USE — accepted 2026-10-19 |
| reel-cp | PAI ops | MSI | C:\temp\reel-cp | IN-USE — new unit 2026-11-04 |
| notebook-cp | PAI ops | MSI | C:\temp\notebook-cp | IN-USE — live 2026-10-31; ADOPT-WIRE into CMM script routing |
| github-cp | PAI ops | MSI | C:\temp\github-cp | TESTED-UNUSED — runner live, github.com login unverified (2026-11-04) |
| grok-cp | PAI ops | MSI | C:\temp\grok-cp | TESTED-UNUSED — selectors unverified, brief dispatch forbidden (2026-11-04) |
| rea-cp | PAI ops | MSI | C:\temp\rea-cp | TESTED-UNUSED — live, rarely called (2026-11-04) |
| home-device-cp | PAI ops | MSI | C:\temp\home-cp (+ repo home-cp) | TESTED-UNUSED — 143/143 tests PASS, act stops at PREPARED, no actuation handler (2026-11-04) |
| suno-cp | PAI ops | MSI | C:\temp\suno-cp | BROKEN at verdict layer — ARCHIVE; its verdicts must not drive decisions (2026-11-04) |
| sunogen worker | PAI ops | MSI | C:\temp\sunogen | IN-USE — newest job 2026-11-03 |
| ChatGPT queue worker | PAI ops | MSI | C:\temp\chatgpt + task ChatGPTLane-MSI | IN-USE (2026-11-04) |
| codex-prod (WFLOW production) | PAI ops | MSI | C:\temp\codex-prod + task CodexDailyProduction | IN-USE — VM local source build-v2-src is stale, do not reuse (2026-11-04) |
| msi-bin suite (+ stepcap) | PAI ops | MSI | C:\temp\msi-bin | IN-USE — edited 2026-11-01 |
| agent-browser 0.39.0 | PAI ops | MSI | npx via CDP 9336 | IN-USE (2026-11-04) |
| gh portable 2.101.0 | PAI ops | MSI | C:\temp\gh-install\bin\gh.exe | IN-USE — commit/push/PR verified 2026-10-27 |
| TokenEconomizer | PAI ops | MSI | Codex plugin + C:\temp\tokenecon-trial | IN-USE PILOT since 2026-10-31; verdict due 2026-11-14 |
| SimLab Core R7 | PAI ops | MSI | C:\ProgramData\PAI_SIMLAB\...\R7 | IN-USE at gates — called via chief-simlab.js, no background task (2026-11-04) |
| release-gate v1.2 | PAI ops | MSI | C:\temp\release-gate\release-gate.mjs | IN-USE — 147/147 fixtures PASS (2026-11-04) |
| motion-kit | PAI ops | MSI | C:\temp\motion-kit | TESTED-UNUSED — smoke PASS 2026-10-27; ADOPT-WIRE to video lane toolkit |
| CloakBrowser 0.6.4 | PAI ops | MSI | C:\temp\cloak-trial | TESTED-UNUSED — trial 2026-10-28; ADOPT-WIRE as canary |
| agent-desktop 1.1.0 | PAI ops | MSI | %APPDATA%\npm\agent-desktop.cmd; state C:\Users\tanta\.agent-desktop | IN-USE — trial PASS + wired into MSI CP 2026-11-04 |
| PAI CP Builder | PAI ops | HOME + MSI | extends REA (rea-cp) | TESTED-UNUSED — accepted 2026-10-14 (62 tests PASS); ADOPT-WIRE as step 0 for new web apps |
| PAI worker transport | PAI ops | MSI | C:\ProgramData\PAI_MSI_WORKER_TRANSPORT | TESTED-UNUSED — dispatch asleep by Tân's intent since 2026-10-03; do not revive unasked |
| Sim Studio R1 + Sim Stack | PAI ops | MSI | C:\ProgramData\PAI_SIM_STACK | TESTED-UNUSED — ran 1 real campaign (2026-08, per registry), dormant since |
| windows-mcp-trial | PAI ops | MSI | C:\temp\windows-mcp-trial | UNTESTED — ARCHIVE candidate (agent-desktop won this slot) |
| Nox / emu-lab | PAI ops | MSI | C:\temp\nox, C:\temp\emu-lab + tasks | TESTED-UNUSED — MSI-NoxBoot task Disabled (2026-11-04) |
| ProgramData PAI forest + SAT/PAI_W1 (group) | PAI legacy | MSI | C:\ProgramData\PAI* (~90 trees), C:\PAI_W1 | DORMANT legacy generations 2026-08→10; ARCHIVE — map only, physical cleanup only via pre-delete law + asset ledger |
| One-off job dirs (group) | PAI ops | MSI | C:\temp\ (~150 dirs: it43-*, cmm-*, mv-*, leona-*, *-review, *-trial) | Not tools — job footprints; ARCHIVE as group, never delete in passing (2026-11-04) |

## B. Tools — HOME services & stacks (TOOL_REGISTRY §3, 2026-11-04)

| Name | Owner | Machine | Path | State (dated) |
|---|---|---|---|---|
| Ollama 0.40.12 | HOME runtime | HOME | task OllamaServe, :11434 | IN-USE — port listening, measured 2026-11-04 |
| Leona Voice service v2 | HOME runtime | HOME | D:\leona-voice (:8077 + Tailscale Funnel) | IN-USE — task Running, files live 2026-10-31 |
| Chief MCP stack | HOME runtime | HOME | tasks Guard/SideBySide/Tunnel; gateway 8787 / guard 8788 / bridge 8790 | IN-USE — verified 2026-10-30; Chief-Gov off by Tân's order, not broken |
| Mission Framework executor | HOME runtime | HOME | C:\temp\mf-* (~25 dirs) | IN-USE — dirs live 2026-11-04 (mf-p3-live, cmm-t8) |
| ComfyUI | HOME runtime | HOME | D:\ComfyUI (+ D:\AI_Model_Storage) | IN-USE — live 2026-11-01 |
| Scoring Service | HOME runtime | HOME | C:\scoring-service (:8000) | DORMANT by Tân's order 2026-10-27, reaffirmed 2026-11-04 — task Disabled, port closed is the CORRECT state |
| Unified Lane (sunolisten) | HOME runtime | HOME | C:\temp\sunolisten | DORMANT — guardian UnifiedLaneWatch Disabled since 2026-10-30 |
| Score Queue | HOME runtime | HOME | C:\temp\score-queue + task | DORMANT (with Scoring) |
| TOM training stack | HOME runtime | HOME | D:\tom-train (RTX 3060 Ti) | DORMANT by program — frozen after Run 6; Run 2 is the official candidate |
| Q family (QCHECK/QSCAN/QTRACE/QFIX) | HOME runtime | HOME | PAI_RUNTIME\bin + ProgramData snapshots | DORMANT — all ran for real; last QCHECK cert 2026-10-15 = DEGRADED; deep in ProgramData, not re-censused 2026-11-04 |
| home-pc-cp | HOME runtime | HOME | C:\temp\home-cp (source VM ~/workspace/home-control-plane/) | TESTED-UNUSED — last edited 2026-10-19 |
| PAI Task Box Ingress + Admin Bridge | HOME runtime | HOME | tasks; run inside C:\Users\Tom\My Drive | TESTED-UNUSED — mirror holds 99.8GB real files, delete nothing there (2026-11-04) |
| upscale-tools | HOME runtime | HOME | D:\upscale-tools | TESTED-UNUSED — live 2026-10-28 |
| bookjudge (HOME copy) | HOME runtime | HOME | C:\temp\bookjudge | TESTED-UNUSED — ARCHIVE candidate (main path is VM skill local-book-scoring) |
| orca-trial | HOME runtime | HOME | C:\temp\orca-trial | TESTED-UNUSED — no verdict record; ARCHIVE candidate |
| sunogen (HOME copy) | HOME runtime | HOME | C:\temp\sunogen, sunogen-home | DUPLICATE of MSI sunogen — idle since 2026-10-09; ARCHIVE |

## C. Tools — Muse VM skills & infrastructure (TOOL_REGISTRY §4, 2026-11-04)

| Name | Owner | Machine | Path | State (dated) |
|---|---|---|---|---|
| Custom skills (~40) | Leona | VM | ~/workspace/custom-skills/local-*/ | IN-USE — the daily Leona/lane layer (2026-11-04) |
| Skill mirrors legacy (6) | Leona | VM | ~/workspace/skills/ | DUPLICATE — live copies in custom-skills; ARCHIVE |
| Custom connectors | Leona | VM | ~/workspace/custom-connectors/ | UNTESTED — directory EMPTY (0 dirs) as of 2026-11-04; recorded so nobody re-searches |
| ctx search (context-mode) | Leona | VM | ~/workspace/context-mode-trial/ | IN-USE — index/search only, no hooks (Tân ruling 2026-10-12); also inventory V006 |
| Core-file integrity | Leona | VM | ~/workspace/security/ + 6h cron | IN-USE |
| Memory system (VM) | Leona | VM | ~/workspace/memory-system/ | IN-USE as Leona process layer; DESIGN-ONLY as a store (inventory V005) |
| restic backup | Leona | VM | cron restic-pilot-daily → encrypted repo on Drive | IN-USE — restore test PASS 2026-10-28 |
| CP source dirs (11–12/10) | Leona | VM | ~/workspace/*-control-plane/ | DUPLICATE-as-source — runtimes live on MSI; KEEP with source↔runtime relation noted |
| judge-v2 (music scoring standard) | Leona | VM | ~/workspace/zmedia-music/judge-v2/ | IN-USE as standard (locked 2026-10-13); scoring work itself paused by order |
| analyze_track.py + live-score/ | Leona | VM | ~/workspace/zmedia-music/ | TESTED-UNUSED since 2026-10-06; ARCHIVE candidate; jobs pointing here stay OFF by Tân's ruling |
| pai-cp-package | Leona | VM | ~/workspace/pai-cp-package/ | TESTED-UNUSED — full GTM closed by ruling F18; internal use only; ARCHIVE candidate |

## D. GitHub repositories (TOOL_REGISTRY §5, census via gh 2026-11-04)

| Name | Owner | Machine | Path | State (dated) |
|---|---|---|---|---|
| pai-cp | tantanpq | GitHub | github.com/tantanpq/pai-cp | IN-USE — pushed 2026-10-17→31 |
| pai-cp-free (public) | tantanpq | GitHub | github.com/tantanpq/pai-cp-free | IN-USE — 25 HIGH house-path literals still need scrub in its own wave |
| home-cp | tantanpq | GitHub | github.com/tantanpq/home-cp | IN-USE |
| leona-tool-bundle | tantanpq | GitHub | github.com/tantanpq/leona-tool-bundle | IN-USE — 2 BLOCKER EXCL-ORG open before any sharing |
| pai-core-private | tantanpq | GitHub | github.com/tantanpq/pai-core-private | IN-USE — source checkout also on HOME (inventory H055) |
| zmedia-ops | tantanpq | GitHub | github.com/tantanpq/zmedia-ops | IN-USE |
| pai-assurance | tantanpq | GitHub | github.com/tantanpq/pai-assurance | IN-USE |
| pai-continuity | tantanpq | GitHub | github.com/tantanpq/pai-continuity | IN-USE |
| zline-ops | tantanpq | GitHub | github.com/tantanpq/zline-ops | IN-USE — brief mirror, Issue #19 |
| zlinegroup-us | tantanpq | GitHub | github.com/tantanpq/zlinegroup-us | IN-USE — main is authoritative; pushed 2026-11-04 |
| leona-scoring-standards | tantanpq | GitHub | github.com/tantanpq/leona-scoring-standards | IN-USE |
| business-idea-scorer | tantanpq | GitHub | github.com/tantanpq/business-idea-scorer | IN-USE |
| PAI | tantanpq | GitHub | github.com/tantanpq/PAI | IN-USE — public capability/runbook copies also on HOME (inventory H054) |
| pai-reliability-evidence | tantanpq | GitHub | github.com/tantanpq/pai-reliability-evidence | ARCHIVED on GitHub (public) |
| free-ai-tools-hub (private) | tantanpq | GitHub | github.com/tantanpq/free-ai-tools-hub | TESTED-UNUSED — pushed 2026-10-11; absent from paper inventory; ARCHIVE candidate |
| zlinegroup-site | tantanpq | GitHub | github.com/tantanpq/zlinegroup-site | DUPLICATE — superseded by zlinegroup-us; ARCHIVE |
| desktop-tutorial | tantanpq | GitHub | github.com/tantanpq/desktop-tutorial | ARCHIVE |
| tantanpq (profile) | tantanpq | GitHub | github.com/tantanpq/tantanpq | KEEP — profile repo |

## E. Systems — VM spine / memory / retrieval (Workstream A inventory, 2026-11-05)

| Name | Owner | Machine | Path | State (dated) |
|---|---|---|---|---|
| V001 VM task spine shadow-1a | HOME authority (mirrored) / VM read-model | VM | ~/workspace/pai-continuity/spine/build/shadow-1a/runtime/spine.db | LIVE ingestion ~5-min cycle, newest 2026-11-05 07:59 PT; 13,929 rows / 63 tracked |
| V002 VM claim-register | Leona | VM | ~/workspace/pai-continuity/claim-register/claims.jsonl (+ inbox.jsonl, CLAIMS_DIGEST_LIVE.md) | LIVE — 267 admitted + 8 pending counted 2026-11-05; hourly INVALIDATE lifecycle |
| V003 Continuity architecture / prior censuses | Leona | VM | ~/workspace/pai-continuity/ASSET_REGISTER_2026-10-28.md et al. | Documents, dates 2026-10-16→11-01; historical, no runtime authority implied |
| V004 Muse runtime memory | Leona | VM | ~/memory + ~/MEMORY.md | LIVE — 69 files / 25MB, newest 2026-11-05 |
| V005 memory-system design | Leona | VM | ~/workspace/memory-system/ | DESIGN-ONLY, no runtime; newest 2026-10-12 |
| V006 context-mode trial | Leona | VM | ~/workspace/context-mode-trial/ | Index/search only; newest stats 2026-11-01; running process not established (= registry ctx search) |
| V007 PAI query layer pilot | Leona | VM | ~/workspace/pai-query-layer/ | DONE — Codex review PASS 2026-11-05; ADOPT-WITH-FIXES (F2/F4 land in Phase 2) |
| V008 TOM layered corpus/RAG | TOM domain | VM | ~/workspace/second-life/tom-corpus/memory/{L1,L2,L3} + tools | LIVE — 169 KU corpus; Slices 1–2 certified 2026-11-05 |
| V009 lane-ops tool registry | Leona | VM | ~/workspace/lane-ops/TOOL_REGISTRY.md + lane-launch-registry.json | LIVE — updated 2026-11-04; this register is its seed child |
| V010 Leona portable capsule | Leona | VM | ~/workspace/leona-capsule/v1 (+ tar.gz, .sha256) | Packaging R1 present; no runtime/process evidence |
| V011 Leona workspace | Leona | VM | ~/workspace/leona | UNKNOWN internals — top-level listing only (2026-11-05) |
| V012 PAI CP package | Leona | VM | ~/workspace/pai-cp-package | Packaging experiment; no live runtime evidence (= registry pai-cp-package) |
| V013 PAI CP package lanes | Leona | VM | ~/workspace/pai-cp-package.lanes | UNKNOWN contents/activity (2026-11-05) |
| V014 Repo hygiene plans | Leona | VM | ~/workspace/pai-repo-hygiene | Paper 2026-10-08/09, described stale; no runtime |
| V015 PAI strategy papers | Leona | VM | ~/workspace/pai-strategy | Paper, described stale; newest date not supplied |
| V016 Tools radar / token research | Leona | VM | ~/workspace/tools-radar/ | Research notes; newest write 2026-11-04 (TokenEconomizer review prep dated 2026-11-14 is a plan title, not executed work) |
| V017 Frozen Muse memory archive | Leona | VM | ~/workspace/memory-archive-2026-10-27 | Frozen archive by design, 2026-10-27; not active memory |
| V018 PAI repo program workspace | PAI Repo Program | VM | ~/workspace/pai-repo-program | Program coordination source; this repo is its Phase 1 output |

## F. Systems — HOME primary catalogue (Workstream A inventory, direct inspection 2026-11-05)

| Name | Owner | Machine | Path | State (dated) |
|---|---|---|---|---|
| H001 Simple Body Claim Service R2 | HOME legacy runtime | HOME | C:\ProgramData\PAI_SIMPLE_BODY_R1\HOME\components\claim-service (gen native-maint-r8-v5) | LIVE — listener :3412, health OK 2026-11-05 |
| H002 HOME execution authority DB | HOME legacy runtime | HOME | C:\ProgramData\PAI_RUN_LOOP\pai-run-loop.db | ACTIVE — authority maintenance PASS / fence 116, 2026-11-05; claims=202 (main checkpoint) |
| H003 Simple Body Home Resident R2 | HOME legacy runtime | HOME | C:\ProgramData\PAI_SIMPLE_BODY_R1\HOME\components\resident (gen r27-incremental) | LIVE — PID running, heartbeat fresh 2026-11-05 |
| H004 Home Control Run Loop task | HOME legacy runtime | HOME | C:\ProgramData\PAI_RUNTIME\bin\run-current-once.ps1 | LIVE — Ready, last run 2026-11-05 08:04 result 0; maintenance-only mode |
| H005 Shared Task Box / Drop Ingress | HOME legacy runtime | HOME | C:\Users\Tom\My Drive\PAI_PROJECT\06_STATE\...\SHARED_TASK_BOX_R1\_stage\DROP_INGRESS_R7 | LIVE — task Running 2026-11-05; backlog/outcomes not read (Drive scope) |
| H006 Chief current gateway (8787) | Chief (HOME) | HOME | C:\ProgramData\PAI_CHIEF\generations\one-pai-source-9125efab237d-2894760a0e3c | LIVE — :8787 health 200 on 2026-11-05 |
| H007 Chief side-by-side bridge (8790) | Chief (HOME) | HOME | C:\ProgramData\PAI_CHIEF\launchers\context-carrier-economy-r1-c987c82738e7944f | LIVE — :8790 observed 2026-11-05; older frozen generation sharing chief-live.sqlite; retire only after consumer mapping |
| H008 Chief MCP Bridge Guard (8791) | Chief (HOME) | HOME | C:\ProgramData\PAI_BRIDGE_GUARD\guard.js | LIVE — :8791, task Running (last 2026-10-28) |
| H009 Chief MCP Guard / Grok lane router (8788) | Chief (HOME) | HOME | C:\ProgramData\PAI_GATEWAY_GUARD\guard.js + PAI_GROK_LANE_MSI_V1\runtime-1.1.2 | LIVE — listener up 2026-11-05 |
| H010 Chief MCP Tunnel V1 | Chief (HOME) | HOME | C:\ProgramData\PAI_CHIEF\start-chief-mcp-tunnel.ps1 | RUNNING — task since 2026-10-26; public reachability not tested |
| H011 One PAI Monitor (17892) | Chief (HOME) | HOME | C:\ProgramData\PAI_ONE_PAI_MONITOR\one-pai-monitor-targeted-live-r2-20260916 | LIVE — :17892 listener 2026-11-05; derived view, not a scheduler |
| H012 Chief continuity SQLite store | Chief (HOME) | HOME | C:\ProgramData\PAI_CHIEF\state\chief-live.sqlite | Persisted — main mtime 2026-10-20, WAL mtime 2026-10-31; no new semantic write established on 2026-11-05 |
| H013 Chief automatic continuity runtime V1 | Chief (HOME) | HOME | C:\ProgramData\PAI_CHIEF\generations\one-pai-source-9125efab237d-2894760a0e3c\src\one_pai\chief\CORE\chief_continuity_runtime_v1 | Source present in live generation; sessions=3 (main checkpoint) |
| H014 Continuity Memory Rooms V1 | Chief (HOME) | HOME | ...\CORE\continuity_memory_rooms_v1 (in chief-live.sqlite) | Data-bearing — 8 rooms / 357 fragments / 256 packages / 9 cards (main checkpoint) |
| H015 Standalone Rooms database | Chief (HOME) | HOME | C:\Users\Tom\AppData\Local\PAI\continuity-memory-rooms\rooms.sqlite | Persisted — 1 room / 2 fragments; mtime 2026-10-19; current owner/use unknown |
| H016 Prompt Evidence Ledger / Bundles | Chief (HOME) | HOME | ...\CORE\pai_prompt_continuity_v1 (tables in chief-live.sqlite) | Persisted — 39 evidence events / 12 bundles (main checkpoint) |
| H017 Claim Personal Memory / Character store | HOME legacy runtime | HOME | pai-run-loop.db tables personal_memory_records/mutations (via claim-service gen native-maint-r8-v5) | LIVE interface — 230 records / 241 mutations (main checkpoint); enabled in config |
| H018 Character/Leona continuity adapter | HOME legacy runtime | HOME | claim-service gen …\CHARACTER_CONTINUITY.md + character-context-query.js + tools\leona-mcp-stdio.cjs | LIVE stdio process observed 2026-11-05; E2E not re-run |
| H019 Older personal continuity JSONL impl | Chief (HOME) | HOME | C:\ProgramData\PAI_CHIEF\generations\context-carrier-economy-r1-...\pai_personal_continuity_v1 | SOURCE-ONLY — configured canonical store empty; retire as writer after compat tests |
| H020 Old per-user Chief journal DB | Chief (HOME) | HOME | C:\Users\Tom\.pai\PAI_CHIEF\state\chief-live.sqlite | DORMANT — 40,960B, mtime 2026-09-03; no current task binding |
| H021 Learning journal + resident projections | HOME legacy runtime | HOME | C:\ProgramData\PAI_SIMPLE_BODY_R1\HOME\learning-journal-r1 + resident-state projections | Persisted — newest archive/ACK index 2026-11-02 |
| H022 PAI Mind operational evidence | HOME legacy runtime | HOME | C:\ProgramData\PAI_RUN_LOOP\pai-mind | Persisted — newest events 2026-11-01; no 2026-11-05 write seen |
| H023 Chief context-economy (current gen) | Chief (HOME) | HOME | one-pai-source-9125efab…\src\one_pai\chief\CORE\chief_chat_bridge_v1\src\context-economy | Source in live generation (dir mtime 2026-10-19); per-module savings not measured |
| H024 Context-carrier generation (older) | Chief (HOME) | HOME | context-carrier-economy-r1-c987c82738e7944f\...\src\context-economy | OLDER — 5 files dated 2026-09-17, behind live 8790 gateway; version predecessor |
| H025 Context contracts + budget ledger (QA copy) | Chief (HOME) | HOME | C:\temp\PAI_MEMORY_ROOMS_INDEPENDENT_QA_d9b0e6259a5f49ccbaba599695bb146f\CORE\chief_chat_bridge_v1\src\context-economy | QA/source copy, files 2026-09-20; not the deployed copy |
| H026 Resident context packet compiler r16 | HOME legacy runtime | HOME | resident gen r27-incremental\payload\...\lib\compile-executor-context-packet-r16.cjs | Installed — preferred ceiling 8192 / hard 12288 (source constants, 2026-11-05 read) |
| H027 Provider token control R5 (Grok) | HOME legacy runtime | HOME | resident gen r27-incremental\payload\...\lib\grok-provider-token-control-r5.cjs + resident-state\provider-token.grok.json | Installed — accepted telemetry file mtime 2026-09-17; quotas honestly UNKNOWN in source |
| H028 Work-unit budget / economics modules | HOME legacy runtime | HOME | C:\ProgramData\PAI_RELEASES\efa77246…\PAI_PROJECT\CORE\work_unit_budget_v1; checkout pai-core-private\src\one_pai\runtime | Source located 2026-11-05; current per-module execution unknown |
| H029 home-cp | HOME runtime | HOME | C:\temp\home-cp | ACTIVE files — idempotency.jsonl mtime 2026-11-04; on-demand CLI, no daemon by design (= registry home-pc-cp) |
| H030 pai-terminal / Seed Kit R8 | HOME runtime | HOME | C:\temp\home-cp\pai-terminal; seed-kit-r8 | Source Oct 2026; bounded bridge LIMIT=12000; no invocation performed by census |
| H031 cp-runtime-r8 / capability work dirs | HOME runtime | HOME | C:\temp\home-cp\work\cp-runtime-r8 et al. | Scratch — only pty-probe.cjs (2026-10-17) at top level; retire after export |
| H032 PAI Terminal + Continuity plugin source | HOME runtime | HOME | C:\Users\Tom\plugins\pai-terminal; C:\Users\Tom\plugins\pai-continuity | Source dirs Sep 2026; wrappers, no extra stores |
| H033 TOM HOME local room app | TOM domain | HOME | C:\Users\Tom\PAI_CANDIDATES\TOM_PAI_HOME_V1; AppData\Local\PAI\tom-home\room.json | STOP_STATE 2026-10-19 = NOT_ADMITTED; no :4891 listener 2026-11-05; synthetic/local journal |
| H034 TOM continuity Stage B + R3 candidates | TOM domain | HOME | C:\Users\Tom\PAI_CANDIDATES\TOM_PAI_CONTINUITY_V1\...; TOM_PAI_R3_STORAGE | Candidates — newest receipts 2026-10-18; synthetic fixtures, no live owner integration |
| H035 Conversation identity ledger | HOME runtime | HOME | C:\Users\Tom\AppData\Local\PAI\pai-conversation-identity\ledger.jsonl | Persisted — 437B, mtime 2026-10-19; metadata only |
| H036 Leona continuity dev checkout | HOME runtime | HOME | C:\Users\Tom\.codex\artifacts\leona-continuity-r1-20261016 | Source — newest 2026-10-18; leona-operational parts explicitly synthetic |
| H037 Leona claim base snapshot | HOME runtime | HOME | C:\Users\Tom\.codex\artifacts\leona-claim-base-5c556db2 | Source-only — newest 2026-10-16; retire after hash preservation |
| H038 Spine convergence workspace | HOME runtime | HOME | C:\Users\Tom\.codex\workspaces\spine-convergence-r1 (+ -evidence) | Historical source — newest manifest 2026-09-28; name does NOT prove VM/HOME unification happened |
| H039 Memory Rooms independent QA tree | Chief (HOME) | HOME | C:\temp\PAI_MEMORY_ROOMS_INDEPENDENT_QA_d9b0e6259a5f49ccbaba599695bb146f\CORE | Source mirror — 726 files; newest edits 2026-10-19 despite Jul-23 root date |
| H040 Continuity control plane V1 | Chief (HOME) | HOME | QA tree + live gen: CORE\continuity_control_plane_v1 | Source observed 2026-11-05; precedence contract dated 2026-08-08; adapter, no own store |
| H041 Solution Knowledge V1 | Solution knowledge | HOME | QA tree + live gen: CORE\solution_knowledge_v1 | Contract/primitives — README 2026-07-20; persistence external by design; no own DB |
| H042 Knowledge Room V1 | Chief (HOME) | HOME | C:\temp\pai-run-loop-external-deps\knowledge_room_v1 + live gen CORE\knowledge_room_v1 | Derived read-only view — catalog authority NONE; external-deps newest 2026-08-11 |
| H043 Run Loop source snapshots / external deps | HOME legacy runtime | HOME | C:\temp\pai-run-loop-063b-snapshot; pai-run-loop-063b-deps; pai-run-loop-external-deps | Historical source — newest contents 2026-08-14; no DBs in walks |
| H044 Lean Work Supply snapshot | HOME legacy runtime | HOME | C:\temp\lean-work-supply-plane-v1-snapshot | Historical — newest test 2026-08-12; pure projection, no storage |
| H045 Program Graph Ledger snapshot | HOME legacy runtime | HOME | C:\temp\program-graph-ledger-v1-snapshot | Historical — deployment unknown; embedded 1980 timestamps not trustworthy |
| H046 BF1 QA/log/bundle estate (group of 48 packages) | HOME runtime | HOME | C:\temp\PAI_BF1_QA_R1; C:\temp\BF1_HOME_DIRECT_LOGS; C:\temp\BF1_INCOMING | QA estate — newest 2026-09-01; individually verified in inventory Part II (see Gaps note G1) |
| H047 Billion W1 graph/Result work | HOME runtime | HOME | C:\temp\PAI_BILLION_W1 | Historical source/evidence — latest file 2026-07-24; runtime use unknown |
| H048 Bridge canary eval / port experiment | Chief (HOME) | HOME | C:\temp\bridge-canary-eval-20261028; C:\temp\bridge-port-20261028 | Canary DB copies — latest 2026-10-28; retire execution after evidence preservation |
| H049 Context ingress R3/R3b canaries | Chief (HOME) | HOME | C:\temp\pai-chief-context-ingress-r3-canary; -r3b-canary | Canary copies — receipts 2026-09-18; no runtime binding |
| H050 pai-boot HOME (credential pointers) | HOME runtime | HOME | C:\temp\pai-boot | Pointer files only (2 token-bridge files, 2026-10-28) — contents NOT opened; catalogue reference only, NEVER commit |
| H051 BGE retrieval trial (bge-m3 + reranker) | HOME runtime | HOME | C:\temp\trial2-rerun (models, stage_b.py, stage_c.py) | Offline trial — results 2026-11-01; no serving process; evaluation fixture only |
| H052 VM TOM review bundles on HOME | TOM domain | HOME | C:\temp\review-slice2; review-slice2-fix1; review-slice2-fix2 | Review copies — outputs 2026-11-05; not a live TOM deployment |
| H053 PAI query review carrier | Leona | HOME | C:\temp\review-pai-query\bundle.b64 | Transport artifact — 1,698,000B, mtime 2026-11-05; not executed by census |
| H054 Public Context Kit / source-only resume | tantanpq | HOME | C:\Users\Tom\Documents\GitHub\Pai\capabilities\context (+ runbooks) | PACKAGE_CANDIDATE — README mtime 2026-09-10 |
| H055 Private One PAI source checkout | tantanpq | HOME | C:\Users\Tom\Documents\GitHub\pai-core-private\src\one_pai | Source checkout — latest files 2026-09-29; checkout is not deployment proof |
| H056 Two-capsule convergence workspace | HOME runtime | HOME | C:\Users\Tom\AppData\Local\PAI-ops\tom-chief-two-capsule-convergence-20261019 | Evidence/source — newest doc 2026-10-20 |
| H057 LocalDispatcher historical bridge | HOME runtime | HOME | C:\Users\Tom\AppData\Local\PAI-Chief\LocalDispatcher | DORMANT evidence — root mtime 2026-10-04; routing paused; no current binding proven |
| H058 Scoring Service API / jobs DB | Scoring domain | HOME | C:\scoring-service; jobs.db | NOT SERVING at :8000 on 2026-11-05 (health FAIL ×406, task Disabled since 2026-10-27) — consistent with Tân's DORMANT order for scoring; data/source intact, 449 jobs (main checkpoint) |
| H059 Scoring queue / health / ledger | Scoring domain | HOME | C:\temp\score-queue; C:\scoring-service\ledger_export.db | DORMANT with scoring — worker log last 2026-10-13; ledger export last 2026-10-27 |
| H060 Ollama HOME + num_ctx experiment | HOME runtime | HOME | C:\Users\Tom\.ollama; C:\temp\ollama-test; scoring-service\standard-v1\reports.py | Config evidence — reports.py pins num_ctx 8192 (read 2026-11-05); source config, not a running-scorer proof (= registry Ollama) |
| H061 Codex memory/session store (HOME) | External agent (Codex) | HOME | C:\Users\Tom\.codex\memories; memories_v2; sessions; archived_sessions | Agent-owned — sessions newest 2026-11-05; metadata only, bodies not analyzed; NOT a PAI authority |
| H062 Codex internal SQLite (HOME) | External agent (Codex) | HOME | C:\Users\Tom\.codex\*.sqlite (memories_1, thread_history_1, state_5, …) | Agent-owned — metadata only, contents not opened |
| H063 Other agent stores (HOME) | External agents | HOME | C:\Users\Tom\.grok; C:\Users\Tom\.gemini; C:\Users\Tom\.claude\projects | Agent-owned (Grok/Gemini/Claude) — dirs Jun→Nov 2026; freshness not audited |
| H064 Context7 cached integration | External | HOME | C:\Users\Tom\.claude\plugins\...\context7; C:\Users\Tom\.grok\marketplace-cache\...\context7 | Cache presence only — enabled/network state unverified |
| H065 Context-economy package/site copies (group) | HOME runtime | HOME | C:\temp\pai-cp-free-pushc-home\gateway; pai-cp-mkt\work\gateway; cmm-* repos; zline-* trees; mf-p2c-build | Copies of the same context families, Oct 2026; no new authority |
| H066 HOME CP publish/review evidence copies (group) | HOME runtime | HOME | C:\temp\homecp-*-publish-20261027; homecp-independent-review-20261019-r5 | Evidence copies — publish tasks last ran 2026-10-27 |
| H209 Historical voice-assistant context source | HOME runtime | HOME | C:\temp\PAI-HOME-PERSONAL-VOICE-ASSISTANT-R8\overlay\apps\local-shell\assistant-context.js (+ R7/R9/R10 siblings) | Historical source — files Jul 2026; current runtime use not established |

## G. Systems — MSI catalogue (Workstream A inventory, per evidence pack only, 2026-11-05)

| Name | Owner | Machine | Path | State (dated) |
|---|---|---|---|---|
| M001 MSI Simple Body Resident | HOME legacy runtime (worker candidate) | MSI | Task \PAI MSI Simple Body Resident; C:\Users\tanta\.pai | RUNNING per pack — last 2026-11-04 result 267009; install path + DB binding UNKNOWN |
| M002 MSI Worker Host Agent / Transport / Commander | PAI ops | MSI | Tasks \PAI MSI Worker Host Agent; \PAI MSI Worker Transport; \PAI MSI Remote Commander | Tasks present per pack (Nov 2026); install paths UNKNOWN; result codes are not end-to-end proof |
| M003 MSI Grok Lane agent | PAI ops | MSI | Task \PAI Grok Lane MSI V1 Agent | RUNNING per pack — last 2026-11-04; binding unverified |
| M004 TokenEconomizer trial source | PAI ops | MSI | C:\temp\tokenecon-trial\clone\tokeneconomizer | Source present (2026-10-31); daemon/performance NOT re-verified (= registry TokenEconomizer) |
| M005 TokenEconomizer repo caches | PAI ops | MSI | C:\Users\tanta\.tokeneconomizer\repos\* (9 repo indexes) | Caches Oct 2026-10-31 → 11-01; root mtime 2026-11-05 01:05; content/quality not read |
| M006 Spine slice0 review estate (group) | Leona | MSI | C:\temp\spine-challenge; spine-review; spine-slice0-review; spine-slice0-r2…r16 | Review copies, all 2026-10-31; NOT 15 running spines |
| M007 Claim-register review/probe estate (group) | Leona | MSI | C:\temp\claimreg-r7-audit-20261101; claimreg-review*; claimreg-round3…7-probes | Test copies 2026-11-01; no live claims.jsonl binding |
| M008 Legacy claim-service learning copy | HOME legacy runtime | MSI | C:\temp\claim-service-learning-live-r1-6b281c04 | Historical source (Aug 2026); runtime activity UNKNOWN despite 'live' name |
| M009 Context Efficiency experiment | PAI ops | MSI | C:\Users\tanta\PAI_CONTEXT_EFFICIENCY_20260806 | Folder mtime 2026-08-06 only; contents/effectiveness UNKNOWN |
| M010 DeepTutor trial memory/KB | Trial | MSI | C:\temp\deeptutor-trial\data\memory; data\knowledge_bases | Trial dirs newest 2026-11-04; last task result 1 (failed); no production qualification |
| M011 LightRAG benchmark repo | Trial | MSI | C:\temp\pai-bench\repos\lightrag | Benchmark candidate — dir mtime 2026-11-05; no deployment proof |
| M012 MSI Ollama inference | PAI ops | MSI | Task \OllamaServe; C:\Users\tanta\.ollama | Task RUNNING per pack (2026-11-04); model/embedding endpoint NOT verified |
| M013 Notebook CP variants | PAI ops | MSI | C:\temp\notebook-cp; notebook-cp-9333; notebook-cp-backup-20261031-v1.9.0; nbcp-r19-test | Variants Oct 2026; no daemon/authority proof (= registry notebook-cp) |
| M014 Codex CP jobs/work | PAI ops | MSI | C:\temp\codex-cp\jobs; work; leona-e2e | Job envelopes Oct→Nov 2026; auxiliary executor queue, not a general spine |
| M015 MSI pai-boot | PAI ops | MSI | C:\temp\pai-boot | UNKNOWN contents (dir mtime 2026-10-28) — do NOT infer from HOME same-name credential folder |
| M016 PAI context/context-economy packaging variants | PAI ops | MSI | C:\temp\pai-naming-fix\capabilities\*; C:\temp\pai-refresh\capabilities\*; C:\temp\pai-pkg | Source copies Oct 2026; no runtime proof |
| M017 Repository review bundle (group) | Leona | MSI | C:\temp\repo-review\{PAI, pai-continuity, pai-cp, pai-cp-free, pai-reliability-evidence, leona-scoring-standards, leona-tool-bundle} | Review worktrees Oct 2026; not a second runtime |
| M018 MSI Codex agent stores | External agent (Codex) | MSI | C:\Users\tanta\.codex\sessions; memories_1.sqlite; state_5.sqlite; thread_history_1.sqlite; goals_1.sqlite; queue_1.sqlite | Agent-owned — thread_history newest 2026-11-05; metadata only |
| M019 MSI Gemini/Antigravity knowledge | External agent (Gemini) | MSI | C:\Users\tanta\.gemini\antigravity-cli\knowledge; C:\temp\backups\antigravity-cli-snap-20261027 | Knowledge dir Sep 2026; current use UNKNOWN |
| M020 MSI Grok continuity sessions | External agent (Grok) | MSI | ~/.grok/sessions/* (spine-challenge, home-cp, pai-cp-mkt, …) | Session journals Oct 2026; not PAI canonical memory |
| M021 MSI onboarding node package | PAI legacy | MSI | C:\Users\tanta\Downloads\PAI_MSI_ONBOARD\pai_node_package_v1 | Legacy — test tasks Disabled since Sep 2026; disabled task ≠ dead files |
| M022 MSI CECL/RSM knowledge candidates | Solution knowledge | MSI | C:\Users\tanta\PAI_CANDIDATES\PAI_PRODUCT_DISTRIBUTION_STAGING_R1\CECL_* | Staging Sep 2026; durable persistence not shown |
| M023 MSI minimal operating-loop candidate | PAI legacy | MSI | C:\Users\tanta\PAI_MINIMAL_SELF_OPERATING_LOOP_V0 | Folder only (Aug 2026); backend/runtime UNKNOWN |
| M024 HOME CP copy on MSI | PAI ops | MSI | C:\temp\home-cp | Copy — root mtime 2026-10-27; no proof it controls HOME now |
| M025 CP product bundles / qualification scratch (group) | PAI ops | MSI | C:\temp\pai-cp-free-pushc-20261016215511; pai-cp-mkt; pai-cp-r1-native-qualification-20261014; … | Packaging/test copies Oct 2026; runtime not proven |
| M026 Leona tool-bundle versions (group) | Leona | MSI | C:\temp\leona-tool-bundle-clone; -rel110; -verify110; -wt; leona-ops; leona-presence; leona-proof | Worktrees Oct 2026; memory ownership not established |
| M027 MSI reliability sentinel | PAI ops | MSI | Task \PAI-Reliability-Sentinel-R14 | Ready — last 2026-11-05 07:59 result 0; install path UNKNOWN; health evidence only |
| M028 Codex daily production + ChatGPT lane | PAI ops | MSI | Tasks \CodexDailyProduction; \ChatGPTLane-MSI; C:\temp\codex-prod | Tasks Ready, last runs 2026-11-05 result 0 (= registry codex-prod / ChatGPT worker) |
| M029 MSI historical campaign/acceleration estate (group) | PAI legacy | MSI | C:\Users\tanta\PAI_ACCEL_*; PAI_CAMPAIGN_20260806; PAI_CODEX_E2E_R1; … | Legacy evidence Aug 2026; no current backend proven |
| M030 Other CP retrieval/action surfaces (group) | PAI ops | MSI | C:\temp\{chatgpt-cp, dom-cp, github-cp, grok-cp, msi-cp, rea-cp, meta-cp, suno-cp, reel-cp, youtube-cp, windows-mcp-trial} | Presence only per pack, roots Oct→Nov 2026; per-tool detail in §A; credential dirs inside are NOT token economy |

## Gaps — assets not entered individually, with reason

- **G1 — HOME bulk catalogue groups (143 entries):** the inventory's 48 BF1
  package directories (H047-series detail in Part II), 24 one-pai-home
  artifact directories, 55 historical candidate/staging directories, and 15
  shallow Drive-mirror pointers are individually verified in
  `INVENTORY_AND_CONSOLIDATION_MAP.md` Part II but are seeded here only as
  the group entries H046-adjacent/BF1 estate + this note. Reason: they are
  QA/evidence/package copies, not separate systems; per-entry import is a
  Phase 0 manifest task, not a Phase 1 skeleton task.
- **G2 — MSI authority binding:** MSI resident/worker tasks (M001–M003) have
  no task-action/DB binding in the evidence pack, so no entry can state
  whether MSI is a third spine authority or a HOME worker. UNKNOWN by
  evidence, per plan §9 — Phase 0 collects read-only MSI evidence.
- **G3 — Claim-count discrepancy:** VM claim-register is 267 admitted in the
  inventory's direct count vs 272 claim records in the query pilot's index
  (V002/V007). Neither number overwrites the other; reconciliation is an
  explicit Phase 0 deliverable.
- **G4 — Drive vault contents:** Drive is a pointer layer in this census
  (task-box ingress, manifests, mirrors). Vault document bodies were out of
  census scope; assets living only inside Drive documents have no entries
  yet. Phase 0 manifest must declare its Drive scope explicitly.
- **G5 — ProgramData interiors (HOME):** release/repair/backup directory
  interiors beyond targeted owners were enumerated by name only; the Q
  family (registry §3) sits deep in ProgramData and was not re-censused on
  2026-11-04/05. Entries exist at family level; per-item states are dated
  and may be stale.
- **G6 — GitHub contents vs installs:** the 8 PAI repos (§D) are entered as
  repos, but no commit-level reconciliation against HOME/MSI installs
  exists yet (plan §2). Locked decision 2 makes that reconciliation a
  manifest duty; until then "IN-USE" means repo-alive, not install-parity.
- **G7 — github-cp login:** github-cp's github.com login is unverified in
  both sources; its entry carries the caveat rather than a state upgrade.
- **G8 — External-agent stores:** Codex/Grok/Gemini/Claude stores (H061–H063,
  M018–M020) are entered as agent-owned pointers only — metadata-level, by
  design. Their contents are not PAI assets and are never merged (contract:
  admission-privacy-forget rule 5).
