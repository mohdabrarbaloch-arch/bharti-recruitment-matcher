"""Candidate routes: add a resume, list, read, change status, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.parser import parse_resume
from app.database import get_db
from app.limiter import RateLimit
from app.models import Candidate, Job, User
from app.routers.jobs import _owned_job, _score_and_store
from app.schemas import CandidateCreate, CandidateOut, CandidateStatusUpdate
from app.security import get_current_user

router = APIRouter(prefix="/api/jobs/{job_id}/candidates", tags=["candidates"])
settings = get_settings()

_write_limit = RateLimit(times=120, seconds=60, scope="candidates-write")


def _owned_candidate(candidate_id: int, job: Job, db: Session) -> Candidate:
    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id, Candidate.job_id == job.id)
        .first()
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found"
        )
    return candidate


@router.post(
    "",
    response_model=CandidateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_write_limit)],
)
def add_candidate(
    job_id: int,
    payload: CandidateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CandidateOut:
    """Parse a resume and attach it to a job.

    The parser is the source of truth for skills and years. Anything the
    caller supplied explicitly (email, phone, location) wins over the parse,
    because a recruiter correcting a bad extraction should not have to fight
    the parser.
    """
    job = _owned_job(job_id, user, db)

    parsed = parse_resume(payload.resume_text)

    email = (payload.email or parsed.email or "").strip().lower() or None
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No email address found in the resume and none supplied. "
                "Add an email so the candidate can be de-duplicated."
            ),
        )

    full_name = (payload.full_name or "").strip()
    if not full_name:
        # Fall back to the email local-part, title-cased: "ali.khan@x.com"
        # becomes "Ali Khan". Ugly but never empty.
        local = email.split("@")[0]
        full_name = (
            " ".join(
                part.capitalize() for part in local.replace("_", ".").split(".") if part
            )
            or "Unnamed candidate"
        )

    candidate = Candidate(
        job_id=job.id,
        full_name=full_name[:160],
        email=email,
        phone=(payload.phone or parsed.phone),
        location=(payload.location or parsed.location),
        resume_text=payload.resume_text,
        skills=parsed.skills,
        skill_evidence=parsed.skill_evidence,
        titles=parsed.titles,
        education=parsed.education,
        years_experience=parsed.years_experience,
        seniority=parsed.seniority,
        parse_warnings=parsed.warnings,
    )
    db.add(candidate)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{email} is already in this job's pipeline",
        ) from None

    _score_and_store(job, candidate, db)
    db.commit()
    db.refresh(candidate)
    return CandidateOut.model_validate(candidate)


@router.get("", response_model=list[CandidateOut])
def list_candidates(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CandidateOut]:
    job = _owned_job(job_id, user, db)
    ordered = sorted(job.candidates, key=lambda c: c.created_at, reverse=True)
    return [CandidateOut.model_validate(c) for c in ordered]


@router.get("/{candidate_id}", response_model=CandidateOut)
def get_candidate(
    job_id: int,
    candidate_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CandidateOut:
    job = _owned_job(job_id, user, db)
    return CandidateOut.model_validate(_owned_candidate(candidate_id, job, db))


@router.patch("/{candidate_id}", response_model=CandidateOut)
def update_status(
    job_id: int,
    candidate_id: int,
    payload: CandidateStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CandidateOut:
    job = _owned_job(job_id, user, db)
    candidate = _owned_candidate(candidate_id, job, db)
    candidate.status = payload.status
    db.commit()
    db.refresh(candidate)
    return CandidateOut.model_validate(candidate)


@router.delete(
    "/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def delete_candidate(
    job_id: int,
    candidate_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    job = _owned_job(job_id, user, db)
    candidate = _owned_candidate(candidate_id, job, db)
    db.delete(candidate)
    db.commit()
