# DataBox

DataBox is a private document workspace. People belong to an organization. They create documents, choose who can see them, and edit the current version together.

It is not part of the MedRecs app and does not use that app's Firebase login, Control Plane, or Cloud SQL database.

## Features

### Accounts and organizations

Sign-in is email and password. **Create an organization** starts a new organization and makes that person its owner. **Join an organization** uses the organization id shown on the workspace and adds the person as a member. The form cannot choose a role. Passwords must be at least 12 characters, and one address can create at most five accounts an hour.

The first development start, when the user table is empty, creates `owner@localhost`. That account is separate from organizations people create later.

The workspace shows the signed-in user id and the organization id. The user id is what another person pastes when sharing a document with them.

### Documents

A new document is a collaborative text document and starts **private**. The creator can switch it to **public**.

- A public document is listed for everyone in the organization. Its contents open only for the creator, a person it was shared with by user id, or a person whose labels match **Always opened by**.
- A private document is listed only for the creator and the people it was shared with by user id.
- **Blocked for** denies a person who carries that label, even when they were shared the document. The creator can still open their own document.

Someone who can see a public document but cannot open it can **Ask to view** or **Ask to edit**. The creator allows or denies the request. An organization owner or admin can also decide requests on public documents. An allowed request becomes a user-id share. That share does not expire. It cannot give the person more than their organization role, so a member can edit and a viewer can only read.

### Share links

The current version has an edit link and a view link. Older versions keep a view link. The owner sets the lifetime from 1 to 168 hours. Setting it issues a new link and the previous URL stops working.

A link requires sign-in first, and the signed-in person must belong to the document’s organization. The link does not by itself open the contents. The person must already be allowed: they created it, it was shared with their user id, or their label matches. The page records who opened it. A denied open is stored as denied, and the client is told the link is unavailable.

A view link shows a picture of the document. An edit link opens the live editor.

### Editing

The editor supports heading, subheading, bold, and italic. People on the current version see each other’s text and presence. **Save version** freezes the current text as a new version. The new version becomes the one that can be edited. Older edit links stop working. Each saved version keeps its own view link.

### Labels

**My labels** on the workspace are the signed-in person’s tags, such as `finance` or `contractor`. On a document, **Always opened by** lists labels that may open a public document, and **Blocked for** lists labels that may not. Only an owner, an admin, or the document’s creator can change those labels and the user-id shares.

## Implementation

The document rules sit in the middle of the program. HTTP, the database, and file storage sit outside that middle and call inward.

| Layer | Where | Responsibility |
| --- | --- | --- |
| Domain | `backend/databox/domain` | Documents, labels, share rules, tokens. No web framework and no database. |
| Application | `backend/databox/application/service.py` | Use cases: create, list, share, request access, collaborate, render. |
| Infrastructure | `backend/databox/infrastructure` | Postgres, local files, GCS, Redis, and in-memory stand-ins used by tests. |
| Delivery | `backend/app` | FastAPI routes, sign-in, and process startup. |
| Website | `frontend/src` | React workspace, editor, and share page. |

Sign-in and account creation talk to the user tables directly from `backend/app/auth_routes.py`. The collaboration entry module also points at the FastAPI app. Those two edges sit outside the inward-only split.

### Processes

Local development runs several processes:

- The website is Vite, normally `http://localhost:5173`. It proxies `/api` to the API and collaboration WebSockets to the collaboration process.
- The API is `app.main` on port 8000. It checks accounts, documents, shares, and labels. It does not rasterize PDFs.
- Collaboration is `app.collab_main` on port 8001. The browser first asks the API for a short single-use ticket, then sends that ticket on the socket.
- Page pictures are rendered by a Celery worker when `DATABOX_RENDER_QUEUE=celery`, or by `app.render_main` when the queue is HTTP.
- Postgres stores accounts and document metadata. Redis carries live editing fan-out, tickets, locks, and policy epochs. Redis data is not kept across a container restart.

### What is stored where

Postgres database `databox` holds organizations, users, password hashes, memberships, labels, documents, versions, user-id shares, expiring share-link hashes, access requests, audit events, and the collaborative text. The text is a Yjs snapshot plus an update log (`databox_collaboration_documents` and `databox_yjs_updates`), not the small `.txt` file stored beside it.

Document files and rendered pictures use keys shaped like `org/{organization-id}/documents/{document-id}/versions/{version-id}.txt` and `.../renders/{version-id}/page-1.webp`. In development those files are under `backend/data/objects`. In production the same layout goes to a private GCS bucket, and local disk storage is refused.

A share URL contains a random token. The database stores an HMAC of that token. A sealed copy lets an owner or admin display the current links again. The raw token is not the lookup key.

The browser keeps the sign-in token in memory, so a reload asks for sign-in again. A short-lived page token for an open picture is kept in `sessionStorage` under `databox:view:{documentId}` and is cleared when the tab closes. Reading a rendered page checks that token without querying the database. Issuing a token, opening a share link, and joining collaboration still re-check the database, labels, and expiry.

### Access decision

For someone who did not create the document:

1. A blocked label denies access.
2. A private document opens only when that user id has a viewer or editor share.
3. A public document opens when an audience label matches, or when that user id has a viewer or editor share.
4. Otherwise a public document stays in the list and can be requested. A private document is omitted and a direct open is reported as not found.

Missing, expired, revoked, cross-organization, and denied links all return the same not-found response, so the client cannot tell those cases apart.

### Versions and collaboration

The editor shares a Yjs document. The server persists each accepted update before acknowledging it. Viewers can receive the document, and their edit frames are ignored. Saving a version compacts the current Yjs state onto the new version and revokes edit links that pointed at the previous version. The website reconnects because the current version id changed.

### Tests

`backend/tests/test_databox.py` runs the use cases against memory adapters. It covers label denial, expiring links, versioned shares, user-id shares, public documents that stay closed until the creator approves a request, and private documents that stay hidden.

## What you need

- Docker Desktop, running
- Python 3.12
- Node.js 18 or newer

The password in `backend/.env.example` is only for the Postgres container on your machine. Change it in both `docker-compose.yml` and `backend/.env` if you want a different one. Do not send that password, or any real secret, in chat.

## Run it on your machine

Use four terminals after the database is up. Start them from the repository root. On Windows, the Python commands below are for PowerShell.

**1. Postgres and Redis**

Redis is published on port **6380** so it does not collide with anything already using 6379. Postgres is published on port **5434**.

```powershell
docker compose up -d postgres redis
```

**2. Python environment and tables**

```powershell
cd backend
copy .env.example .env
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m alembic upgrade head
```

If `py -3.12` is missing, use the Python 3.12 interpreter you already have. On macOS or Linux, create the virtualenv with `python3.12 -m venv .venv` and call `./.venv/bin/python` instead of `.\.venv\Scripts\python`.

`backend/.env` is loaded by the API and the collaboration process. `alembic upgrade head` creates the tables. Run it again after pulling a change that adds a migration.

**3. API**

Leave this running.

```powershell
cd backend
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**4. Collaboration**

Leave this running in a second terminal. Editing stays disconnected without it.

```powershell
cd backend
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m uvicorn app.collab_main:app --host 127.0.0.1 --port 8001
```

**5. Page renderer**

Leave this running in a third terminal. `backend/.env.example` sets `DATABOX_RENDER_QUEUE=celery`, so the API sends picture jobs to this worker. A view link shows "Page is still rendering" until the worker finishes; open the page again after that.

```powershell
cd backend
$env:PYTHONPATH = "."
.\.venv\Scripts\celery -A app.worker.celery_app worker --pool=solo --loglevel=INFO -Q databox_render
```

**6. Website**

Leave this running in a fourth terminal.

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in.

The website proxies `/api` to `http://127.0.0.1:8000` and collaboration sockets to `http://127.0.0.1:8001`. Do not open port 8000 in the browser for the workspace.

### First sign-in

The first API start, when the user table is empty, creates one owner:

- email: `owner@localhost`
- password: `local-test-password`

Change `DATABOX_BOOTSTRAP_EMAIL` and `DATABOX_BOOTSTRAP_PASSWORD` in `backend/.env` before that first start if you want different values. The password must be at least 12 characters. Unset `DATABOX_BOOTSTRAP_PASSWORD` in production.

After that, use **Create an organization** for a new organization or **Join an organization** with an organization id from someone who is already in it. Then choose **New document**, mark it public or leave it private, and share it with another person's user id.

### What should be listening

| Process | Address |
| --- | --- |
| Website | http://localhost:5173 |
| API | http://127.0.0.1:8000 |
| Collaboration | http://127.0.0.1:8001 |
| Postgres | `127.0.0.1:5434` |
| Redis | `127.0.0.1:6380` |

## Run everything in Docker

This builds the API, collaboration process, render worker, and website. It does not use `backend/.env`. Do not also start the local API or website, because both want ports 8000 and 5173.

```powershell
docker compose up --build -d
```

Open http://localhost:5173. The first owner inside that stack is still `owner@localhost` / `local-test-password`. Page rendering goes to the compose render worker over HTTP, not to the Celery command above.

Stop it with `docker compose down`. That keeps the database volume. `docker compose down -v` deletes the database volume and the stored files.

## Tests that do not need Docker

```powershell
cd backend
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m pytest tests/test_databox.py
```

## Host it on a server

This runs the website, API, collaboration socket, and page renderer on one Linux server. Postgres, Redis, and the document files stay on that server and are not published to the internet. Only ports 80 and 443 are opened. You need a domain name, not an IP address, so the server can get a certificate.

On the server, install Docker and Docker Compose, then clone this repository.

```sh
cd /opt
git clone https://github.com/kwikedart/DataBox.git databox
cd databox
sh deploy/prepare-env.sh
```

The script asks for the domain, for example `databox.example.com`, and writes `.env.production`. That file holds the generated secrets. Do not commit it. Create a DNS A record from that domain to the server's public IP address, then start the stack:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Open `https://your-domain`. There is no pre-made owner on this stack. Use **Create an organization** and a password of at least 12 characters. Give the organization id on the workspace to anyone who should join.

Document bytes are stored in a private Docker volume at `/var/lib/databox/objects` inside the containers. That mode is `DATABOX_STORAGE=volume`. It is for this single server. A deployment that spreads the API and the renderer across more than one machine should use `DATABOX_STORAGE=gcs` and a private bucket instead.

Watch the logs with:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f api collab web caddy
```

Stop it with `docker compose --env-file .env.production -f docker-compose.prod.yml down`. Adding `-v` deletes the database, the document files, and the certificate. Do not add `-v` unless you mean to erase them.

## Production

Set `APP_ENV=production` only with all of these:

- `DATABOX_AUTH_SECRET`, `DATABOX_TOKEN_PEPPER`, and `DATABOX_VIEW_TOKEN_SECRET`, each a unique secret of at least 32 characters
- `DATABOX_STORAGE=gcs` and `DATABOX_GCS_BUCKET` or `GCS_BUCKET_NAME`
- `DATABOX_REDIS_URL`
- no `DATABOX_BOOTSTRAP_PASSWORD`

`DATABOX_STORAGE=local` and the development auth secret are refused in production.
