# Economic Indicators Dashboard

A React and FastAPI dashboard for GDP growth, debt-to-GDP, trade, GST, inflation and government expenditure, with historical charts and a market ticker.

**Application:** [Open Dashboard](https://economic-dash-web.onrender.com)

**Backend:** [API Docs (Swagger)](https://economic-dash-api.onrender.com/docs) | [API Root](https://economic-dash-api.onrender.com) | [Health Check](https://economic-dash-api.onrender.com/health)

Evaluation credentials are shared privately. There is no public registration or default account.

## Explore the dashboard

After sign-in, choose **Live** for available source-backed observations, dates and history, or **Seed** for a complete, labelled sample dashboard. Seed values are frontend fixtures; they never enter the database or fill gaps in Live mode.

In Live mode, use the period and history controls, inspect **Series details** for provenance, or choose **Refresh data** to check for updates.

Live mode refreshes the API every 60 seconds while the page is visible. The backend collects independently on source-specific schedules. Missing values display as `—`; retained values are marked stale after failed or overdue checks.

## How it works

`React → authenticated FastAPI → private SQLite`, with a server-side collector fetching and validating upstream releases.

- **Frontend:** React, TypeScript, Vite and SVG charts; responsive layout targeting 1214 × 2159 CSS pixels.
- **Backend:** FastAPI, parameterized SQL, scheduled collection and checked schema migrations.
- **Authentication:** Argon2id password hashes and 15-minute JWTs kept in browser memory. Reload, expiry and sign-out require a new sign-in.
- **Hosting:** separate Render static-site and API services. SQLite lives on the API's persistent disk at `/var/data/economic-dash/dashboard.sqlite3`, with no database network listener or public file route.

## Data and limitations

All enabled sources are explicitly labelled **non-NSE** in the interface. NSE was assessed first; suitable acquisition, definition and reuse conditions remain unresolved for the required feeds.

| Live data | Public source | Meaning and refresh checks |
| --- | --- | --- |
| India GDP | [MoSPI via PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2269286) | Annual real growth (%), financial years; weekly, daily during selected release months |
| World GDP | [World Bank WDI](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG) | Annual real growth (%), calendar years; weekly |
| Trade | [Commerce Ministry via PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2323944) | Monthly merchandise exports/imports (USD billion); balance = exports − imports; daily, every 6 hours during release windows |
| Inflation | [MoSPI via PIB](https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2322244&lang=2&reg=48) | Monthly CPI year-on-year (%); daily, every 6 hours during release windows |
| Government expenditure | [Finance Ministry via PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2317034) | Financial-year cumulative amounts (₹ crore), not monthly flows; daily, every 12 hours during release windows |

Release links identify selected publications, not a promise of the latest data. Panels expose actual observation periods, source/as-of information and available history. Comparisons require matching definitions and periods; rate changes use percentage points, amount changes use percentages.

**Live gaps:** debt-to-GDP and the India/US comparison, GST total and monthly average, RBI target and all three market quotes remain unavailable pending source, definition or permission resolution. History can be partial; inconsistent releases are excluded. See the [source catalog](backend/app/data/source-catalog.json) for source choices, transformations and limitations.

## Run locally

Requires **Python 3.13.7**, **Node.js 24.19.0** and **npm 11.17.0**. Commands below use PowerShell; on Linux/macOS, use `.venv/bin/python` and `cp` instead of the Windows executable path and `Copy-Item`.

Clone the repository, then prepare the backend:

```powershell
git clone https://github.com/git4alauddin/economic-dash.git
cd economic-dash/backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Add an uncommented `AUTH_JWT_SIGNING_KEY=<generated key>` line to `backend/.env`. Then create a local account and start the API:

```powershell
.\.venv\Scripts\python.exe -m app.auth.provision --username evaluator
.\.venv\Scripts\python.exe run.py
```

Choose a private password of 15–128 characters at the hidden prompt. Provisioning and API startup apply migrations automatically; local SQLite lives under `backend/.runtime/database/`. Local and hosted accounts are separate.

In a second terminal, from the repository root:

```powershell
cd frontend
Copy-Item .env.example .env
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. API: **http://127.0.0.1:8000**; interactive API reference: **http://127.0.0.1:8000/docs**.

### Essential configuration

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Frontend's API origin; rebuild the frontend when changing a deployed value |
| `AUTH_JWT_SIGNING_KEY` | Backend-only secret: 32 random bytes encoded as 64 hex characters |
| `CORS_ALLOWED_ORIGINS` | JSON list of exact frontend origins; production allows only `["https://economic-dash-web.onrender.com"]` |
| `APP_ENV` | `development` locally; `production` on Render |
| `DATABASE_DIRECTORY` | Private database directory; production: `/var/data/economic-dash` |
| `COLLECTOR_SCHEDULER_STATE_DIRECTORY` | Shared collector-lock directory; same production path as the database |

Defaults and optional settings: [backend example](backend/.env.example), [frontend example](frontend/.env.example). Production settings: [backend](backend/.env.production.example), [frontend](frontend/.env.production.example) and [Render Blueprint](render.yaml). Keep credentials and actual `.env` files outside Git.

## API at a glance

Use [Swagger UI](https://economic-dash-api.onrender.com/docs) to explore requests and responses, or download the [OpenAPI schema](https://economic-dash-api.onrender.com/openapi.json). To try protected routes, execute `POST /api/v1/auth/login` with your privately supplied credentials, copy `access_token`, then paste the token alone into **Authorize → DashboardBearer**. Authorization is not persisted across page reloads; tokens expire after 15 minutes by default.

| Method and route | Access / purpose |
| --- | --- |
| `GET /` | Public API identity |
| `GET /health` | Public database readiness: 200 `{"status":"ok"}` or 503; does not certify source freshness |
| `POST /api/v1/auth/login` | JSON `{"username":"<username>","password":"<password>"}`; returns an access token, expiry and user |
| `GET /api/v1/auth/me` | Current authenticated identity |
| `GET /api/v1/dashboard` | All six panels and ticker |
| `GET /api/v1/indicators` | Indicator definitions and available periods |
| `GET /api/v1/indicators/{id}` | One panel; optional repeated `period=series_id:period_id` |
| `GET /api/v1/indicators/{id}/history` | One series; required `series_id`, optional `end_period_id` |
| `GET /api/v1/ticker` | Market quotes with explicit availability states |

Except the public routes and login, send `Authorization: Bearer <access_token>`. Dashboard, catalog, panel and history routes accept `window=1..24`. Data reads return `{data, meta}`; economic decimals are strings or `null`. Errors use `{error: {code, message, details}}`. Unchanged conditional reads may return 304. Full shapes are in [API models](backend/app/api_models.py).

## Checks and operations

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

From `frontend/`:

```powershell
node --test scripts/test-*.mjs
npm run build
```

Optional history collection, from `backend/`: `.\.venv\Scripts\python.exe -m app.collectors.refresh --history`. This fetches reviewed history from enabled sources and writes validated records; it requires upstream access and skips an overlapping collection.

Render runs one API worker and collector with a 1 GB persistent disk. Provision hosted accounts in the running API's Shell with `python -m app.auth.provision --username evaluator`. Share evaluation credentials privately. Use SQLite-consistent backups before schema changes; code rollback does not restore the database.

Both services are deployed; startup, health and sign-in have been exercised. Remaining hosted security, source-collection and restart-persistence checks are pending.
