# Architecture

## What this is

Bharti scores candidates against a job and explains every number it produces. The design goal is not accuracy — it is **falsifiability**. A recruiter must be able to read a score, disagree with a specific part of it, and know which assumption to argue with.

That goal drives almost every decision below.

---

## System diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser — static/index.html + app.js + style.css                    │
│  No framework, no build step. State in one object, render is pure.   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ fetch, Bearer token
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI (app/main.py)                                               │
│  ├─ security headers middleware (CSP, nosniff, frame-deny, HSTS)     │
│  ├─ CORS allow-list from env                                         │
│  └─ routers/                                                         │
│     ├─ auth.py        register · login · me                          │
│     ├─ jobs.py        CRUD + /ranked                                 │
│     ├─ candidates.py  add resume · status · delete                   │
│     └─ meta.py        skill taxonomy · admin stats                   │
└───────────────┬──────────────────────────────┬───────────────────────┘
                │                              │
                ▼                              ▼
┌───────────────────────────────┐  ┌──────────────────────────────────┐
│  Core engine (pure)           │  │  Persistence                     │
│  app/core/                    │  │  SQLAlchemy 2.0                  │
│  ├─ taxonomy.py               │  │  ├─ SQLite (default, WAL mode)   │
│  │   canonical skills         │  │  └─ Postgres (DATABASE_URL)      │
│  │   aliases + related graph  │  │                                  │
│  ├─ parser.py                 │  │  models: User · Job · Candidate  │
│  │   resume → ParsedResume    │  │          · Match                 │
│  └─ matcher.py                │  │                                  │
│      ParsedResume + Job       │  └──────────────────────────────────┘
│      → MatchResult            │
│                               │
│  No I/O. No DB. No config.    │
└───────────────────────────────┘
```

The core engine has **no imports from the app layer**. It cannot reach the database, the request, or the settings. That is enforced by convention and by the fact that it has no reason to — and it is what makes the matching logic testable in microseconds.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI 0.115 | Typed request/response models, automatic OpenAPI, dependency injection |
| Validation | Pydantic 2.10 | Every numeric field bounded; unbounded `years` is how you get a 10,000-year candidate |
| ORM | SQLAlchemy 2.0 | Typed `Mapped[]` columns; SQLite and Postgres from one code path |
| Auth | python-jose + passlib/bcrypt | JWT with per-password salt |
| Rate limiting | Custom dependency | See "Why not slowapi" below |
| Frontend | Vanilla JS | No build step, no node_modules, no framework churn |
| Tests | pytest | 127 tests, no network, no database |

---

## Data flow: adding a candidate

```
1. POST /api/jobs/{id}/candidates  { resume_text }
        │
2. _owned_job()  ── 404 if not yours (not 403 — see below)
        │
3. parse_resume(text)
        ├─ email / phone / location
        ├─ extract_experience_months()  → merge overlapping intervals
        ├─ extract_skills()             → strict pass over whole doc
        │  + non-strict pass over the "Skills" section
        ├─ titles / education
        └─ seniority  (explicit word wins; years are the fallback)
        │
4. explicit caller fields override the parse
        │
5. Candidate row written; 409 on duplicate (job_id, email)
        │
6. _score_and_store()  → Match row with the full breakdown as JSON
        │
7. 201 with the parsed candidate
```

### Why the breakdown is stored, not recomputed

`Match.breakdown` holds the full component list as JSON. Recomputing later would give a different answer once the weights change, and a recruiter who shortlisted someone on Tuesday deserves to see the reasoning they saw on Tuesday.

`GET /ranked` **does** recompute — that endpoint is what the recruiter sees *now*, and the two are allowed to differ. The stored copy is the historical record.

---

## The scoring model

### Weights

```python
WEIGHTS = {
    "skills":     0.45,
    "experience": 0.25,
    "seniority":  0.15,
    "location":   0.10,
    "education":  0.05,
}
```

A test asserts these sum to 1.0. If that test fails, every score in the product is on a different scale than the UI claims.

Skills dominate because they are the thing a recruiter can verify in a 20-minute call. Education is smallest because it is the weakest predictor and the most likely to introduce bias.

### Renormalisation — the important part

```python
applied_weight = sum(c.weight for c in components if c.applied)
contribution = score * (weight / applied_weight) * 100
```

A component is `applied=False` when the data to judge it is missing — no location on the resume, no education requirement on the job, or the role is remote.

Without this, a candidate with a blank location field scores 0 on location and loses 10 points for a data-entry gap. With it, the remaining weights scale up and the candidate is judged on what is actually known.

A test pins this: the same candidate with and without a location must score the same.

### Skill coverage

```
required_score = mean(credit for each required skill)
nice_score     = mean(credit for each nice-to-have)   # None if there are none

if no nice-to-haves:  score = required_score
else:                 score = required_score + (1 - required_score) * 0.3 * nice_score
```

Nice-to-haves **close part of a gap**; they never cap a complete match. A candidate with every required skill scores 1.0 whether or not they have the extras, because missing a nice-to-have is not a reason to rank someone below a perfect fit.

An earlier version used `0.8 * required + 0.2 * nice`, which capped a perfect candidate at 0.91 and made "100%" unreachable. The test suite caught it.

### Related-skill credit

`related_credit(owned, wanted)` returns 1.0 for an exact match, a graph factor for a related skill, and 0.0 otherwise. The graph is treated as **symmetric** even where only one direction is written down, because a one-way edge is almost always an oversight.

No factor exceeds 0.5, and a test enforces that across the whole graph. Partial credit that rounds up to full credit is a lie about coverage.

### Experience

Meeting the bar is 1.0. Exceeding it is worth nothing extra — a candidate with 15 years is not 50% better than one with 10 for a role that asked for 5. Below the bar the score falls off linearly with a floor of 0.15, because 4 years against a 5-year ask is not the same as 0 years.

### Seniority

Distance on the ladder. One level off is 0.75, two is 0.45, three or more is 0.15. Being **over**-qualified is penalised less than being under-qualified: an over-qualified hire is a retention risk, an under-qualified one is a delivery risk, and only one of those can be fixed with a conversation.

### Education

Degree levels are matched by level, not by substring. `"BSc Computer Science"` does not contain the word "bachelor", so a substring check scored a perfectly qualified candidate at 0.4. Abbreviations are the normal case on a resume, not the exception.

A higher degree satisfies a lower requirement. A lower degree does not satisfy a higher one, and the reason string says so.

---

## Resume parsing: the date arithmetic

The hard part is not the regexes. It is that `"2019 - 2022"`, `"Jan 2020 - Present"`, and `"03/2018 - 07/2019"` all have to become months, and **overlapping roles must not be double counted**.

```
1. Find every date range in the text
2. Convert each to a (start_month_index, end_month_index) interval
3. Drop reversed ranges (end before start) — a typo, not negative experience
4. Drop ranges starting in the future
5. Clamp ends to today
6. Merge overlapping intervals
7. Sum the merged intervals
```

Step 6 is the one that matters. A candidate who held two jobs at once for a year has **one** year of experience, not two. Without merging, a 3-year candidate with a side project looks like a 6-year one.

A bare year is treated as January — the conservative choice, since it under-counts rather than over-counts.

---

## Security

| Concern | Handling |
|---|---|
| Password storage | bcrypt, per-password salt, 72-byte limit enforced at the schema layer rather than silently truncating |
| Account enumeration | Login returns the same message and does the same work for "no such user" and "wrong password" |
| Tenant isolation | Another user's job returns **404, not 403** — a 403 confirms the job exists and leaks the shape of another tenant's pipeline |
| First-user admin | Opt-in via `FIRST_USER_IS_ADMIN`, default **off**. On a public deployment the first stranger to find the signup form would otherwise own the platform |
| Secrets | No secret has a usable default. Production refuses to start without `SECRET_KEY` |
| Headers | CSP, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS in production |
| Rate limiting | 10/min on auth, 120/min on writes, keyed by `X-Forwarded-For` first entry |
| Input bounds | Every numeric and string field bounded in the Pydantic schema |

### Why not slowapi

The first implementation used `@limiter.limit(...)` from slowapi. It broke every POST endpoint with a 422.

The decorator wraps the view function. FastAPI then resolves the string annotations from `from __future__ import annotations` against the **wrapper's** module globals — slowapi's, not ours. `UserCreate` could not be resolved, so FastAPI fell back to treating the request body as a query parameter.

Replaced with a `RateLimit` dependency, which FastAPI inspects from the real function signature. Two further bugs surfaced during the fix, both documented in the code:

1. A plain `@dataclass` defines `__eq__` and therefore drops `__hash__`. FastAPI keys its dependency cache by the callable, so every request raised `TypeError: unhashable type: 'RateLimit'`. Fixed with `@dataclass(eq=False)`.
2. A bound method has no `__globals__`, so a string annotation on `__call__` cannot be resolved either — `request: Request` became a required query parameter. Fixed by dropping the future import from that module.

---

## Scaling notes

**What breaks first, in order:**

1. **Rate limiting.** Per-process. N workers means N times the limit. Fix: Redis-backed counters.
2. **`GET /ranked` recomputes every score on every request.** Fine to a few hundred candidates per job; beyond that it needs caching or a background recompute on write.
3. **SQLite write contention.** WAL mode allows one writer at a time. Postgres is the answer and is one env var away.
4. **The parser is CPU-bound and synchronous.** It runs in the request thread. At volume it belongs in a worker queue.
5. **No migrations.** `create_all()` cannot evolve a schema. Alembic before the first schema change in production.

**What scales cleanly:** the core engine is pure and stateless, so it parallelises trivially. The API is stateless apart from the database, so it scales horizontally behind a load balancer once the rate limiter is shared.

---

## Deliberate omissions

Things a reviewer might expect and won't find, with the reason:

- **No Alembic.** Noted as a limitation rather than half-implemented.
- **No LLM resume extraction.** A regex parser that emits warnings when it is unsure is more honest than a model that hallucinates a skill. The `parse_warnings` field is surfaced in the UI for exactly this reason.
- **No skill join table.** The matcher works on whole lists and never queries across the table.
- **No frontend framework.** The UI is one screen with a modal; a framework would be more code, not less.
- **No WebSockets.** Nothing here is realtime. Adding them would be decoration.
