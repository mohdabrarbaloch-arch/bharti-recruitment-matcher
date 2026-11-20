"""Explainable candidate-to-job matching.

Every score this module produces comes with its own arithmetic. A recruiter
who disagrees with a ranking can see which component moved it and by how much,
and argue with that component instead of the total.

Design rules, in order of importance:

1. **No hidden weights.** The weights are a module constant, they are returned
   in the response, and they sum to 1.0. A test asserts that.
2. **Missing data is not a zero.** A candidate with no location on their resume
   is not penalised for being in the wrong place; the location component is
   dropped and the remaining weights are renormalised. Scoring someone down for
   information you never had is how good candidates get filtered out.
3. **Related skills earn partial credit, never full.** "I know Vue" is worth
   0.45 of a React requirement, not 1.0.
4. **Gaps are named.** The output says which required skills are missing and
   which are only partially covered, so the recruiter knows what to ask about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.taxonomy import related_credit
from app.core.taxonomy import skill as lookup_skill

#: Component weights. Must sum to 1.0 — asserted in tests.
WEIGHTS: dict[str, float] = {
    "skills": 0.45,
    "experience": 0.25,
    "seniority": 0.15,
    "location": 0.10,
    "education": 0.05,
}

SENIORITY_LEVELS = ["intern", "junior", "mid", "senior", "lead", "principal"]


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------


@dataclass
class SkillHit:
    """One required skill and how well the candidate covers it."""

    skill: str
    label: str
    credit: float
    matched_via: str | None = None
    kind: str = "missing"  # exact | related | missing

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "label": self.label,
            "credit": round(self.credit, 3),
            "matched_via": self.matched_via,
            "kind": self.kind,
        }


@dataclass
class Component:
    """One scored dimension, with the arithmetic that produced it."""

    name: str
    weight: float
    score: float
    contribution: float
    reason: str
    applied: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "weight": round(self.weight, 3),
            "score": round(self.score, 3),
            "contribution": round(self.contribution, 3),
            "reason": self.reason,
            "applied": self.applied,
        }


@dataclass
class MatchResult:
    total: float
    components: list[Component]
    required_hits: list[SkillHit] = field(default_factory=list)
    nice_hits: list[SkillHit] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    verdict: str = ""
    confidence: str = "medium"

    def to_dict(self) -> dict:
        return {
            "total": round(self.total, 1),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "components": [c.to_dict() for c in self.components],
            "required_skills": [h.to_dict() for h in self.required_hits],
            "nice_to_have": [h.to_dict() for h in self.nice_hits],
            "gaps": self.gaps,
            "partial": self.partial,
            "strengths": self.strengths,
        }


# --------------------------------------------------------------------------
# Skill coverage
# --------------------------------------------------------------------------


def _label(name: str) -> str:
    found = lookup_skill(name)
    return found.label if found else name.replace("_", " ").title()


def score_skills(
    candidate_skills: list[str], required: list[str], nice: list[str]
) -> tuple[float, list[SkillHit], list[SkillHit], list[str], list[str]]:
    """Coverage of required and nice-to-have skills.

    Required skills set the score. Nice-to-haves can lift a partial match by up
    to 30% of the remaining gap, but they never drag a complete match below
    1.0 — a candidate with every required skill is a perfect skills fit whether
    or not they happen to have the extras.

    Returns (score, required_hits, nice_hits, gaps, partial).
    """
    owned = set(candidate_skills)

    def best_credit(wanted: str) -> tuple[float, str | None]:
        """Highest credit any owned skill gives toward `wanted`."""
        best = 0.0
        via: str | None = None
        for have in owned:
            credit = related_credit(have, wanted)
            if credit > best:
                best = credit
                via = have
        return best, via

    required_hits: list[SkillHit] = []
    gaps: list[str] = []
    partial: list[str] = []

    for wanted in required:
        credit, via = best_credit(wanted)
        if credit >= 1.0:
            kind = "exact"
        elif credit > 0:
            kind = "related"
            partial.append(wanted)
        else:
            kind = "missing"
            gaps.append(wanted)
        required_hits.append(
            SkillHit(
                skill=wanted,
                label=_label(wanted),
                credit=credit,
                matched_via=via,
                kind=kind,
            )
        )

    nice_hits: list[SkillHit] = []
    for wanted in nice:
        credit, via = best_credit(wanted)
        kind = "exact" if credit >= 1.0 else ("related" if credit > 0 else "missing")
        nice_hits.append(
            SkillHit(
                skill=wanted,
                label=_label(wanted),
                credit=credit,
                matched_via=via,
                kind=kind,
            )
        )

    required_score = (
        sum(h.credit for h in required_hits) / len(required_hits)
        if required_hits
        else 1.0
    )
    nice_score = (
        sum(h.credit for h in nice_hits) / len(nice_hits) if nice_hits else None
    )

    if nice_score is None:
        score = required_score
    else:
        # Nice-to-haves close part of a gap; they never cap a complete match.
        # A candidate with every required skill scores 1.0 whether or not they
        # happen to have the extras, because "missing a nice-to-have" is not a
        # reason to rank someone below a perfect fit. Where required coverage
        # is incomplete, the extras lift the score by up to 30% of the gap.
        score = required_score + (1.0 - required_score) * 0.3 * nice_score

    return score, required_hits, nice_hits, gaps, partial


# --------------------------------------------------------------------------
# Experience
# --------------------------------------------------------------------------


def score_experience(years: float, required_years: float) -> tuple[float, str]:
    """Years against the requirement, with diminishing returns above it.

    Meeting the bar is worth 1.0. Exceeding it is worth nothing extra — a
    candidate with 15 years is not 50% better than one with 10 for a role that
    asked for 5. Below the bar the score falls off linearly but never to zero,
    because 4 years against a 5-year ask is not the same as 0 years.
    """
    if required_years <= 0:
        return 1.0, "no experience requirement set"

    if years >= required_years:
        return 1.0, f"{years:.1f} yrs meets the {required_years:.0f} yr requirement"

    ratio = years / required_years
    # Floor at 0.15 so a near-miss still reads as a near-miss.
    score = max(0.15, ratio)
    return (
        score,
        f"{years:.1f} yrs against a {required_years:.0f} yr requirement ({ratio:.0%})",
    )


# --------------------------------------------------------------------------
# Seniority
# --------------------------------------------------------------------------


def score_seniority(candidate_level: str, required_level: str) -> tuple[float, str]:
    """Distance on the seniority ladder.

    One level off is a 0.75, two is 0.45, three or more is 0.15. Being
    *over*-qualified is penalised less than being under-qualified, because an
    over-qualified hire is a retention risk while an under-qualified one is a
    delivery risk — and only one of those can be fixed with a conversation.
    """
    try:
        c = SENIORITY_LEVELS.index(candidate_level)
        r = SENIORITY_LEVELS.index(required_level)
    except ValueError:
        return 0.5, "unrecognised seniority level, scored neutral"

    distance = c - r
    if distance == 0:
        return 1.0, f"exactly the {required_level} level asked for"
    if distance > 0:
        score = max(0.15, 1.0 - 0.25 * distance)
        return score, f"{candidate_level} is {distance} level(s) above {required_level}"
    gap = -distance
    score = max(0.15, 1.0 - 0.35 * gap)
    return score, f"{candidate_level} is {gap} level(s) below {required_level}"


# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------


def score_location(
    candidate_location: str | None, job_location: str | None, remote_ok: bool
) -> tuple[float, str, bool]:
    """Location fit. Returns (score, reason, applied).

    ``applied=False`` means the component is dropped and the remaining weights
    renormalised — which is what happens when either side is unknown. Scoring
    a candidate down for a blank field is a data-quality bug wearing a
    ranking's clothes.
    """
    if remote_ok:
        return 1.0, "role is remote, so location does not constrain", True

    if not candidate_location or not job_location:
        return 0.0, "location unknown on one side, component dropped", False

    c = candidate_location.strip().lower()
    j = job_location.strip().lower()
    if c == j:
        return 1.0, f"both in {job_location}", True
    if c in j or j in c:
        return 0.9, f"'{candidate_location}' and '{job_location}' overlap", True
    return 0.3, f"{candidate_location} vs {job_location} — relocation needed", True


# --------------------------------------------------------------------------
# Education
# --------------------------------------------------------------------------


#: Degree level, highest first. Each level lists the spellings that mean it.
#: This exists because "BSc Computer Science" does not contain the word
#: "bachelor", and a substring check therefore scored a perfectly qualified
#: candidate at 0.4. Abbreviations are the normal case on a resume, not the
#: exception, so they have to be first-class.
_DEGREE_LEVELS: list[tuple[str, tuple[str, ...]]] = [
    ("phd", ("phd", "ph.d", "doctorate", "doctoral")),
    (
        "master",
        ("master", "masters", "msc", "m.sc", "ms ", "m.s.", "mba", "m.phil", "mphil"),
    ),
    (
        "bachelor",
        (
            "bachelor",
            "bachelors",
            "bsc",
            "b.sc",
            "bs ",
            "b.s.",
            "be ",
            "b.e.",
            "btech",
            "b.tech",
            "bcs",
            "b.com",
            "bcom",
            "ba ",
            "b.a.",
        ),
    ),
    ("diploma", ("diploma", "intermediate", "fsc", "hsc", "associate degree")),
]


def _degree_level(text: str) -> str | None:
    """Highest degree level mentioned in `text`, or None."""
    lowered = f" {text.lower()} "
    for level, spellings in _DEGREE_LEVELS:
        for spelling in spellings:
            if spelling in lowered:
                return level
    return None


def score_education(
    candidate_education: list[str], required: str | None
) -> tuple[float, str, bool]:
    """Degree check. Only applied when the job actually asks for one.

    A higher degree satisfies a lower requirement: an MSc meets a "bachelor"
    ask. A lower degree does not satisfy a higher one, and says so.
    """
    if not required:
        return 0.0, "no education requirement set, component dropped", False

    if not candidate_education:
        return 0.2, "no education found on the resume", True

    joined = " ".join(candidate_education)
    req_level = _degree_level(required)
    have_level = _degree_level(joined)

    if req_level is None:
        # The requirement is free text we do not recognise ("BDS", "LLB").
        # Fall back to a substring check and be honest when it fails.
        if required.strip().lower() in joined.lower():
            return 1.0, f"resume mentions '{required}'", True
        return 0.4, f"education found but does not clearly match '{required}'", True

    if have_level is None:
        return (
            0.4,
            f"education found but no recognisable degree level for '{required}'",
            True,
        )

    order = [level for level, _ in _DEGREE_LEVELS]
    have_rank = order.index(have_level)
    req_rank = order.index(req_level)

    if have_rank == req_rank:
        return 1.0, f"holds a {have_level} degree, which is what was asked for", True
    if have_rank < req_rank:
        return 1.0, f"holds a {have_level} degree, which satisfies '{required}'", True
    return 0.4, f"holds a {have_level} degree, below the '{required}' requirement", True


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------


def _verdict(total: float, gaps: list[str], required_count: int) -> str:
    """A short human sentence. Deliberately blunt about the gaps."""
    missing_ratio = len(gaps) / required_count if required_count else 0.0

    if total >= 80 and missing_ratio == 0:
        return "Strong match — every required skill is covered. Worth a call today."
    if total >= 80:
        return (
            f"Strong match, but {len(gaps)} required skill(s) are missing. "
            "Ask about them first."
        )
    if total >= 65 and gaps:
        return (
            f"Good match, with {len(gaps)} required skill(s) missing — "
            "a short conversation would settle whether they matter."
        )
    if total >= 65:
        return "Good match — a short conversation would settle the open questions."
    if total >= 50:
        return "Partial match — real overlap, but the gaps are load-bearing."
    if total >= 35:
        return "Weak match — consider only if the pipeline is thin."
    return "Poor match — the core requirements are not met."


def _confidence(components: list[Component], warnings: list[str]) -> str:
    """How much to trust this score, based on how much data we actually had."""
    applied = [c for c in components if c.applied]
    if len(applied) <= 2 or len(warnings) >= 2:
        return "low"
    if len(applied) <= 3 or warnings:
        return "medium"
    return "high"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def match_candidate(
    *,
    candidate_skills: list[str],
    candidate_years: float,
    candidate_seniority: str,
    candidate_location: str | None,
    candidate_education: list[str],
    required_skills: list[str],
    nice_skills: list[str],
    required_years: float,
    required_seniority: str,
    job_location: str | None,
    remote_ok: bool,
    required_education: str | None,
    warnings: list[str] | None = None,
) -> MatchResult:
    """Score one candidate against one job, with full working shown."""
    warnings = warnings or []

    skill_score, req_hits, nice_hits, gaps, partial = score_skills(
        candidate_skills, required_skills, nice_skills
    )
    exp_score, exp_reason = score_experience(candidate_years, required_years)
    sen_score, sen_reason = score_seniority(candidate_seniority, required_seniority)
    loc_score, loc_reason, loc_applied = score_location(
        candidate_location, job_location, remote_ok
    )
    edu_score, edu_reason, edu_applied = score_education(
        candidate_education, required_education
    )

    raw = [
        Component(
            "skills",
            WEIGHTS["skills"],
            skill_score,
            0.0,
            _skill_reason(req_hits, nice_hits),
        ),
        Component("experience", WEIGHTS["experience"], exp_score, 0.0, exp_reason),
        Component("seniority", WEIGHTS["seniority"], sen_score, 0.0, sen_reason),
        Component(
            "location", WEIGHTS["location"], loc_score, 0.0, loc_reason, loc_applied
        ),
        Component(
            "education", WEIGHTS["education"], edu_score, 0.0, edu_reason, edu_applied
        ),
    ]

    # Renormalise over the components that actually applied. This is the
    # difference between "we don't know their location" and "their location
    # is wrong", and it is the single most important line in this function.
    applied_weight = sum(c.weight for c in raw if c.applied)
    if applied_weight <= 0:
        applied_weight = 1.0

    for component in raw:
        if component.applied:
            component.contribution = (
                component.score * (component.weight / applied_weight) * 100
            )
        else:
            component.contribution = 0.0

    total = sum(c.contribution for c in raw)

    strengths: list[str] = []
    exact = [h.label for h in req_hits if h.kind == "exact"]
    if exact:
        strengths.append(f"Has {', '.join(exact[:4])}")
    if candidate_years >= required_years > 0:
        strengths.append(
            f"{candidate_years:.0f} years against a {required_years:.0f} year ask"
        )
    if sen_score >= 1.0:
        strengths.append(f"At the right level ({candidate_seniority})")
    if loc_applied and loc_score >= 0.9:
        strengths.append("Location works")

    return MatchResult(
        total=total,
        components=raw,
        required_hits=req_hits,
        nice_hits=nice_hits,
        gaps=gaps,
        partial=partial,
        strengths=strengths,
        verdict=_verdict(total, gaps, len(required_skills)),
        confidence=_confidence(raw, warnings),
    )


def _skill_reason(req_hits: list[SkillHit], nice_hits: list[SkillHit]) -> str:
    """One sentence describing the skill coverage arithmetic."""
    if not req_hits:
        return "no required skills listed"

    exact = sum(1 for h in req_hits if h.kind == "exact")
    related = sum(1 for h in req_hits if h.kind == "related")
    missing = sum(1 for h in req_hits if h.kind == "missing")

    parts = [f"{exact}/{len(req_hits)} required skills exact"]
    if related:
        parts.append(f"{related} via a related skill")
    if missing:
        parts.append(f"{missing} missing")
    if nice_hits:
        nice_exact = sum(1 for h in nice_hits if h.kind == "exact")
        parts.append(f"{nice_exact}/{len(nice_hits)} nice-to-haves")
    return ", ".join(parts)
