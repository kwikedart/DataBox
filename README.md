# DataBox

Standalone private-document service. It is not part of the MedRecs app and does not use that app's Firebase login, Control Plane, or Cloud SQL database.

Documents belong to an organization. PDF bytes stay on local disk in development and in a private GCS bucket in production. Share links store only an HMAC of the token. View tokens last at most five minutes and are sent as `Authorization: Bearer`.

## What you need

- Docker Desktop running
- Python 3.12

The local database password in `.env.example` is only for the Docker Postgres container on your machine. Change it in both `docker-compose.yml` and `backend/.env` if you want a different one. Do not send that password, or any real secret, in chat.

## Start it

Open PowerShell.

**1. Database and Redis**

Redis is published on port **6380** so it does not collide with anything already using 6379.

```powershell
cd D:\Intern\databox
docker compose up -d
```

**2. Python environment**

```powershell
cd D:\Intern\databox\backend
copy .env.example .env
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

If `py -3.12` is missing, use the Python 3.12 interpreter you already have.

**3. Create the tables**

```powershell
cd D:\Intern\databox\backend
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m alembic upgrade head
```

On first API start, development mode creates one owner when the user table is empty:

- email: `owner@localhost`
- password: `local-test-password`

Change `DATABOX_BOOTSTRAP_EMAIL` and `DATABOX_BOOTSTRAP_PASSWORD` in `backend/.env` before that first start if you want different values. The password must be at least 12 characters. Those bootstrap variables must be unset in production.

**4. API and website**

```powershell
cd D:\Intern\databox\backend
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8010
```

Open http://127.0.0.1:8010 and sign in. Upload a real PDF (`%PDF-` at the start, `%%EOF` at the end, no `/JavaScript`, `/Launch`, or `/EmbeddedFile`).

**5. Page images**

The API does not rasterize PDFs. In another window:

```powershell
cd D:\Intern\databox\backend
$env:PYTHONPATH = "."
.\.venv\Scripts\celery -A app.worker.celery_app worker --pool=solo --loglevel=INFO -Q databox_render
```

**View page** returns "Page is still rendering" until that worker finishes. Click it again after the worker logs the task.

## Tests that do not need Docker

```powershell
cd D:\Intern\databox\backend
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m pytest tests/test_databox.py
```

## Production

Set `APP_ENV=production` only with all of these:

- `DATABOX_AUTH_SECRET`, `DATABOX_TOKEN_PEPPER`, and `DATABOX_VIEW_TOKEN_SECRET`, each a unique secret of at least 32 characters
- `DATABOX_STORAGE=gcs` and `DATABOX_GCS_BUCKET` or `GCS_BUCKET_NAME`
- `DATABOX_REDIS_URL`
- no `DATABOX_BOOTSTRAP_PASSWORD`

`DATABOX_STORAGE=local` and the development auth secret are refused in production.
