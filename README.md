# Economic Indicators Dashboard

A React and FastAPI application for the Interview Round II economic indicators
dashboard assignment.

## Current status

The M1.2 repository skeleton includes frontend and backend entrypoints, startup
scripts, editor settings and documentation boundaries. The frontend is a
placeholder; dashboard panels and authentic observations are not implemented.

Dependency installation, runtime selection, lockfiles, environment configuration
and service startup verification belong to M1.3. Database, authentication,
collection, integration tests and deployments remain outstanding.

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
      main.tsx         Browser entrypoint
      styles.css
    index.html
    package.json       Frontend dependencies and scripts
    tsconfig.json
    vite.config.js
  backend/
    app/
      __init__.py
      main.py          FastAPI application and bootstrap route
    requirements.txt   Initial dependencies; version verification is pending
    run.py             Local development launcher
  docs/
    README.md          Module ownership and naming conventions
  .editorconfig
  .gitignore
  README.md
```

Frontend dependencies are managed with npm from `frontend/`. Backend dependencies
are managed in an isolated Python environment from `backend/`. M1.3 will verify
the installed versions and record reproducible installation commands.

Planning documents and design exports currently live in the sibling `../doc/`
folder, outside this Git repository.

The README and relevant project files will document reproducible setup, API
contracts, data sources, decisions and limitations as they are implemented.

## Entrypoints and scripts

These commands require the dependencies and backend virtual environment to be
installed during M1.3; their runtime behavior has not yet been verified.

From `frontend/`:

```powershell
npm run dev
npm run typecheck
npm run build
npm run preview
```

The development server serves the placeholder at `http://127.0.0.1:5173`.
`preview` serves the production output after a successful build.

From `backend/`, using the planned local virtual environment:

```powershell
.\.venv\Scripts\python.exe run.py
```

The development API listens at `http://127.0.0.1:8000`. `GET /` returns a bootstrap
message. This is not the final health-check contract, which belongs to M4.

The frontend does not request indicator data yet. Configurable API access and
development CORS configuration are introduced in M1.3.

## Configuration and credentials

Real environment files, local databases, dependencies and generated output are
excluded by `.gitignore`. Reviewed `.env.example` files may be committed with
placeholders only. Evaluation credentials must be shared separately from the
public source code.
