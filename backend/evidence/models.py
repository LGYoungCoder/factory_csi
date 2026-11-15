"""LLM output schemas (validated with Pydantic) and code-enforced guardrails."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal["TESTER_MEASUREMENT_DRIFT", "PROCESS_PARAMETER_DEVIATION", "PRODUCT_MIX_SHIFT",
                   "MATERIAL_LOT_ISSUE"]
Support = Literal["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"]
VType = Literal["cross_retest", "reference_sample_check", "process_config_check"]
SUPPORT_RANK = {"INSUFFICIENT": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
EV_RE = re.compile(r"\bEV-\d{3,}\b")
BANNED = ("confirmed root cause", "the root cause is", "root cause has been identified", "proven", "definitely",
          "certainly caused")
BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(b) for b in BANNED) + r")\b", re.I)
_NEGATION = re.compile(r"\b(not|no|never|nor|without|cannot|isn't|is not|un)\b[\w\s,-]{0,25}$", re.I)


def overclaims(text: str) -> str | None:
    """Return the first overclaiming phrase that is not negated (e.g. 'not a proven cause' is allowed)."""
    for m in BANNED_RE.finditer(text or ""):
        if not _NEGATION.search(text[max(0, m.start() - 40):m.start()]):
            return m.group(0)
    return None


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class HypothesisDraft(_M):
    category: Category
    title: str = Field(max_length=300)
    statement: str = Field(max_length=3000, description="Explanation (≤120 words) citing Evidence IDs like EV-003")
    supporting_evidence: list[str] = Field(default_factory=list, description="Evidence IDs that support it")
    contradicting_evidence: list[str] = Field(default_factory=list, description="Evidence IDs that contradict it")
    missing_evidence: list[str] = Field(default_factory=list,
                                        description="≤5 checks or data that would discriminate, plain text")
    support: Support = Field(description="evidence support level, not a probability")
    recommended_verification_types: list[VType] = Field(default_factory=list)
    change_rationale: str | None = Field(default=None, max_length=2000,
                                         description="Only in updates: why the support changed, citing EV IDs")


    @field_validator("missing_evidence")
    @classmethod
    def _cap(cls, v: list[str]) -> list[str]:
        return v[:5]


class HypothesisSet(_M):
    hypotheses: list[HypothesisDraft] = Field(min_length=1, max_length=5)


class ExpectedOutcome(_M):
    outcome: str = Field(max_length=500, description="e.g. 'all retests PASS on EOL-A'")
    interpretation: Literal["supports", "contradicts", "neutral"]
    hypothesis_id: str


class ProposalDraft(_M):
    verification_type: VType
    serial_numbers: list[str] | None = Field(default=None, description="cross_retest only: 1–5 SNs from the candidate list")
    target_tester_id: str | None = Field(default=None, description="cross_retest only: EOL-A or EOL-B")
    tester_id: str | None = Field(default=None, description="reference_sample_check only")
    equipment_id: str | None = Field(default=None, description="process_config_check only: ST-10, ST-20 or ST-30")
    rationale: str = Field(max_length=2000, description="≤80 words, cite EV IDs")
    targets_hypotheses: list[str] = Field(default_factory=list)
    expected_outcomes: list[ExpectedOutcome] = Field(default_factory=list)
    cited_evidence: list[str] = Field(default_factory=list)

    @field_validator("expected_outcomes")
    @classmethod
    def _cap(cls, v: list) -> list:
        return v[:6]


class ProposalSet(_M):
    proposals: list[ProposalDraft] = Field(default_factory=list, description="≤3, ranked, best first")
    recommend_conclude: bool = False
    conclude_reason: str | None = Field(default=None, max_length=1000)

    @field_validator("proposals")
    @classmethod
    def _cap(cls, v: list) -> list:
        return v[:3]


class ConclusionDraft(_M):
    category: Literal["TESTER_MEASUREMENT_DRIFT", "PROCESS_PARAMETER_DEVIATION", "PRODUCT_MIX_SHIFT",
                      "MATERIAL_LOT_ISSUE", "INSUFFICIENT_EVIDENCE"]
    statement: str = Field(max_length=3000, description="≤120 words, cite EV IDs")
    cited_evidence: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list, description="≤6")

    @field_validator("open_questions")
    @classmethod
    def _cap(cls, v: list[str]) -> list[str]:
        return v[:6]


class ReportNarrative(_M):
    overview: str = Field(max_length=4000, description="Section 1 narrative (≤150 words), cite EV IDs")
    follow_up_actions: list[str] = Field(min_length=1, description="≤6 concrete actions")
    limitations: str = Field(max_length=3000, description="≤100 words")

    @field_validator("follow_up_actions")
    @classmethod
    def _cap(cls, v: list[str]) -> list[str]:
        return v[:6]


# --- guardrails -----------------------------------------------------------------------------
def cited_ids(text: str) -> set[str]:
    return set(EV_RE.findall(text or ""))


def hypothesis_errors(hs: HypothesisSet, known: set[str]) -> list[str]:
    errs = []
    cats = [h.category for h in hs.hypotheses]
    if len(set(cats)) != len(cats):
        errs.append("each category may appear only once")
    for h in hs.hypotheses:
        ids = set(h.supporting_evidence) | set(h.contradicting_evidence) | cited_ids(h.statement) \
            | cited_ids(h.change_rationale or "")
        unknown = sorted(ids - known)
        if unknown:
            errs.append(f"{h.category}: unknown evidence ids {unknown}; use only the listed Evidence IDs")
        both = set(h.supporting_evidence) & set(h.contradicting_evidence)
        if both:
            errs.append(f"{h.category}: {sorted(both)} cannot be both supporting and contradicting")
        if overclaims(h.statement + " " + (h.change_rationale or "")):
            errs.append(f"{h.category}: avoid overclaiming phrases {list(BANNED)}")
    return errs


def apply_guardrails(hs: HypothesisSet, evidence: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Drop unknown citations, enforce support rules. Returns (hypotheses, events)."""
    events: list[dict] = []
    out: list[dict] = []
    seen: set[str] = set()
    for h in hs.hypotheses:
        if h.category in seen:
            continue
        seen.add(h.category)
        d = h.model_dump()
        for key in ("supporting_evidence", "contradicting_evidence"):
            bad = [e for e in d[key] if e not in evidence]
            if bad:
                events.append({"type": "citation_dropped", "payload": {"item": f"{h.category}.{key}",
                                                                       "invalid_ids": bad}})
            d[key] = list(dict.fromkeys(e for e in d[key] if e in evidence))
        d["contradicting_evidence"] = [e for e in d["contradicting_evidence"] if e not in d["supporting_evidence"]]
        if not d["supporting_evidence"] and d["support"] != "INSUFFICIENT":
            events.append({"type": "support_downgraded", "payload": {"hypothesis_id": h.category, "from": d["support"],
                                                                     "to": "INSUFFICIENT",
                                                                     "reason": "no valid supporting evidence"}})
            d["support"] = "INSUFFICIENT"
        mech = [e for e in d["supporting_evidence"] if h.category in evidence[e].get("data", {}).get("mechanism", [])]
        if SUPPORT_RANK[d["support"]] >= SUPPORT_RANK["MEDIUM"] and not mech:
            events.append({"type": "support_downgraded", "payload": {
                "hypothesis_id": h.category, "from": d["support"], "to": "LOW",
                "reason": "no supporting evidence shows this mechanism directly"}})
            d["support"] = "LOW"
        if d["support"] == "HIGH" and not any(evidence[e]["kind"] == "verification" for e in d["supporting_evidence"]):
            events.append({"type": "support_downgraded", "payload": {"hypothesis_id": h.category, "from": "HIGH",
                                                                     "to": "MEDIUM",
                                                                     "reason": "HIGH requires supporting verification "
                                                                               "evidence"}})
            d["support"] = "MEDIUM"
        out.append(d)
    return out, events


def assign_ids(hyps: list[dict], id_map: dict[str, str]) -> list[dict]:
    """Stable hypothesis ids per category across rounds."""
    for h in hyps:
        if h["category"] not in id_map:
            id_map[h["category"]] = f"H-{len(id_map) + 1}"
        h["hypothesis_id"] = id_map[h["category"]]
    return sorted(hyps, key=lambda h: (-SUPPORT_RANK[h["support"]], h["hypothesis_id"]))


def to_support_level(s: str) -> str:
    """EvidenceSupport → Support_Level for evaluation."""
    return {"HIGH": "HIGH", "MEDIUM": "MEDIUM"}.get(s, "LOW")


def decide_conclusion(hyps: list[dict]) -> tuple[str, str]:
    """Top unique hypothesis with support ≥ MEDIUM, else INSUFFICIENT_EVIDENCE. Returns (category, support)."""
    if not hyps:
        return "INSUFFICIENT_EVIDENCE", "LOW"
    top = max(SUPPORT_RANK[h["support"]] for h in hyps)
    leaders = [h for h in hyps if SUPPORT_RANK[h["support"]] == top]
    if top < SUPPORT_RANK["MEDIUM"] or len({h["category"] for h in leaders}) > 1:
        return "INSUFFICIENT_EVIDENCE", "LOW"
    return leaders[0]["category"], to_support_level(leaders[0]["support"])


def judgment_changes(before: list[dict], after: list[dict], new_evidence: list[str]) -> list[dict]:
    b = {h["category"]: h for h in before}
    a = {h["category"]: h for h in after}
    out = []
    for cat in sorted(set(b) | set(a)):
        hb, ha = b.get(cat), a.get(cat)
        sb, sa = (hb or {}).get("support"), (ha or {}).get("support")
        if hb is None:
            direction = "new"
        elif ha is None:
            direction = "removed"
        elif SUPPORT_RANK[sa] > SUPPORT_RANK[sb]:
            direction = "up"
        elif SUPPORT_RANK[sa] < SUPPORT_RANK[sb]:
            direction = "down"
        else:
            direction = "unchanged"
        h = ha or hb
        because = sorted(set((ha or {}).get("supporting_evidence", []) + (ha or {}).get("contradicting_evidence", []))
                         & set(new_evidence)) if ha else []
        out.append({"hypothesis_id": h["hypothesis_id"], "category": cat, "before": sb, "after": sa,
                    "direction": direction, "because": because, "rationale": (ha or {}).get("change_rationale")})
    return out
