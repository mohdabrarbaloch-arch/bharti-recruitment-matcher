"""Seed a demo account, two roles, and a handful of realistic resumes.

Run with: python -m scripts.seed

The resumes are written to exercise the parser's awkward cases on purpose:
one has overlapping roles, one has no dates at all, one uses "React.js" and
"reactjs" interchangeably, and one is a strong match with a single gap.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.parser import parse_resume
from app.database import SessionLocal, init_db
from app.models import Candidate, Job, User
from app.routers.jobs import _score_and_store
from app.security import hash_password

DEMO_EMAIL = "abraz@example.com"
DEMO_PASSWORD = "bharti-demo-2026"

RESUMES: list[dict] = [
    {
        "name": "Ayesha Khan",
        "text": """Ayesha Khan
ayesha.khan@example.com | +92 300 1234567 | Karachi

Summary
Backend engineer with six years building payment systems.

Experience
Senior Backend Engineer, Finca Microfinance
Jan 2021 - Present
Led the migration from a monolith to FastAPI services. Owned the ledger.

Backend Engineer, Systems Ltd
Mar 2019 - Dec 2020
Built REST APIs in Django. Introduced pytest across the team.

Junior Developer, Systems Ltd
Jun 2018 - Feb 2019
Maintained internal tooling.

Skills
Python, FastAPI, Django, PostgreSQL, Redis, Docker, AWS, pytest, Git

Education
BSc Computer Science, NED University, 2018
""",
    },
    {
        "name": "Bilal Ahmed",
        "text": """Bilal Ahmed
bilal.ahmed@example.com | Lahore

Experience
Full Stack Developer, Naya Tech
Feb 2020 - Present
React.js frontend, Node.js backend, MongoDB.

Freelance Developer
Jan 2020 - Present
Small client projects alongside the day job.

Skills
JavaScript, TypeScript, React, Node.js, MongoDB, Express, Git, Figma

Education
BS Software Engineering, FAST NUCES, 2019
""",
    },
    {
        "name": "Sana Iqbal",
        "text": """Sana Iqbal
sana.iqbal@example.com | Islamabad

Experience
Data Engineer, Analytics Co
Aug 2021 - Present
Airflow pipelines, Spark jobs, warehouse modelling.

Analyst, Bank Alfalah
Jul 2019 - Jul 2021
SQL reporting and dashboards.

Skills
Python, SQL, Airflow, Spark, PostgreSQL, pandas, Docker, Git

Education
MSc Data Science, LUMS, 2019
""",
    },
    {
        "name": "Hamza Sheikh",
        "text": """Hamza Sheikh
hamza.sheikh@example.com

Experience
Software Engineer at a startup. Worked on various projects.

Skills
Python, Flask, MySQL, Git

Education
Bachelor of Computer Science
""",
    },
    {
        "name": "Zara Malik",
        "text": """Zara Malik
zara.malik@example.com | Karachi | +92 321 9876543

Experience
Principal Engineer, Careem
Mar 2017 - Present
Owned the dispatch platform. Kubernetes, Go, gRPC at scale.

Senior Engineer, Careem
Jan 2014 - Feb 2017
Built the pricing service in Java.

Engineer, Netsol
Aug 2011 - Dec 2013
Enterprise integrations.

Skills
Go, Java, Kubernetes, Docker, gRPC, PostgreSQL, Redis, AWS, Terraform,
Prometheus, Grafana, CI/CD, mentoring, code review

Education
BSc Computer Science, IBA Karachi, 2011
""",
    },
    {
        "name": "Usman Tariq",
        "text": """Usman Tariq
usman.tariq@example.com | Remote

Experience
Frontend Developer, Bazaar
Apr 2022 - Present
Vue.js and Nuxt. Design system work with Figma.

Skills
Vue, Nuxt, JavaScript, CSS, Tailwind, Figma, Git

Education
BS Computer Science, UET Lahore, 2022
""",
    },
]

JOBS: list[dict] = [
    {
        "title": "Senior Backend Engineer",
        "company": "Finca",
        "location": "Karachi",
        "remote_ok": False,
        "description": (
            "Own the payments ledger. Python services, Postgres, on-call rotation."
        ),
        "required_skills": ["python", "postgres", "docker", "rest"],
        "nice_skills": ["fastapi", "redis", "aws"],
        "min_years": 5,
        "seniority": "senior",
        "required_education": "bachelor",
    },
    {
        "title": "Frontend Engineer",
        "company": "Bazaar",
        "location": "Karachi",
        "remote_ok": True,
        "description": "Build the storefront. React, TypeScript, design systems.",
        "required_skills": ["react", "typescript", "css"],
        "nice_skills": ["nextjs", "figma", "testing"],
        "min_years": 3,
        "seniority": "mid",
        "required_education": None,
    },
]


def main() -> None:
    init_db()
    db = SessionLocal()

    try:
        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                full_name="ABraz Baloch",
                hashed_password=hash_password(DEMO_PASSWORD),
                role="admin",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"created demo user {DEMO_EMAIL}")
        else:
            print(f"demo user {DEMO_EMAIL} already exists")

        for spec in JOBS:
            existing = (
                db.query(Job)
                .filter(Job.owner_id == user.id, Job.title == spec["title"])
                .first()
            )
            if existing:
                print(f"job '{spec['title']}' already exists, skipping")
                continue

            job = Job(owner_id=user.id, **spec)
            db.add(job)
            db.commit()
            db.refresh(job)
            print(f"created job '{job.title}'")

            for resume in RESUMES:
                parsed = parse_resume(resume["text"])
                email = (
                    parsed.email
                    or f"{resume['name'].lower().replace(' ', '.')}@example.com"
                )

                candidate = Candidate(
                    job_id=job.id,
                    full_name=resume["name"],
                    email=email,
                    phone=parsed.phone,
                    location=parsed.location,
                    resume_text=resume["text"],
                    skills=parsed.skills,
                    skill_evidence=parsed.skill_evidence,
                    titles=parsed.titles,
                    education=parsed.education,
                    years_experience=parsed.years_experience,
                    seniority=parsed.seniority,
                    parse_warnings=parsed.warnings,
                )
                db.add(candidate)
                db.flush()
                match = _score_and_store(job, candidate, db)
                print(
                    f"  {resume['name']:<16} {match.total:5.1f}  "
                    f"{len(parsed.skills):2d} skills  "
                    f"{parsed.years_experience:4.1f} yrs"
                )

            db.commit()

        print("\nDone. Sign in with:")
        print(f"  email:    {DEMO_EMAIL}")
        print(f"  password: {DEMO_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
