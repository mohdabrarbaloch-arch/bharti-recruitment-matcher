"""Tests for the resume parser.

The date arithmetic is where this module earns its keep, so most of these
tests are about months rather than about regexes.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.parser import (
    extract_experience_months,
    parse_resume,
)

TODAY = date(2026, 11, 20)


class TestExperienceMonths:
    def test_simple_range(self) -> None:
        months, count = extract_experience_months("Jan 2020 - Jan 2021", today=TODAY)
        assert months == 12
        assert count == 1

    def test_present_uses_today(self) -> None:
        months, _ = extract_experience_months("Jan 2025 - Present", today=TODAY)
        # Jan 2025 to Nov 2026 inclusive of the month boundary = 22 months
        assert months == 22

    def test_numeric_month_format(self) -> None:
        months, _ = extract_experience_months("03/2018 - 07/2019", today=TODAY)
        assert months == 16

    def test_iso_style_format(self) -> None:
        months, _ = extract_experience_months("2018-03 - 2019-07", today=TODAY)
        assert months == 16

    def test_bare_years_are_conservative(self) -> None:
        """A bare year is treated as January, which under-counts rather than
        over-counts. Under-counting is the safe direction."""
        months, _ = extract_experience_months("2019 - 2021", today=TODAY)
        assert months == 24

    def test_overlapping_roles_count_once(self) -> None:
        """Two concurrent jobs for a year is one year of experience, not two.
        This is the bug that makes a 3-year candidate look like a 6-year one."""
        text = """
        Developer, Company A
        Jan 2020 - Jan 2022
        Developer, Company B
        Jan 2021 - Jan 2022
        """
        months, count = extract_experience_months(text, today=TODAY)
        assert count == 2
        assert months == 24  # not 36

    def test_adjacent_roles_do_not_double_count_the_boundary(self) -> None:
        """Jan 2019-Dec 2020 is 23 months and Jan 2021-Dec 2022 is 23, so the
        total is 46. Counting both endpoints inclusively would give 48 and
        quietly inflate every candidate by a month per role."""
        text = """
        Engineer, A
        Jan 2019 - Dec 2020
        Engineer, B
        Jan 2021 - Dec 2022
        """
        months, _ = extract_experience_months(text, today=TODAY)
        assert months == 46

    def test_reversed_range_is_dropped(self) -> None:
        """A typo that ends before it starts must not produce negative time."""
        months, _ = extract_experience_months("Jan 2022 - Jan 2020", today=TODAY)
        assert months == 0

    def test_future_start_is_ignored(self) -> None:
        months, _ = extract_experience_months("Jan 2030 - Present", today=TODAY)
        assert months == 0

    def test_no_dates_returns_zero(self) -> None:
        months, count = extract_experience_months("I am a developer.", today=TODAY)
        assert months == 0
        assert count == 0


class TestContactExtraction:
    def test_finds_email(self) -> None:
        parsed = parse_resume("Ali Khan\nali.khan@example.com\nKarachi", today=TODAY)
        assert parsed.email == "ali.khan@example.com"

    def test_email_is_lowercased(self) -> None:
        parsed = parse_resume("Ali@Example.COM", today=TODAY)
        assert parsed.email == "ali@example.com"

    def test_finds_pakistani_mobile(self) -> None:
        parsed = parse_resume("Ali Khan\n+92 300 1234567", today=TODAY)
        assert parsed.phone is not None
        assert parsed.phone.endswith("3001234567")

    def test_does_not_treat_a_year_as_a_phone(self) -> None:
        parsed = parse_resume("Graduated 2018 from NED", today=TODAY)
        assert parsed.phone is None

    def test_finds_city(self) -> None:
        parsed = parse_resume("Ali Khan\nKarachi, Pakistan", today=TODAY)
        assert parsed.location == "Karachi"

    def test_missing_email_produces_a_warning(self) -> None:
        parsed = parse_resume("Ali Khan\nPython developer", today=TODAY)
        assert parsed.email is None
        assert any("email" in w for w in parsed.warnings)


class TestSkillsAndSeniority:
    def test_skills_section_is_parsed(self) -> None:
        text = """Ali Khan
ali@example.com

Skills
Python, Docker, PostgreSQL
"""
        parsed = parse_resume(text, today=TODAY)
        assert "python" in parsed.skills
        assert "docker" in parsed.skills
        assert "postgres" in parsed.skills

    def test_short_aliases_work_inside_skills_section(self) -> None:
        """'js' and 'ts' are ambiguous in prose but unambiguous in a list."""
        text = """Ali Khan
ali@example.com

Skills
js, ts, react
"""
        parsed = parse_resume(text, today=TODAY)
        assert "javascript" in parsed.skills
        assert "typescript" in parsed.skills

    def test_skill_evidence_records_the_alias(self) -> None:
        text = "Ali Khan\nali@example.com\n\nSkills\nReactJS, k8s"
        parsed = parse_resume(text, today=TODAY)
        assert parsed.skill_evidence["react"] == "reactjs"
        assert parsed.skill_evidence["kubernetes"] == "k8s"

    def test_explicit_senior_word_wins_over_years(self) -> None:
        text = """Ali Khan
ali@example.com

Senior Engineer
Jan 2024 - Present
"""
        parsed = parse_resume(text, today=TODAY)
        assert parsed.seniority == "senior"
        assert "senior" in parsed.seniority_reason.lower()

    def test_years_used_when_no_level_word(self) -> None:
        text = """Ali Khan
ali@example.com

Engineer
Jan 2014 - Present
"""
        parsed = parse_resume(text, today=TODAY)
        assert parsed.seniority in ("senior", "principal")
        assert "no explicit level" in parsed.seniority_reason

    def test_empty_resume_is_handled(self) -> None:
        parsed = parse_resume("", today=TODAY)
        assert parsed.skills == []
        assert parsed.warnings

    def test_education_is_found(self) -> None:
        text = "Ali Khan\nali@example.com\nBSc Computer Science, NED University, 2018"
        parsed = parse_resume(text, today=TODAY)
        assert any("BSc" in e for e in parsed.education)


class TestRealisticResume:
    def test_full_resume_parses_sensibly(self) -> None:
        text = """Ayesha Khan
ayesha.khan@example.com | +92 300 1234567 | Karachi

Experience
Senior Backend Engineer, Finca Microfinance
Jan 2021 - Present
Led the migration to FastAPI services.

Backend Engineer, Systems Ltd
Mar 2019 - Dec 2020
Built REST APIs in Django.

Skills
Python, FastAPI, Django, PostgreSQL, Redis, Docker, AWS, pytest, Git

Education
BSc Computer Science, NED University, 2018
"""
        parsed = parse_resume(text, today=TODAY)

        assert parsed.email == "ayesha.khan@example.com"
        assert parsed.location == "Karachi"
        assert parsed.seniority == "senior"
        # Jan 2021 -> Nov 2026 is 70 months; Mar 2019 -> Dec 2020 is 21.
        # They do not overlap, so the total is 91 months = 7.6 years.
        assert parsed.years_experience == pytest.approx(7.6, abs=0.1)
        for expected in ("python", "fastapi", "django", "postgres", "docker", "aws"):
            assert expected in parsed.skills
