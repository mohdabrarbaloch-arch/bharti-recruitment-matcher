"""Pydantic schemas: request validation and response shapes.

Every numeric and string field has a bound. An unbounded ``years`` field is
how you get a candidate with 10,000 years of experience and a leaderboard that
means nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.taxonomy import normalise_skill_list

Seniority = Literal["intern", "junior", "mid", "senior", "lead", "principal"]
CandidateStatus = Literal["new", "shortlisted", "rejected", "hired"]


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    #: bcrypt truncates at 72 bytes, so anything longer is rejected here
    #: rather than silently losing the tail of the password.
    password: str = Field(min_length=8, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


class JobCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    company: str = Field(default="", max_length=160)
    location: str | None = Field(default=None, max_length=120)
    remote_ok: bool = False
    description: str = Field(default="", max_length=20_000)
    required_skills: list[str] = Field(default_factory=list, max_length=40)
    nice_skills: list[str] = Field(default_factory=list, max_length=40)
    min_years: float = Field(default=0.0, ge=0, le=50)
    seniority: Seniority = "mid"
    required_education: str | None = Field(default=None, max_length=80)

    @field_validator("required_skills", "nice_skills")
    @classmethod
    def _normalise(cls, value: list[str]) -> list[str]:
        cleaned = [s.strip() for s in value if s and s.strip()]
        return normalise_skill_list(cleaned)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    company: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=120)
    remote_ok: bool | None = None
    description: str | None = Field(default=None, max_length=20_000)
    required_skills: list[str] | None = Field(default=None, max_length=40)
    nice_skills: list[str] | None = Field(default=None, max_length=40)
    min_years: float | None = Field(default=None, ge=0, le=50)
    seniority: Seniority | None = None
    required_education: str | None = Field(default=None, max_length=80)
    is_open: bool | None = None

    @field_validator("required_skills", "nice_skills")
    @classmethod
    def _normalise(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalise_skill_list([s.strip() for s in value if s and s.strip()])


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    company: str
    location: str | None
    remote_ok: bool
    description: str
    required_skills: list[str]
    nice_skills: list[str]
    min_years: float
    seniority: str
    required_education: str | None
    is_open: bool
    created_at: datetime
    candidate_count: int = 0


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------


class CandidateCreate(BaseModel):
    """Add a candidate by pasting resume text.

    ``full_name`` is optional: if it is missing we fall back to the email
    local-part, because a recruiter pasting a resume should not be blocked by
    a form field the resume already answers.
    """

    full_name: str | None = Field(default=None, max_length=160)
    resume_text: str = Field(min_length=20, max_length=60_000)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=120)


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    full_name: str
    email: str | None
    phone: str | None
    location: str | None
    skills: list[str]
    skill_evidence: dict
    titles: list[str]
    education: list[str]
    years_experience: float
    seniority: str
    parse_warnings: list[str]
    status: str
    created_at: datetime


class CandidateStatusUpdate(BaseModel):
    status: CandidateStatus


class RankedCandidate(BaseModel):
    """A candidate plus their score. This is what the dashboard renders."""

    candidate: CandidateOut
    match: dict


# --------------------------------------------------------------------------
# Admin / meta
# --------------------------------------------------------------------------


class SkillOut(BaseModel):
    name: str
    label: str
    category: str
    aliases: list[str]


class PlatformStats(BaseModel):
    users: int
    jobs: int
    candidates: int
    matches: int
    average_score: float
    shortlisted: int
