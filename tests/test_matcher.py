"""Tests for the matcher.

The two properties that matter most:

* the weights sum to 1.0, and
* a missing data point drops its component instead of scoring it zero.

The second one is the difference between "we don't know their location" and
"their location is wrong", and getting it wrong silently filters out good
candidates.
"""

from __future__ import annotations

import pytest

from app.core.matcher import (
    WEIGHTS,
    match_candidate,
    score_education,
    score_experience,
    score_location,
    score_seniority,
    score_skills,
)


def _match(**overrides):
    """A strong baseline match, with any field overridable."""
    defaults = {
        "candidate_skills": ["python", "postgres", "docker"],
        "candidate_years": 6.0,
        "candidate_seniority": "senior",
        "candidate_location": "Karachi",
        "candidate_education": ["BSc Computer Science"],
        "required_skills": ["python", "postgres", "docker"],
        "nice_skills": ["redis"],
        "required_years": 5.0,
        "required_seniority": "senior",
        "job_location": "Karachi",
        "remote_ok": False,
        "required_education": "bachelor",
    }
    defaults.update(overrides)
    return match_candidate(**defaults)


class TestWeights:
    def test_weights_sum_to_one(self) -> None:
        """If this fails, every score in the product is on a different scale
        than the UI claims."""
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_all_components_present(self) -> None:
        result = _match()
        names = {c.name for c in result.components}
        assert names == set(WEIGHTS)


class TestSkillScoring:
    def test_all_required_present_scores_one(self) -> None:
        score, hits, _, gaps, partial = score_skills(
            ["python", "postgres"], ["python", "postgres"], []
        )
        assert score == 1.0
        assert gaps == []
        assert partial == []
        assert all(h.kind == "exact" for h in hits)

    def test_missing_skill_is_named_as_a_gap(self) -> None:
        score, _, _, gaps, _ = score_skills(["python"], ["python", "docker"], [])
        assert score == pytest.approx(0.5)
        assert gaps == ["docker"]

    def test_related_skill_earns_partial_credit(self) -> None:
        score, hits, _, gaps, partial = score_skills(["vue"], ["react"], [])
        assert 0.0 < score < 1.0
        assert gaps == []
        assert partial == ["react"]
        assert hits[0].kind == "related"
        assert hits[0].matched_via == "vue"

    def test_nice_to_haves_lift_a_partial_match(self) -> None:
        """Nice-to-haves close part of a gap, so a candidate missing a
        required skill scores higher with the extras than without."""
        without = score_skills(["python"], ["python", "docker"], ["redis"])[0]
        with_nice = score_skills(["python", "redis"], ["python", "docker"], ["redis"])[
            0
        ]
        assert with_nice > without

    def test_nice_to_haves_do_not_cap_a_complete_match(self) -> None:
        """A candidate with every required skill is a perfect skills fit,
        whether or not they happen to have the extras. Missing a nice-to-have
        is not a reason to rank someone below a perfect fit."""
        perfect = score_skills(["python"], ["python"], ["redis"])[0]
        assert perfect == 1.0

    def test_no_required_skills_does_not_crash(self) -> None:
        score, hits, _, gaps, _ = score_skills(["python"], [], [])
        assert score == 1.0
        assert hits == []
        assert gaps == []

    def test_duplicate_required_skills_are_not_double_counted(self) -> None:
        score, hits, _, _, _ = score_skills(["python"], ["python", "python"], [])
        assert score == 1.0
        assert len(hits) == 2


class TestExperienceScoring:
    def test_meeting_the_bar_is_full_credit(self) -> None:
        score, _ = score_experience(5.0, 5.0)
        assert score == 1.0

    def test_exceeding_the_bar_is_not_extra_credit(self) -> None:
        """15 years is not 50% better than 10 for a 5-year role."""
        assert score_experience(15.0, 5.0)[0] == 1.0

    def test_below_the_bar_falls_off_but_not_to_zero(self) -> None:
        score, reason = score_experience(4.0, 5.0)
        assert 0.5 < score < 1.0
        assert "80%" in reason

    def test_zero_years_against_a_requirement_is_low_but_positive(self) -> None:
        score, _ = score_experience(0.0, 5.0)
        assert score == pytest.approx(0.15)

    def test_no_requirement_is_full_credit(self) -> None:
        assert score_experience(0.0, 0.0)[0] == 1.0


class TestSeniorityScoring:
    def test_exact_level(self) -> None:
        assert score_seniority("senior", "senior")[0] == 1.0

    def test_one_level_below_is_penalised(self) -> None:
        score, reason = score_seniority("mid", "senior")
        assert score == pytest.approx(0.65)
        assert "below" in reason

    def test_one_level_above_is_penalised_less(self) -> None:
        """Over-qualified is a retention risk; under-qualified is a delivery
        risk. Only one of those can be fixed with a conversation."""
        above = score_seniority("lead", "senior")[0]
        below = score_seniority("mid", "senior")[0]
        assert above > below

    def test_unknown_level_is_neutral(self) -> None:
        assert score_seniority("wizard", "senior")[0] == 0.5


class TestLocationScoring:
    def test_same_city(self) -> None:
        score, _, applied = score_location("Karachi", "Karachi", False)
        assert score == 1.0
        assert applied is True

    def test_remote_drops_the_constraint(self) -> None:
        score, reason, applied = score_location("Lahore", "Karachi", True)
        assert score == 1.0
        assert applied is True
        assert "remote" in reason

    def test_unknown_location_drops_the_component(self) -> None:
        """This is the important one: a blank field must not read as a
        mismatch."""
        score, reason, applied = score_location(None, "Karachi", False)
        assert applied is False
        assert "dropped" in reason

    def test_different_cities_are_penalised(self) -> None:
        score, _, applied = score_location("Lahore", "Karachi", False)
        assert applied is True
        assert score < 0.5


class TestEducationScoring:
    def test_no_requirement_drops_the_component(self) -> None:
        _, _, applied = score_education(["BSc"], None)
        assert applied is False

    def test_matching_degree(self) -> None:
        score, _, applied = score_education(["BSc Computer Science"], "bachelor")
        assert score == 1.0
        assert applied is True

    def test_higher_degree_satisfies_lower_requirement(self) -> None:
        score, reason, _ = score_education(["MSc Data Science"], "bachelor")
        assert score == 1.0
        assert "satisfies" in reason

    def test_missing_education_is_penalised_but_not_zero(self) -> None:
        score, _, applied = score_education([], "bachelor")
        assert applied is True
        assert 0.0 < score < 0.5


class TestRenormalisation:
    def test_dropped_component_does_not_lower_the_total(self) -> None:
        """A candidate with no location on their resume must not score lower
        than the same candidate with a matching location."""
        with_location = _match(candidate_location="Karachi")
        without_location = _match(candidate_location=None)
        assert without_location.total == pytest.approx(with_location.total, abs=0.01)

    def test_dropped_component_contributes_zero(self) -> None:
        result = _match(candidate_location=None)
        location = next(c for c in result.components if c.name == "location")
        assert location.applied is False
        assert location.contribution == 0.0

    def test_total_never_exceeds_one_hundred(self) -> None:
        result = _match()
        assert 0.0 <= result.total <= 100.0

    def test_perfect_candidate_scores_one_hundred(self) -> None:
        result = _match()
        assert result.total == pytest.approx(100.0, abs=0.5)


class TestVerdictAndConfidence:
    def test_strong_match_verdict_mentions_a_call(self) -> None:
        result = _match()
        assert "Strong match" in result.verdict

    def test_gaps_are_mentioned_in_the_verdict(self) -> None:
        result = _match(candidate_skills=["python"])
        assert "missing" in result.verdict.lower()

    def test_low_confidence_when_data_is_thin(self) -> None:
        result = _match(
            candidate_location=None,
            required_education=None,
            warnings=["no email", "no skills"],
        )
        assert result.confidence == "low"

    def test_high_confidence_with_full_data(self) -> None:
        result = _match()
        assert result.confidence == "high"

    def test_breakdown_serialises(self) -> None:
        payload = _match().to_dict()
        assert "total" in payload
        assert "components" in payload
        assert len(payload["components"]) == 5
        assert all("reason" in c for c in payload["components"])
