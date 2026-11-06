# ADOPTION — F01-R1 citation reconciliation (Phase 3, Step 3)

Status: adopted by Leona under delegated authority, 2026-11-05. This record is
NOT an owner-signed decision and does not claim to be one. Overturn path: any
owner decision, or a future contract amendment defining an authorized citation
representation — applied prospectively only, never by amending history.

## The conflict

The focused re-review of the Step 3 fix round
(`CODEX_REREVIEW_STEP3_FIX_2026-11-05.md`, sha256 `d8fc2c60…46f6`) returned:
F03 PASS, F02 discharged (the vm-spine house-default adoption satisfies ruling
6(a) by the recorded-delegation branch; demonstration PASS), and F01 substance
PASS in full — every UNLINK corrects target, anchor, fold, rehearsal and
scope-hygiene check verified. The sole remaining item, finding F01-R1, is
representational, and the reviewer prescribed no data or code change:

- The re-review brief (written by Leona) asked that the SO-CAI section
  citation for each re-LINKed task appear inside the registry event's
  `reason` field.
- The Registrar's closed reason schema (`packages/cabinet/registrar.py`,
  lines 249–253) rejects any `reason` value outside its code vocabulary —
  an inline citation such as `title-citation:muc-8` would be refused at
  admission. All 12 re-LINK events correctly carry the closed code
  `title-citation`.
- The citations themselves live in the member tasks' titles, which are bound
  into each LINK event by segment digest, and the reviewer independently
  verified them correct (e.g. home-device-ops = section 8).

## The reconciliation adopted

**A section citation carried in the digest-bound title of the member record
satisfies the citation requirement for registry LINK events.** The closed
reason vocabulary stays closed: `reason` remains a machine-comparable code,
and provenance detail lives in digest-bound content — the same pattern the
registry already uses for F01 UNLINK evidence bindings and for privacy
inheritance under §6.

Consequences: no registry event is amended, no history is rewritten, the
Registrar is unchanged, and Step 3's closure is not blocked by F01-R1.

## Provenance

Adopted by Leona on 2026-11-05 under (a) the standing delegation for
in-framework execution decisions and (b) the owner's instruction of
2026-11-05 20:09 PT to complete the work without further choice rounds.
The reviewer framed F01-R1 explicitly as a reconciliation decision for the
parent, prescribing neither a history amendment nor a Registrar change; the
brief wording that created the conflict was Leona's own.
