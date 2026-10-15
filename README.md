# Economic Indicators Dashboard

A React and FastAPI application for the Interview Round II economic indicators
dashboard assignment.

## Current status

M1.2 provides the repository skeleton. M1.3 adds pinned dependencies, environment
configuration, development CORS and a placeholder that checks its FastAPI connection.
Local startup, browser rendering, backend configuration tests and frontend builds
have been verified.

Dashboard panels, authentic observations, database storage, authentication,
scheduled collection, full integration QA and deployments remain outstanding.

## Planned scope

- Reproduce the supplied Figma design at the 1214 × 2159 CSS-pixel evaluation viewport.
- Provide a market ticker and panels for GDP growth, debt-to-GDP, trade, GST
  collection, inflation and government expenditure.
- Serve dashboard data through FastAPI using verified public sources, with NSE
  used where it provides the required data.
- Include source and observation dates, scheduled collection, history and honest
  missing/stale states.
- Provide authentication, private database storage and separate HTTPS frontend
  and API deployments.

The working production topology below selects hosting, storage, scheduling and
update delivery based on provider documentation. Deployment verification remains
outstanding. Charting is selected during the M2 design audit.

## Repository and local materials

```text
economic-dash/
  frontend/
    src/
      App.tsx          React placeholder
      api.ts           Bootstrap API connection check
      config.ts        Public API URL configuration
      main.tsx         Browser entrypoint
      styles.css
    .env.example
    .npmrc
    index.html
    package.json       Frontend dependencies and scripts
    package-lock.json  Exact dependency resolution
    tsconfig.json
    vite.config.js
  backend/
    app/
      __init__.py
      config.py        Validated environment settings
      main.py          FastAPI application and bootstrap route
    tests/
      test_configuration.py
    .env.example
    .python-version
    requirements.in    Direct runtime dependencies
    requirements.txt   Pinned runtime dependency resolution
    requirements-dev.in
    requirements-dev.txt
    run.py             Local development launcher
  .editorconfig
  .gitignore
  .node-version
  README.md
```

Frontend dependencies are managed with npm from `frontend/`. Backend dependencies
are managed with uv in an isolated Python environment from `backend/`.

Planning documents and design exports currently live in the sibling `../doc/`
folder, outside this Git repository.

This README will document reproducible setup, API contracts, data sources,
decisions and limitations as they are implemented. Private implementation logs
record progress separately; evaluator-facing instructions belong in this repository.

## Ownership and naming

| Module | Responsibility |
| --- | --- |
| M1 | Repository conventions, architecture decisions and shared contracts |
| M2 | Frontend design system, dashboard panels and controls |
| M3 | Source register, validation and scheduled collection |
| M4 | Database schema, SQL, dashboard API and health contract |
| M5 | Authentication, secrets and CORS |
| M6 | Integration and quality verification |
| M7 | Deployment, operational documentation and submission |

- React components use PascalCase filenames; the browser entrypoint is `main.tsx`.
- Python modules and functions use `snake_case`; the API entrypoint is `app/main.py`.
- Commit titles follow `m<module>.f<feature>.<snake_case_name>`.

## Production topology — M1.4 feasibility baseline

Provider documentation was checked on **2026-10-15**. This is the implementation
baseline and deployment test plan; no live deployment or database privacy test has
been performed. Accounts, availability and the actual hosting bill remain unconfirmed.

| Component | Selected placement | Configuration boundary |
| --- | --- | --- |
| React frontend | Vercel static Vite deployment | Repository root directory `frontend/`; output `dist/`; HTTPS frontend origin |
| FastAPI | A paid Render Python web service | Root directory `backend/`; one instance and one Uvicorn worker; separate HTTPS API origin |
| Database | Integrated SQLite on the API's persistent disk | Mount `/var/data`; planned file `/var/data/economic-dash/dashboard.sqlite3`; backend-only file access |
| Collector | Scheduled asyncio task owned by FastAPI lifespan | Same process as API; source-specific schedules; server-side upstream access only |
| Client updates | Authenticated dashboard polling | Every 60 seconds while visible and signed in; upstream collection runs independently |
| Health | Planned public API route `/health` | M4 implements the contract; M7 configures Render's HTTP health path |

The browser downloads the React application from Vercel and requests indicator
data from Render. The collector validates public-source observations before
writing SQLite; FastAPI serves the stored observations. The frontend has no
database or upstream credentials.

### ADR-03 — integrated database

**Decision/reason:** use SQLite on the paid API instance's persistent disk to keep
storage private and reduce infrastructure for this single-instance assignment.
**Alternative:** private-network PostgreSQL if independent workers or horizontal
scaling become necessary. **Constraints/consequence:** all database files stay on
the mounted path, outside served assets; no database listener or file-download
route is introduced. M4 owns schema, parameterized SQL, locking and consistent
backup/restore. **Verification/owners:** M4 and M7 must verify persistence across
restart/redeploy, file permissions and absence of public database access.

[Render disks](https://render.com/docs/disks) preserve mounted files across
restarts/deploys, are available only to paid services, and can be attached to only
one service instance. Other services and cron jobs cannot share that disk.

### ADR-04 — separate HTTPS hosts

**Decision/reason:** Vercel serves the frontend and Render runs FastAPI, providing
distinct hosting environments and websites. **Alternative:** another static host
plus a VM; that adds operating-system/TLS administration to the timebox.
**Constraints/consequence:** use actual assigned production origins in
`VITE_API_BASE_URL` and the backend's one-origin production CORS allowlist. Do not
allow every preview domain. **Verification/owner:** M7 checks both URLs, TLS,
provider/build settings, evaluator access and CORS; M5 verifies authentication.

[Vercel supports Vite deployments and SPA routing](https://vercel.com/docs/frameworks/frontend/vite)
and [managed HTTPS](https://vercel.com/docs/domains/working-with-ssl).
[Render documents native FastAPI deployment](https://render.com/docs/deploy-fastapi)
and [HTTPS/port routing](https://render.com/docs/web-services).

Planned build/runtime settings for M7:

- Frontend: Vite preset, Node 24.x, install with `npx --yes npm@11.17.0 ci`, build
  with `npm run build`, output `dist/`. Add the documented SPA rewrite when client
  routes are introduced. Build with the actual HTTPS API URL.
- Backend: set `PYTHON_VERSION=3.13.7`; build with
  `python -m pip install -r requirements.txt`; start with
  `python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1`.
  Set `APP_ENV=production` and the exact HTTPS frontend origin. Do not use reload.
- Vercel manages Node minor/patch versions, so its build must satisfy our package
  engine range and pass a clean build; an exact cloud patch match is not assumed.
  [Node support](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions).
- Render supports an explicit Python version, avoiding its changing default.
  [Python version selection](https://render.com/docs/python-version).

### ADR-05 — collector scheduling ownership

**Decision/reason:** M3 starts one scheduled asyncio task in FastAPI's lifespan and
cancels/awaits it on shutdown. An explicit single-instance/single-worker topology
gives that task one owner with access to the same SQLite file. This is a design
inference from normal Python service execution, to be tested on the host.
**Alternatives:** separate cron/worker plus private PostgreSQL, or a VM scheduler.
**Constraints/consequence:** no autoscaling, multiple workers or request-triggered
source collection. Persist run/observation metadata, prevent overlapping runs,
recover due work after restarts, and implement timeouts/backoff in M3. Brief
deploy interruptions remain possible. **Verification/owners:** M3 and M7 check
jobs run without browser traffic and that restarts never create duplicate runners.

Implementation basis: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
and [Python asyncio tasks](https://docs.python.org/3.13/library/asyncio-task.html).

### ADR-06 — frontend update delivery

**Decision/reason:** choose documented polling over SSE for the initial application;
it works through standard HTTPS requests and avoids persistent-stream reconnect
logic. **Alternative:** SSE remains a future interface change if justified by
measured requirements. **Constraints/consequence:** M6 polls the authenticated
dashboard API every 60 seconds while visible, avoids overlapping requests, pauses
when hidden, refreshes on return and backs off failures up to five minutes. M3
sets source-specific collection cadences; polling does not imply tick-level data.
Retained observations keep their original dates and are marked stale on refresh
failure. **Verification/owners:** M4/M6 test request timing, session expiry,
visibility, outages and last-valid-data behavior; M1.5 defines the API contract.

### Costs, rejected options and remaining risks

- The candidate frontend plan is [Vercel Hobby](https://vercel.com/docs/plans/hobby),
  free within its limits for eligible personal/non-commercial use. This assumes
  a personal assessment project; verify eligibility during provisioning.
- The backend **requires a paid Render web service plus disk**. Resources have
  not been provisioned. Confirm plan availability and current
  [pricing](https://render.com/pricing) before provisioning in M7.
- [Render Free](https://render.com/docs/free) was rejected for this topology:
  idle spin-down interrupts scheduling and its ephemeral filesystem cannot retain
  SQLite across restarts; persistent disks are unavailable on Free.
- Private PostgreSQL remains a feasible alternative, with public/external access
  disabled and the internal URL used by the backend. The default external-access
  configuration is unsuitable. [Render database access controls](https://render.com/docs/postgresql-creating-connecting#restricting-external-access).
- A disk-backed API is limited to one instance and has redeploy interruption.
  Keep resource usage bounded and use a database-consistent backup/restore procedure.
- Upstream access from the selected host is unproven. M3/M7 must test the actual
  NSE/public endpoints from that environment; a blocked source may require a
  hosting change. Do not invent values or assume an untested source works.

### Deployment verification plan

All live checks below are **pending**, not results established by M1.4.

| Condition | Required evidence | Owner |
| --- | --- | --- |
| Separate websites/environments and HTTPS | Independent Vercel/Render settings, assigned origins, valid TLS and evaluator access in a logged-out browser | M7 |
| Reproducible hosted build | Actual Node/npm/Python versions and successful install/build from pinned files | M7 |
| Private database | Backend-only file permissions, no database listener/public download route, no DB in frontend assets or repository | M4/M5/M7 |
| Persistent history | Write a known test observation, restart and redeploy, then confirm its identity/value remain intact; exercise backup restoration | M4/M7 |
| One scheduled collector | Run through multiple due intervals without browser traffic; inspect ownership, overlap prevention and restart recovery | M3/M7 |
| Restrictive production CORS | Exact frontend origin succeeds; localhost, preview and untrusted origins are rejected for browser access | M5/M7 |
| Health routing | M4's `/health` responds independently of sign-in and external source availability, reports local dependency failure, and passes Render HTTP probes | M4/M7 |
| Polling and stale data | Verify cadence, visibility/session handling, failure backoff and retained values/source dates during an upstream outage | M3/M4/M6 |
| Provider/source feasibility | Confirm account/paid-plan access and actual upstream responses from the API host before evaluation | M3/M7 |

[Render HTTP health checks](https://render.com/docs/health-checks) can target a
configured path. Add that setting only after M4 implements the route; the current
bootstrap route is not a substitute for the final health contract.

## Local setup

The verified runtimes are Node.js **24.19.0**, npm **11.17.0** and Python
**3.13.7**. Node and Python versions are recorded in `.node-version` and
`backend/.python-version`; npm is declared in `frontend/package.json`.
Install uv for Python environment and package management.

These PowerShell instructions start from the repository root in separate terminals.

### Backend

For a clean checkout, create an isolated environment and install the pinned
development dependencies:

```powershell
cd backend
uv venv --python 3.13.7 .venv
uv pip sync --python .venv/Scripts/python.exe requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe run.py
```

If PyCharm already supplies an isolated environment, substitute its configured
Python executable for `.venv/Scripts/python.exe`. The environment can live outside
the repository; application configuration still loads from `backend/.env`.

The API listens at `http://127.0.0.1:8000`. Development mode enables reload;
test and production modes do not. Runtime-only installs use `requirements.txt`.

### Frontend

```powershell
cd frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm ci
npm run dev -- --strictPort
```

Open `http://127.0.0.1:5173`. With the API running, the placeholder displays
"The dashboard is coming soon." Failed API requests produce an unavailable message.

`npm run build` type-checks and creates `dist/`; `npm run preview` serves that build
locally. For preview against the API, explicitly add its exact origin (normally
`http://127.0.0.1:4173`) to the development backend allowlist.

## Environment configuration

| Variable | Location | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `frontend/.env` | Public FastAPI base URL; sample is `http://127.0.0.1:8000` |
| `APP_ENV` | `backend/.env` | `development`, `test` or `production` |
| `API_HOST` | `backend/.env` | Development launcher listen address; default is `127.0.0.1` |
| `API_PORT` | `backend/.env` | Development launcher listen port; default is `8000`; the hosted start command uses Render's `PORT` |
| `CORS_ALLOWED_ORIGINS` | `backend/.env` | JSON array of exact frontend origins, without paths or trailing slashes |

Backend process variables override `backend/.env`. Restart the API after changing
its environment. For the frontend, restart Vite after changing `.env`; deployed
builds must be rebuilt with their API URL. `VITE_` variables are public browser
configuration and must never contain secrets.

The sample CORS allowlist permits only `http://127.0.0.1:5173` and
`http://localhost:5173`, with GET requests and no credentialed cookies. CORS controls
browser access; it is not authentication. Production configuration requires
`APP_ENV=production` and exactly one explicitly configured HTTPS frontend origin.
Wildcards and development defaults are rejected in production. Provider-specific
deployment settings and authentication are addressed in later modules.

## Current API

- `GET /`: public bootstrap response, `{"message":"Economic Indicators API"}`.
- `GET /docs`: generated interactive API documentation.
- `GET /openapi.json`: generated OpenAPI schema.

The bootstrap response is not a health contract or authentic indicator data.
M4 owns the final health and dashboard routes; M5 owns authentication.

## Verification and dependency updates

From `frontend/`, run `npm run typecheck` or `npm run build`.

From `backend/`, using the isolated environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The seven tests cover example configuration, dotenv/process precedence, invalid
ports and CORS origins, production restrictions and allowed/rejected preflights.
Local HTTP and browser startup were also checked. Changing only
`VITE_API_BASE_URL` was verified to change the generated build's API configuration.

`package-lock.json` is the frontend dependency lock. Backend `requirements*.in`
files declare direct dependencies; the corresponding `.txt` files pin their
resolved dependencies. To deliberately regenerate backend pins from `backend/`:

```powershell
uv pip compile requirements.in --universal --output-file requirements.txt --no-header --annotation-style line
uv pip compile requirements-dev.in --constraint requirements.txt --universal --output-file requirements-dev.txt --no-header --annotation-style line
```

Use the pinned Python interpreter for regeneration. Review dependency changes and
rerun verification before committing updated lockfiles.

Implementation references: [uv dependency locking](https://docs.astral.sh/uv/pip/compile/),
[Vite environment configuration](https://vite.dev/guide/env-and-mode) and
[FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/).

## Configuration and credentials

Real environment files, local databases, dependencies and generated output are
excluded by `.gitignore`. Reviewed `.env.example` files may be committed with
placeholders only. Evaluation credentials must be shared separately from the
public source code.
