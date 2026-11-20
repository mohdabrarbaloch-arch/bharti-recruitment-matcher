"""Resume parser.

Turns a block of resume text into structured facts: contact details, total
years of experience, skills, job titles, education, and a seniority guess.

The hard part is not the regexes, it is the date arithmetic. "2019 - 2022" and
"Jan 2020 - Present" and "03/2018 - 07/2019" all have to become months, and
overlapping roles must not be double counted. A candidate who held two jobs at
once for a year has one year of experience, not two.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.core.taxonomy import extract_skills, split_skill_list

# --------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------

SENIORITY_ORDER = ["intern", "junior", "mid", "senior", "lead", "principal"]


@dataclass
class ParsedResume:
    """Everything we could pull out of a resume, plus the evidence for it."""

    email: str | None = None
    phone: str | None = None
    location: str | None = None
    years_experience: float = 0.0
    skills: list[str] = field(default_factory=list)
    skill_evidence: dict[str, str] = field(default_factory=dict)
    titles: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    seniority: str = "mid"
    seniority_reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "years_experience": round(self.years_experience, 1),
            "skills": self.skills,
            "skill_evidence": self.skill_evidence,
            "titles": self.titles,
            "education": self.education,
            "seniority": self.seniority,
            "seniority_reason": self.seniority_reason,
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------
# Contact details
# --------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

#: Deliberately loose on separators, strict on digit count. Pakistani mobile
#: numbers are 10 digits after the country code (3xx xxxxxxx), so we accept
#: 10-15 digits total and let the caller decide whether to trust it.
_PHONE_RE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?){2,5}\d{2,4}"
)

_CITY_HINTS = (
    "karachi",
    "lahore",
    "islamabad",
    "rawalpindi",
    "faisalabad",
    "multan",
    "peshawar",
    "quetta",
    "hyderabad",
    "sialkot",
    "gujranwala",
    "london",
    "dubai",
    "berlin",
    "toronto",
    "new york",
    "san francisco",
    "bangalore",
    "remote",
)


def _find_email(text: str) -> str | None:
    match = _EMAIL_RE.search(text)
    return match.group(0).lower() if match else None


def _find_phone(text: str) -> str | None:
    """First plausible phone number, normalised to digits and a leading +."""
    for match in _PHONE_RE.finditer(text):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        # Reject things that are obviously dates or years, and anything too
        # short to be a real number.
        if len(digits) < 10 or len(digits) > 15:
            continue
        if re.fullmatch(r"(19|20)\d{2}", digits):
            continue
        return ("+" if raw.strip().startswith(("+", "00")) else "") + digits
    return None


def _find_location(text: str) -> str | None:
    lowered = text.lower()
    for city in _CITY_HINTS:
        if re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", lowered):
            return city.title()
    return None


# --------------------------------------------------------------------------
# Date ranges -> months of experience
# --------------------------------------------------------------------------

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_PRESENT_WORDS = ("present", "current", "now", "today", "ongoing")

#: One side of a date range. Matches "Jan 2020", "January 2020", "2020",
#: "03/2018", "2018-03". The month is optional.
_DATE_TOKEN = (
    r"(?:"
    r"(?P<mon1>[A-Za-z]{3,9})\.?\s+(?P<yr1>(?:19|20)\d{2})"
    r"|(?P<num1>\d{1,2})/(?P<yr2>(?:19|20)\d{2})"
    r"|(?P<yr3>(?:19|20)\d{2})-(?P<num2>\d{1,2})"
    r"|(?P<yr4>(?:19|20)\d{2})"
    r")"
)

_RANGE_RE = re.compile(
    _DATE_TOKEN
    + r"\s*(?:-|–|—|to|until|through)\s*"
    + r"(?P<end>present|current|now|today|ongoing|"
    + _DATE_TOKEN.replace("?P<", "?P<e_")
    + r")",
    re.IGNORECASE,
)


def _token_to_month(match: re.Match[str], prefix: str = "") -> tuple[int, int] | None:
    """Read one date token out of a match into (year, month)."""
    mon = match.group(f"{prefix}mon1")
    yr = match.group(f"{prefix}yr1")
    if mon and yr:
        month = _MONTHS.get(mon.lower()[:9])
        if month is None:
            return None
        return int(yr), month

    num = match.group(f"{prefix}num1")
    yr = match.group(f"{prefix}yr2")
    if num and yr:
        month = int(num)
        if 1 <= month <= 12:
            return int(yr), month
        return None

    yr = match.group(f"{prefix}yr3")
    num = match.group(f"{prefix}num2")
    if yr and num:
        month = int(num)
        if 1 <= month <= 12:
            return int(yr), month
        return None

    yr = match.group(f"{prefix}yr4")
    if yr:
        # A bare year is treated as January: the conservative choice, since
        # it under-counts rather than over-counts experience.
        return int(yr), 1

    return None


def _months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return (end[0] - start[0]) * 12 + (end[1] - start[1])


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping month-index intervals so concurrent roles count once."""
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def extract_experience_months(text: str, today: date | None = None) -> tuple[int, int]:
    """Total months of experience, and how many date ranges were found.

    Overlapping ranges are merged, so two concurrent part-time roles do not
    add up to double the time. Ranges that end before they start are dropped
    as typos rather than allowed to produce negative experience.
    """
    today = today or date.today()
    now_index = _month_index(today.year, today.month)

    intervals: list[tuple[int, int]] = []
    for match in _RANGE_RE.finditer(text):
        start = _token_to_month(match)
        if start is None:
            continue

        end_raw = match.group("end")
        if end_raw and end_raw.lower() in _PRESENT_WORDS:
            end = (today.year, today.month)
        else:
            end = _token_to_month(match, prefix="e_")
            if end is None:
                continue

        start_i = _month_index(*start)
        end_i = _month_index(*end)

        if end_i < start_i:
            continue
        # A range that starts in the future is not experience yet.
        if start_i > now_index:
            continue
        end_i = min(end_i, now_index)

        intervals.append((start_i, end_i))

    merged = _merge_intervals(intervals)
    total = sum(end - start for start, end in merged)
    return total, len(intervals)


# --------------------------------------------------------------------------
# Titles, education, seniority
# --------------------------------------------------------------------------

_TITLE_WORDS = (
    "engineer",
    "developer",
    "designer",
    "manager",
    "analyst",
    "scientist",
    "architect",
    "consultant",
    "specialist",
    "lead",
    "director",
    "intern",
    "administrator",
    "strategist",
    "researcher",
    "programmer",
    "officer",
    "head of",
    "vp of",
    "founder",
    "co-founder",
)

_TITLE_RE = re.compile(
    r"^[ \t]*([A-Z][A-Za-z/&+.\- ]{2,60}?(?:" + "|".join(_TITLE_WORDS) + r"))[ \t]*$",
    re.MULTILINE,
)

_EDU_RE = re.compile(
    r"\b(bachelor|bachelors|b\.?s\.?c?|b\.?e\.?|b\.?tech|master|masters|m\.?s\.?c?|"
    r"mba|ph\.?d|doctorate|diploma|intermediate|matric|fsc|hsc|bcs|msc)\b",
    re.IGNORECASE,
)

_SENIORITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "principal",
        re.compile(r"\b(principal|distinguished|staff engineer|architect)\b", re.I),
    ),
    ("lead", re.compile(r"\b(lead|head of|director|vp of|manager|team lead)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?|snr)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr\.?|associate|entry level|graduate)\b", re.I)),
    ("intern", re.compile(r"\b(intern|internship|trainee)\b", re.I)),
]


def _find_titles(text: str) -> list[str]:
    titles: list[str] = []
    for match in _TITLE_RE.finditer(text):
        title = re.sub(r"\s+", " ", match.group(1)).strip(" -–—")
        if 3 <= len(title) <= 60 and title.lower() not in (t.lower() for t in titles):
            titles.append(title)
    return titles[:8]


def _find_education(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        if _EDU_RE.search(line):
            cleaned = re.sub(r"\s+", " ", line).strip(" -–—•·")
            if 3 <= len(cleaned) <= 120 and cleaned not in found:
                found.append(cleaned)
    return found[:5]


def _guess_seniority(text: str, years: float) -> tuple[str, str]:
    """Seniority from explicit words first, then from years as a fallback.

    Words win because a resume that says "Senior Engineer" is telling you
    something the year count cannot. The year fallback only fires when the
    text is silent, and it says so in the reason string.
    """
    for level, pattern in _SENIORITY_PATTERNS:
        match = pattern.search(text)
        if match:
            return level, f"resume says '{match.group(0).strip()}'"

    if years >= 10:
        return "principal", f"{years:.0f} years of experience, no explicit level"
    if years >= 6:
        return "senior", f"{years:.0f} years of experience, no explicit level"
    if years >= 2:
        return "mid", f"{years:.0f} years of experience, no explicit level"
    if years > 0:
        return "junior", f"{years:.0f} years of experience, no explicit level"
    return "mid", "no dates or level found; defaulted to mid"


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------

_SKILLS_HEADER_RE = re.compile(
    r"^[ \t]*(?:technical\s+)?(?:skills|technologies|tech\s+stack|toolkit|"
    r"competencies|expertise)[ \t]*:?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def _skills_section(text: str) -> str:
    """The block under a "Skills" header, if there is one.

    Bounded by the next blank-line-separated header-looking line, so we do not
    swallow the whole rest of the resume.
    """
    match = _SKILLS_HEADER_RE.search(text)
    if not match:
        return ""
    rest = text[match.end() :]
    lines: list[str] = []
    for line in rest.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        # A short line with no separators and no lowercase words is probably
        # the next section header.
        if (
            len(stripped) < 40
            and not re.search(r"[,;|/•·]", stripped)
            and (stripped.isupper() or stripped.istitle())
        ):
            break
        lines.append(stripped)
    return "\n".join(lines)


def parse_resume(text: str, today: date | None = None) -> ParsedResume:
    """Parse resume text into structured facts."""
    result = ParsedResume()
    if not text or not text.strip():
        result.warnings.append("resume text was empty")
        return result

    result.email = _find_email(text)
    result.phone = _find_phone(text)
    result.location = _find_location(text)

    months, range_count = extract_experience_months(text, today=today)
    result.years_experience = months / 12.0
    if range_count == 0:
        result.warnings.append(
            "no date ranges found, so years of experience is 0 — "
            "add 'Jan 2020 - Present' style dates to get a real figure"
        )

    # Skills: scan the whole document strictly, then scan the skills section
    # non-strictly so short aliases like "js" and "ts" are picked up where
    # the context makes them unambiguous.
    evidence = extract_skills(text, strict=True)
    section = _skills_section(text)
    if section:
        for token in split_skill_list(section):
            for canonical_name, alias in extract_skills(token, strict=False).items():
                evidence.setdefault(canonical_name, alias)

    result.skill_evidence = evidence
    result.skills = sorted(evidence)

    result.titles = _find_titles(text)
    result.education = _find_education(text)
    result.seniority, result.seniority_reason = _guess_seniority(
        text, result.years_experience
    )

    if not result.email:
        result.warnings.append("no email address found")
    if not result.skills:
        result.warnings.append("no recognisable skills found")

    return result
