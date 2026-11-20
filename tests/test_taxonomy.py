"""Tests for the skill taxonomy.

These are the cheapest tests in the suite and they catch the most embarrassing
bugs: an alias that matches the wrong word, or a related-skill edge that gives
more credit than it should.
"""

from __future__ import annotations

import pytest

from app.core.taxonomy import (
    all_skills,
    canonical,
    extract_skills,
    normalise_skill_list,
    related_credit,
    skill,
    split_skill_list,
)


class TestCanonical:
    @pytest.mark.parametrize(
        "alias,expected",
        [
            ("React", "react"),
            ("react.js", "react"),
            ("ReactJS", "react"),
            ("REACT", "react"),
            ("PostgreSQL", "postgres"),
            ("postgres", "postgres"),
            ("Node.js", "nodejs"),
            ("node", "nodejs"),
            ("k8s", "kubernetes"),
            ("Golang", "go"),
            ("C++", "cpp"),
            ("C#", "csharp"),
            ("scikit-learn", "scikit"),
        ],
    )
    def test_aliases_resolve(self, alias: str, expected: str) -> None:
        assert canonical(alias) == expected

    def test_unknown_returns_none(self) -> None:
        assert canonical("solidity") is None
        assert canonical("") is None

    def test_whitespace_is_tolerated(self) -> None:
        assert canonical("  python  ") == "python"


class TestRelatedCredit:
    def test_exact_match_is_full_credit(self) -> None:
        assert related_credit("python", "python") == 1.0

    def test_related_skill_is_partial(self) -> None:
        credit = related_credit("vue", "react")
        assert 0.0 < credit < 1.0
        assert credit == pytest.approx(0.45)

    def test_related_graph_is_symmetric(self) -> None:
        """A one-way edge is almost always an oversight, so we treat it as
        symmetric. This test pins that decision."""
        assert related_credit("vue", "react") == related_credit("react", "vue")

    def test_unrelated_is_zero(self) -> None:
        assert related_credit("python", "figma") == 0.0

    def test_no_related_credit_exceeds_half(self) -> None:
        """Partial credit must never be full credit. If this fails, someone
        added an edge above 0.5 and the matcher is now lying about coverage."""
        for owned in all_skills():
            for wanted, factor in owned.related.items():
                assert factor <= 0.5, f"{owned.name} -> {wanted} is {factor}"


class TestExtractSkills:
    def test_finds_multiple_skills_in_prose(self) -> None:
        text = "I build services in Python with PostgreSQL and deploy on Docker."
        found = extract_skills(text)
        assert "python" in found
        assert "postgres" in found
        assert "docker" in found

    def test_returns_the_alias_that_matched(self) -> None:
        found = extract_skills("Experienced with ReactJS and Node.js")
        assert found["react"] == "reactjs"
        assert found["nodejs"] == "node.js"

    def test_does_not_match_inside_a_longer_word(self) -> None:
        """'Go' must not match 'Google', and 'R' must not match 'React'."""
        found = extract_skills("Worked at Google on React applications")
        assert "go" not in found
        assert "react" in found

    def test_cpp_matches_without_trailing_boundary(self) -> None:
        found = extract_skills("Strong C++ developer")
        assert "cpp" in found

    def test_ambiguous_aliases_skipped_in_strict_mode(self) -> None:
        """'ts' in prose is usually a timestamp, not TypeScript."""
        found = extract_skills("Updated at 12:00 ts 1699999", strict=True)
        assert "typescript" not in found

    def test_ambiguous_aliases_allowed_in_skill_list(self) -> None:
        found = extract_skills("ts", strict=False)
        assert "typescript" in found

    def test_empty_text_finds_nothing(self) -> None:
        assert extract_skills("") == {}


class TestSkillListHelpers:
    def test_split_handles_mixed_separators(self) -> None:
        parts = split_skill_list("Python, Docker; AWS | Redis • Git")
        assert parts == ["Python", "Docker", "AWS", "Redis", "Git"]

    def test_normalise_maps_aliases_and_keeps_unknowns(self) -> None:
        result = normalise_skill_list(["React.js", "Solidity", "k8s"])
        assert result == ["react", "solidity", "kubernetes"]

    def test_normalise_deduplicates(self) -> None:
        result = normalise_skill_list(["React", "react.js", "REACT"])
        assert result == ["react"]


class TestSkillLookup:
    def test_label_is_human_readable(self) -> None:
        found = skill("computer_vision")
        assert found is not None
        assert found.label == "Computer Vision"

    def test_unknown_skill_returns_none(self) -> None:
        assert skill("nonexistent_skill") is None

    def test_all_skills_is_sorted_and_non_empty(self) -> None:
        skills = all_skills()
        assert len(skills) > 50
        names = [s.name for s in skills]
        assert names == sorted(names)
