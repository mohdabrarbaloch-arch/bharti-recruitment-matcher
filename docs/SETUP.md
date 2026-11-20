# Setup

## Requirements

- Python 3.11 or newer
- pip
- Optional: Docker + Docker Compose (for the Postgres path)

No Node, no build step, no external services.

---

## Local setup

```bash
git clone https://github.com/mohdabrarbaloch-arch/bharti-recruitment-matcher.git
cd bharti-recruitment-matcher

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env
```

`SECRET_KEY` is the only variable you must set. The app refuses to start in production without it, and the Docker Compose file will not come up without one either — a default signing key in a public repo is how sessions get forged.

### Seed demo data

```bash
python -m scripts.seed
```

Creates an account, two roles, and six candidates. The resumes deliberately exercise the parser's awkward cases: overlapping roles, missing dates, inconsistent skill spellings, and one strong match with a single gap.

### Run

```bash
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**

```
email:    abraz@example.com
password: bharti-demo-2026
```

---

## Docker

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
docker compose up --build
```

Brings up Postgres 16 and the app. The app waits for the database healthcheck before starting.

To seed inside the container:

```bash
docker compose exec app python -m scripts.seed
```

---

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | *(none)* | **Required in production.** JWT signing key. Generate with `secrets.token_urlsafe(48)`. |
| `ENVIRONMENT` | `development` | `development` \| `production` \| `test`. Production enables HSTS and enforces `SECRET_KEY`. |
| `DATABASE_URL` | `sqlite:///./bharti.db` | Any SQLAlchemy URL. Postgres: `postgresql+psycopg://user:pass@host:5432/db` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token lifetime (24 hours). |
| `CORS_ORIGINS` | `http://localhost:8000` | Comma-separated allow-list. |
| `RATE_LIMIT_AUTH` | `10` | Auth requests per minute per IP. |
| `RATE_LIMIT_DEFAULT` | `120` | Write requests per minute per IP. |
| `FIRST_USER_IS_ADMIN` | `false` | Opt-in. Leave off on any public deployment. |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

---

## Running the checks

```bash
pytest -q                    # 127 tests, ~9s, no network, no database
ruff check .                 # lint
ruff format --check .        # formatting
```

---

## Troubleshooting

**`RuntimeError: SECRET_KEY must be set`**
You're in production mode without a key. Either set `SECRET_KEY` or set `ENVIRONMENT=development`.

**`TypeError: unhashable type: 'RateLimit'`**
You're on an old copy of `app/limiter.py`. The `RateLimit` dataclass needs `eq=False` so FastAPI can hash it for its dependency cache.

**Every POST returns 422 with the body read as a query parameter**
Something reintroduced `from __future__ import annotations` into `app/limiter.py`. FastAPI resolves a bound method's annotations against `__globals__`, which a bound method does not have. That module must not use the future import.

**`sqlite3.OperationalError: database is locked`**
SQLite allows one writer at a time. Fine for local use; use Postgres for anything concurrent.

**Port 8000 already in use**
`uvicorn app.main:app --reload --port 8001`

---

## Deploying

This app needs a **persistent database** and a **long-running process**. Vercel's serverless model provides neither, so it is the wrong host.

Good fits: a small VPS, Railway, Render, or Fly.io — all of which can build the included `Dockerfile` directly.

Checklist before you deploy:

1. Set `SECRET_KEY` to a fresh random value.
2. Set `ENVIRONMENT=production`.
3. Set `DATABASE_URL` to a managed Postgres instance.
4. Set `CORS_ORIGINS` to your real origin.
5. Leave `FIRST_USER_IS_ADMIN=false`.
6. Put a reverse proxy with TLS in front, and make sure it sets `X-Forwarded-For` — the rate limiter keys on it.
