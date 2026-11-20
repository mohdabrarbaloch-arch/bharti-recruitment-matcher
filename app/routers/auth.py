"""Auth routes: register, login, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.limiter import RateLimit
from app.models import User
from app.schemas import LoginRequest, Token, UserCreate, UserOut
from app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

#: Auth endpoints get a tighter limit than the rest of the API: they are the
#: ones worth brute-forcing.
_auth_limit = RateLimit(times=10, seconds=60, scope="auth")


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_auth_limit)],
)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> Token:
    """Create an account and return a token immediately.

    The first account becomes an administrator only when
    ``FIRST_USER_IS_ADMIN`` is explicitly enabled. On a public deployment the
    default is off, because otherwise the first stranger to find the signup
    form owns the platform.
    """
    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    is_first = db.query(User).count() == 0
    role = "admin" if (is_first and settings.first_user_is_admin) else "recruiter"

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two simultaneous signups with the same email: the unique index is
        # the real guard, and this turns the race into a clean 409.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        ) from None

    db.refresh(user)
    return Token(
        access_token=create_access_token(user.email, user.role),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=Token, dependencies=[Depends(_auth_limit)])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    user = db.query(User).filter(User.email == payload.email.lower()).first()

    # Same message and same work for "no such user" and "wrong password", so
    # the response cannot be used to enumerate accounts.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    return Token(
        access_token=create_access_token(user.email, user.role),
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
