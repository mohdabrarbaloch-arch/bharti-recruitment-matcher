"""Job routes: create, list, read, update, delete, and the ranked shortlist."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.matcher import match_candidate
from app.database import get_db
from app.limiter import RateLimit
from app.models import Candidate, Job, Match, User
from app.schemas import (
    CandidateOut,
    JobCreate,
    JobOut,
    JobUpdate,
    RankedCandidate,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
settings = get_settings()

_write_limit = RateLimit(times=120, seconds=60, scope="jobs-write")


def _owned_job(job_id: int, user: User, db: Session) -> Job:
    """Fetch a job the caller owns.

    Returns 404 rather than 403 for someone else's job: a 403 confirms the job
    exists, which leaks the shape of another tenant's pipeline.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None or (job.owner_id != user.id and user.role != "admin"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    return job


def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.candidate_count = len(job.candidates)
    return out


@router.post(
    "",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_write_limit)],
)
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    job = Job(owner_id=user.id, **payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    return _to_out(job)


@router.get("", response_model=list[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    open_only: bool = Query(default=False),
) -> list[JobOut]:
    query = db.query(Job)
    if user.role != "admin":
        query = query.filter(Job.owner_id == user.id)
    if open_only:
        query = query.filter(Job.is_open.is_(True))
    jobs = query.order_by(Job.created_at.desc()).all()
    return [_to_out(j) for j in jobs]


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    return _to_out(_owned_job(job_id, user, db))


@router.patch("/{job_id}", response_model=JobOut)
def update_job(
    job_id: int,
    payload: JobUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    job = _owned_job(job_id, user, db)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)

    # Requirements changed, so every stored score is now stale. Recompute
    # rather than leaving a leaderboard that describes a job that no longer
    # exists.
    if any(
        k in changes
        for k in (
            "required_skills",
            "nice_skills",
            "min_years",
            "seniority",
            "location",
            "remote_ok",
            "required_education",
        )
    ):
        _rescore_job(job, db)

    return _to_out(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    job = _owned_job(job_id, user, db)
    db.delete(job)
    db.commit()


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def _rescore_job(job: Job, db: Session) -> None:
    """Recompute every candidate's score for this job."""
    for candidate in job.candidates:
        _score_and_store(job, candidate, db)
    db.commit()


def _score_and_store(job: Job, candidate: Candidate, db: Session) -> Match:
    """Score one candidate and upsert the Match row."""
    result = match_candidate(
        candidate_skills=candidate.skills or [],
        candidate_years=candidate.years_experience,
        candidate_seniority=candidate.seniority,
        candidate_location=candidate.location,
        candidate_education=candidate.education or [],
        required_skills=job.required_skills or [],
        nice_skills=job.nice_skills or [],
        required_years=job.min_years,
        required_seniority=job.seniority,
        job_location=job.location,
        remote_ok=job.remote_ok,
        required_education=job.required_education,
        warnings=candidate.parse_warnings or [],
    )

    match = candidate.match
    if match is None:
        match = Match(candidate_id=candidate.id, job_id=job.id)
        db.add(match)

    match.total = result.total
    match.verdict = result.verdict
    match.confidence = result.confidence
    match.breakdown = result.to_dict()
    return match


@router.get("/{job_id}/ranked", response_model=list[RankedCandidate])
def ranked_candidates(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    min_score: float = Query(default=0.0, ge=0, le=100),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RankedCandidate]:
    """Candidates ordered by score, each with the full breakdown.

    Scores are recomputed on read rather than trusted from the table. The
    stored breakdown is what the recruiter saw when they shortlisted someone;
    this endpoint is what they see now, and the two are allowed to differ.
    """
    job = _owned_job(job_id, user, db)

    rows: list[RankedCandidate] = []
    for candidate in job.candidates:
        match = _score_and_store(job, candidate, db)
        if match.total < min_score:
            continue
        rows.append(
            RankedCandidate(
                candidate=CandidateOut.model_validate(candidate),
                match=match.breakdown,
            )
        )
    db.commit()

    rows.sort(key=lambda r: r.match["total"], reverse=True)
    return rows[:limit]
