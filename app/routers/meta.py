"""Meta routes: skill taxonomy for autocomplete, and admin platform stats."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.taxonomy import all_skills
from app.database import get_db
from app.models import Candidate, Job, Match, User
from app.schemas import PlatformStats, SkillOut
from app.security import get_current_user, require_admin

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/skills", response_model=list[SkillOut])
def list_skills(
    q: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=200, ge=1, le=500),
    _user: User = Depends(get_current_user),
) -> list[SkillOut]:
    """The taxonomy, optionally filtered. Powers the skill autocomplete."""
    skills = all_skills()
    if q:
        needle = q.strip().lower()
        skills = [
            s for s in skills if needle in s.name or any(needle in a for a in s.aliases)
        ]
    return [
        SkillOut(
            name=s.name,
            label=s.label,
            category=s.category,
            aliases=list(s.aliases),
        )
        for s in skills[:limit]
    ]


@router.get("/admin/stats", response_model=PlatformStats)
def platform_stats(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> PlatformStats:
    """Platform-wide numbers. Administrator only — a recruiter has no business
    reading another tenant's pipeline volume."""
    avg = db.query(func.avg(Match.total)).scalar() or 0.0
    return PlatformStats(
        users=db.query(User).count(),
        jobs=db.query(Job).count(),
        candidates=db.query(Candidate).count(),
        matches=db.query(Match).count(),
        average_score=round(float(avg), 1),
        shortlisted=db.query(Candidate)
        .filter(Candidate.status == "shortlisted")
        .count(),
    )
