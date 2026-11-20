# API Reference

Base URL: `http://127.0.0.1:8000`

Interactive docs: **`/api/docs`** (Swagger) · **`/api/redoc`** (ReDoc)

All endpoints except `/api/health`, `/api/auth/register`, and `/api/auth/login` require:

```
Authorization: Bearer <token>
```

---

## Errors

Every error returns the same shape:

```json
{ "detail": "Human-readable explanation." }
```

Validation errors (422) return FastAPI's standard array form with the offending field path.

| Code | Meaning |
|---|---|
| `401` | Missing token, invalid token, or wrong credentials |
| `403` | Authenticated but not permitted |
| `404` | Not found — **also returned for another user's resource** |
| `409` | Conflict: duplicate email, or candidate already in the pipeline |
| `422` | Validation failure, or a resume with no extractable email |
| `429` | Rate limit exceeded. Includes `Retry-After: 60` |

> **On 404 vs 403:** requesting another user's job returns `404`, not `403`. A `403` would confirm the job exists and leak the shape of another tenant's pipeline.

---

## Health

### `GET /api/health`

```json
{ "status": "ok", "app": "Bharti", "version": "1.0.0", "environment": "development" }
```

Unauthenticated. This is what the Docker healthcheck polls.

---

## Auth

### `POST /api/auth/register`

Rate limit: 10/min.

```json
{ "email": "you@example.com", "full_name": "Your Name", "password": "at-least-8-chars" }
```

`201` → `{ "access_token": "...", "token_type": "bearer", "user": {...} }`

`409` if the email is taken. `422` if the password is under 8 characters or over 72 bytes (bcrypt's limit — rejected rather than silently truncated).

### `POST /api/auth/login`

Rate limit: 10/min.

```json
{ "email": "you@example.com", "password": "..." }
```

`200` → same shape as register. `401` for both "no such user" and "wrong password" — identical message and identical work, so the endpoint cannot be used to enumerate accounts.

### `GET /api/auth/me`

`200` → the current user.

---

## Jobs

### `POST /api/jobs`

```json
{
  "title": "Senior Backend Engineer",
  "description": "Own the payments service.",
  "required_skills": ["python", "postgresql", "docker"],
  "nice_to_have_skills": ["kubernetes", "redis"],
  "min_years_experience": 5,
  "seniority": "senior",
  "location": "Karachi",
  "remote": false,
  "min_education": "bachelor"
}
```

`201` → the created job.

- `required_skills` — 1 to 30 entries, each 1–60 chars
- `seniority` — `intern` \| `junior` \| `mid` \| `senior` \| `lead` \| `principal`
- `min_education` — `none` \| `diploma` \| `bachelor` \| `master` \| `phd`
- `min_years_experience` — 0 to 60

### `GET /api/jobs`

`200` → your jobs, newest first, each with a `candidate_count`.

### `GET /api/jobs/{job_id}`

`200` → the job. `404` if it isn't yours.

### `PATCH /api/jobs/{job_id}`

Any subset of the create fields. **Changing requirements re-scores every candidate in the pipeline** and returns the updated job.

### `DELETE /api/jobs/{job_id}`

`204` on success. Cascades to candidates and matches.

### `GET /api/jobs/{job_id}/ranked`

The main endpoint. Returns every candidate scored against the job's **current** requirements, best first.

Returns a **JSON array**, not a wrapper object. Optional query params: `min_score` (0–100, default 0) and `limit` (1–500, default 100).

```json
[
  {
    "candidate": { "id": 4, "full_name": "Ayesha Khan", "email": "...", "status": "new" },
    "match": {
      "total": 100.0,
      "verdict": "Strong match — every required skill is covered. Worth a call today.",
      "confidence": "high",
      "components": [
        {
          "name": "skills",
          "weight": 0.45,
          "score": 1.0,
          "contribution": 45.0,
          "reason": "3/3 required skills exact, 1/1 nice-to-haves.",
          "applied": true
        },
        {
          "name": "experience",
          "weight": 0.25,
          "score": 1.0,
          "contribution": 25.0,
          "reason": "8.2 yrs meets the 5 yr requirement.",
          "applied": true
        }
      ],
      "required_skills": ["python", "postgres", "docker"],
      "nice_to_have": ["redis"],
      "gaps": [],
      "partial": [],
      "strengths": ["python", "postgresql", "docker"]
    }
  }
]
```

**Reading the breakdown:** `contribution` is the points this component added to `total`. The contributions sum to the total — a test asserts it. `applied: false` means the component was skipped for lack of data and its weight was redistributed; the `reason` says why.

### `POST /api/jobs/{job_id}/candidates`

```json
{
  "resume_text": "Ayesha Khan\nayesha@example.com\nKarachi\n\nSkills\nPython, PostgreSQL, Docker, Redis\n\nExperience\nSenior Engineer, Acme\nJan 2019 - Present",
  "full_name": "Ayesha Khan",
  "email": "ayesha@example.com",
  "location": "Karachi",
  "years_experience": 7.5,
  "seniority": "senior",
  "education": ["BSc Computer Science"]
}
```

Only `resume_text` is required. Any field you supply **overrides** what the parser found — useful when the parser gets something wrong and you'd rather correct it than re-upload.

`201` → the candidate, including `parse_warnings` (a list of things the parser was unsure about) and `parsed_skills`.

`409` if a candidate with that email is already in this job's pipeline. `422` if no email could be extracted and none was supplied.

### `GET /api/jobs/{job_id}/candidates`

`200` → all candidates in the pipeline, unscored.

### `PATCH /api/jobs/{job_id}/candidates/{candidate_id}`

```json
{ "status": "shortlisted" }
```

`status` — `new` \| `shortlisted` \| `rejected` \| `hired`

`200` → the updated candidate.

### `DELETE /api/jobs/{job_id}/candidates/{candidate_id}`

`204` on success.

---

## Meta

### `GET /api/skills`

Requires auth. `200` → the skill taxonomy, for autocomplete. Optional `q` filter and `limit` (1–500, default 200).

```json
[
  { "name": "python", "label": "Python", "category": "language", "aliases": ["py", "python3"] }
]
```

### `GET /api/admin/stats`

Admin only. `403` for everyone else.

```json
{
  "users": 3,
  "jobs": 2,
  "candidates": 6,
  "matches": 6,
  "average_score": 61.2,
  "shortlisted": 1
}
```

---

## Rate limits

| Scope | Default | Applies to |
|---|---|---|
| Auth | 10/min | `/api/auth/register`, `/api/auth/login` |
| Writes | 120/min | All POST / PATCH / DELETE |

Keyed by the first entry of `X-Forwarded-For`, falling back to the socket address. **Per-process** — N workers means N times the limit. Redis is the fix for multi-worker deployments.

Exceeding a limit returns `429` with `Retry-After: 60`.
