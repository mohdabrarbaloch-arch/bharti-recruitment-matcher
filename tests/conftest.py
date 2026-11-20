"""Shared test fixtures.

Each test gets a fresh in-memory SQLite database and a fresh app instance, so
tests cannot leak state into each other. The engine is created per-test rather
than per-session because SQLite in-memory databases are per-connection.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before app.config is imported anywhere.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bharti.db")
os.environ.setdefault("FIRST_USER_IS_ADMIN", "true")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.limiter import reset_limits
from app.main import app


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Reset the rate-limit counters before every test.

    The limiter is process-global by design, so without this the suite's own
    registrations trip the 10/minute auth limit and unrelated tests start
    failing with 429s. Test isolation is the test suite's problem, not the
    limiter's.
    """
    reset_limits()
    yield
    reset_limits()


@pytest.fixture()
def db_session():
    """A fresh in-memory database per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    """A TestClient wired to the per-test database."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client):
    """Register a user and return bearer headers."""
    response = client.post(
        "/api/auth/register",
        json={
            "email": "recruiter@example.com",
            "full_name": "Test Recruiter",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def sample_job(client, auth_headers):
    """A job with a realistic requirement set."""
    response = client.post(
        "/api/jobs",
        headers=auth_headers,
        json={
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "location": "Karachi",
            "remote_ok": False,
            "required_skills": ["python", "postgres", "docker"],
            "nice_skills": ["redis", "aws"],
            "min_years": 5,
            "seniority": "senior",
            "required_education": "bachelor",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


STRONG_RESUME = """Ayesha Khan
ayesha@example.com | +92 300 1234567 | Karachi

Experience
Senior Backend Engineer, Finca
Jan 2019 - Present
Built FastAPI services and owned the ledger.

Skills
Python, FastAPI, PostgreSQL, Docker, Redis, AWS, pytest, Git

Education
BSc Computer Science, NED University, 2018
"""

WEAK_RESUME = """Bilal Ahmed
bilal@example.com | Lahore

Experience
Frontend Developer, Naya Tech
Feb 2022 - Present
Vue.js and Nuxt.

Skills
Vue, JavaScript, CSS, Figma

Education
BS Computer Science, FAST, 2021
"""
