"""SQLAlchemy models.

Two things worth noting about the schema:

* Skills are stored as JSON arrays rather than a join table. The matching
  engine works on whole lists and never queries "who has React" across the
  table, so a join table would add complexity for a query nobody runs. If
  skill-level search becomes a requirement, that is the moment to normalise.

* ``Match`` stores the full score breakdown as JSON. Recomputing a score later
  would give a different answer once the weights change, and a recruiter who
  shortlisted someone on Tuesday deserves to see the reasoning they saw on
  Tuesday, not today's.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="recruiter", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    jobs: Mapped[list[Job]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    company: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    remote_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    required_skills: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    nice_skills: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    min_years: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    seniority: Mapped[str] = mapped_column(String(20), default="mid", nullable=False)
    required_education: Mapped[str | None] = mapped_column(String(80), nullable=True)

    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    owner: Mapped[User] = relationship(back_populates="jobs")
    candidates: Mapped[list[Candidate]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("job_id", "email", name="uq_candidate_job_email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )

    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)

    resume_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    skills: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    skill_evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    titles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    education: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    years_experience: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    seniority: Mapped[str] = mapped_column(String(20), default="mid", nullable=False)
    parse_warnings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    job: Mapped[Job] = relationship(back_populates="candidates")
    match: Mapped[Match | None] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", uselist=False
    )


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), unique=True, index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )

    total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[str] = mapped_column(
        String(10), default="medium", nullable=False
    )
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    candidate: Mapped[Candidate] = relationship(back_populates="match")
