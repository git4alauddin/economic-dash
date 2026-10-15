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

Database, hosting, charting and scheduling choices remain open until feasibility
checks are complete.

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
| `API_HOST` | `backend/.env` | Listen address; development defaults to `127.0.0.1` |
| `API_PORT` | `backend/.env` | Listen port; default is `8000` |
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
