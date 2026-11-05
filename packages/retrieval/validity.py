"""Knowledge Room validity gate — Phase 2 gate layer for PAI retrieval.

This module imports the deterministic gate rules of HOME's Knowledge Room V1
into the retrieval package. Source of the rules (read read-only on HOME,
2026-11-05):

  - C:\\temp\\pai-run-loop-external-deps\\knowledge_room_v1\\README.md
  - C:\\temp\\pai-run-loop-external-deps\\knowledge_room_v1\\src\\knowledge-room.js
    (compileKnowledgeCapsule / freshness / applicability / validateItem)
  - C:\\temp\\pai-run-loop-external-deps\\knowledge_room_v1\\tests\\knowledge-room.test.js
  - C:\\ProgramData\\PAI_CHIEF\\generations\\one-pai-source-9125efab237d-2894760a0e3c\\
    src\\one_pai\\chief\\CORE\\knowledge_room_v1\\src\\knowledge-room.js
    (second deployment; byte-identical rules, 1-byte whitespace difference)

Knowledge Room's stated retrieval order (README, verbatim):
  "state -> project/domain validity -> freshness -> counterevidence
   -> lexical/task relevance -> budget"
and: "Only ACTIVE items are returned by the default compiler. Stale,
challenged, superseded, archived, revoked, candidate and counterevidenced
items are excluded." Exclusions are REPORTED with reasons, never silent —
this module follows that: gate() returns (passed, reason) per record and the
query layer surfaces an `excluded` list.

Field mapping (Knowledge Room -> this package's records):
  item.status (CANDIDATE/QUALIFIED/ACTIVE/CHALLENGED/SUPERSEDED/ARCHIVED/REVOKED)
    -> record.lifecycle mapped as: unadmitted->CANDIDATE, admitted->ACTIVE,
       invalidated->REVOKED, superseded->SUPERSEDED, expired->ARCHIVED.
       QUALIFIED/CHALLENGED have no house-source equivalent yet.
  item.validity.projectId -> record.validity_project (house records: "PAI")
  item.domain ("GLOBAL" matches any context domain)
    -> record.domain (free-text house domains, compared slug-normalized —
       an adaptation, documented in the package README)
  item.validity.environments / item.validity.releases
    -> record.validity_environments / record.validity_releases
       (no current house source populates these; the gate logic is KR's,
        applied only when the record declares a non-empty list, as in KR)
  item.review.freshUntil -> replaced by this package's STRONGER freshness
    signal: the content-hash / WAL-aware STALE gate over live sources.
    KR: freshUntil absent -> CURRENT_BY_TRIGGER (pass); past -> STALE;
    unparseable -> INVALID_FRESHNESS. Here: source unchanged -> pass;
    source changed or missing -> STALE; fingerprint error -> INVALID_FRESHNESS.
  item.evidenceAgainst (non-empty -> COUNTEREVIDENCE_PRESENT)
    -> record.evidence_against. In the claim register, counterevidence is
       realized as INVALIDATE events, which land in the STATE gate
       (lifecycle=invalidated); the explicit-field check is implemented for
       any source that populates it.
  relevance threshold: KR excludes score < 0.16 as LOW_RELEVANCE, where its
    score is a weighted formula over fields PAI records mostly do not
    carry (temperature; salience only when a source declares it).
    ADAPTATION: the threshold RULE is imported; the score here is BM25
    normalized to [0,1) as s/(s+1). See README.
  budget: KR budget is an integer in [1, 32] (default 8), applied after
    relevance sorting (KR order: score desc, salience desc, knowledgeId
    asc — the query layer sorts identically); out-of-range budget is an
    error (KNOWLEDGE_BUDGET_INVALID). Imported as the --limit bounds.
  applicability: KR checks item.validity.projectId and item.domain, then
    environment/release lists. This package additionally reads the
    record's declared validity_domains scope (fix round 1).
  unknown lifecycle: KR validates its state enum up front; an unmapped
    house lifecycle is excluded as STATE_UNKNOWN, never silently ACTIVE
    (fix round 1).

Pure functions, stdlib only, no I/O. The query layer supplies per-source
freshness states computed by its STALE gate.
"""

# Knowledge Room ACTIVE_READ = {"ACTIVE"}: only ACTIVE passes by default.
STATE_MAP = {
    "admitted": "ACTIVE",
    "unadmitted": "CANDIDATE",
    "invalidated": "REVOKED",
    "superseded": "SUPERSEDED",
    "expired": "ARCHIVED",
}

BUDGET_MIN = 1
BUDGET_MAX = 32
RELEVANCE_THRESHOLD = 0.16  # KR: score < 0.16 -> LOW_RELEVANCE


class BudgetInvalid(ValueError):
    """Mirror of KR's KNOWLEDGE_BUDGET_INVALID."""


def check_budget(budget):
    if not isinstance(budget, int) or isinstance(budget, bool) \
            or budget < BUDGET_MIN or budget > BUDGET_MAX:
        raise BudgetInvalid(
            f"KNOWLEDGE_BUDGET_INVALID: budget must be an integer in "
            f"[{BUDGET_MIN}, {BUDGET_MAX}], got {budget!r}")
    return budget


def kr_state(record):
    """Map the house lifecycle onto KR states. KR validates its state enum
    before compiling (knowledge-room.js validateItem -> KNOWLEDGE_ITEM_ENUM_INVALID),
    so an unknown house lifecycle must NOT silently become ACTIVE: it maps
    to None here and gate() excludes it as STATE_UNKNOWN (fix round 1,
    Codex Phase 2 review area 5 boundary finding)."""
    return STATE_MAP.get(record.get("lifecycle", "admitted"))


def _slug(s):
    return "-".join(str(s or "").lower().replace("/", " ").split())


def applicability(record, context):
    """KR applicability(): returns an exclusion reason string or None.

    Order inside KR: project -> domain -> environments -> releases.
    """
    proj = record.get("validity_project")
    if proj and context.get("project_id") and proj != context["project_id"]:
        return "PROJECT_MISMATCH"
    ctx_domain = context.get("domain")
    if ctx_domain:
        rec_domain = record.get("domain") or ""
        if rec_domain != "GLOBAL":
            rs, cs = _slug(rec_domain), _slug(ctx_domain)
            if rs != cs and cs not in rs and rs not in cs:
                return "DOMAIN_MISMATCH"
        # Declared validity scopes: when the record declares the domains it
        # is valid in (validity_domains, populated by the indexer), the
        # context domain must be one of them — the gate actually reads the
        # field (fix round 1, Codex Phase 2 review area 5 row 8).
        scopes = record.get("validity_domains") or []
        if scopes:
            cs = _slug(ctx_domain)
            ok = False
            for s in scopes:
                if s == "GLOBAL":
                    ok = True
                    break
                ss = _slug(s)
                if ss == cs or cs in ss or ss in cs:
                    ok = True
                    break
            if not ok:
                return "DOMAIN_MISMATCH"
    envs = record.get("validity_environments") or []
    if envs:
        if not context.get("environment"):
            return "ENVIRONMENT_REQUIRED"
        if context["environment"] not in envs:
            return "ENVIRONMENT_MISMATCH"
    rels = record.get("validity_releases") or []
    if rels:
        if not context.get("release"):
            return "RELEASE_REQUIRED"
        if context["release"] not in rels:
            return "RELEASE_MISMATCH"
    return None


def gate(record, context, source_freshness, waive_state=False):
    """Apply the KR gate order to one record (relevance and budget are
    applied by the caller, as in KR's compile loop).

    record: index record dict.
    context: {project_id, domain, environment, release}
    source_freshness: "FRESH" | "STALE" | "INVALID_FRESHNESS" for the
        record's source, from the query layer's STALE gate.
    waive_state: skip ONLY stage 1 (state). This is the whole content of
        the documented query opt-ins (--include-unadmitted, --history):
        they waive the state reason they name and nothing else — stages
        2-4 still run (fix round 1, Codex Phase 2 review blocker 2).

    Returns None when the record passes, else the KR exclusion reason.
    """
    # 1. state
    state = kr_state(record)
    if state is None:
        return "STATE_UNKNOWN"
    if state != "ACTIVE" and not waive_state:
        return f"STATE_{state}"
    # 2. project/domain validity
    reason = applicability(record, context)
    if reason:
        return reason
    # 3. freshness
    if source_freshness == "STALE":
        return "STALE"
    if source_freshness == "INVALID_FRESHNESS":
        return "INVALID_FRESHNESS"
    # 4. counterevidence
    if record.get("evidence_against"):
        return "COUNTEREVIDENCE_PRESENT"
    return None


def normalize_bm25(score):
    """Adaptation of KR's relevance scale: map a raw BM25 score to [0, 1)
    so the imported 0.16 LOW_RELEVANCE threshold is meaningful."""
    if score <= 0:
        return 0.0
    return score / (score + 1.0)
