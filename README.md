# Economic Indicators Dashboard

A React and FastAPI application for the Interview Round II economic indicators
dashboard assignment.

## Current status

M1.2 provides the repository skeleton. M1.3 adds pinned dependencies, environment
configuration, development CORS and a placeholder that checks its FastAPI connection.
Local startup, browser rendering, backend configuration tests and frontend builds
have been verified.

M1.4–M1.6 document the production feasibility baseline, shared contracts and first
indicator handoff. M1.6 rechecked local HTTP/CORS behavior; source locking and the
authentic data pipeline remain downstream work.

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
when hidden, refreshes on return and backs off transient network/server failures
up to five minutes; an explicit rate-limit retry delay may be longer. M3
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

## Cross-module contracts — M1.5

This is the agreed interface baseline for M2–M5, replacing the planners'
illustrative payloads. It does not implement the routes, authentication, collector
or database. M4 owns final Pydantic models/SQL schemas; changes to these meanings
or required fields must update this agreement and its consumers.

### API version, routes and access — ADR-07/08

Business/auth routes use `/api/v1`. Additive optional metadata may remain in v1;
breaking names, types or meanings require an explicit contract revision and
coordinated consumers, or a new API version.

| Method/path | Access | Contract owner/purpose |
| --- | --- | --- |
| `GET /` | Public | Existing non-sensitive bootstrap message; no economic data |
| `GET /health` | Public | M4: local service/database readiness; 200 when ready, 503 otherwise; no source fetch or secrets |
| `POST /api/v1/auth/login` | Public, throttled | M5: JSON `username` and `password`; generic 401 on invalid credentials |
| `GET /api/v1/auth/me` | Bearer token | M5: current user's opaque `id` and normalized `username` |
| `GET /api/v1/indicators` | Bearer token | M4: indicator/series definitions, units, available periods and supported controls |
| `GET /api/v1/dashboard` | Bearer token | M4: ticker plus all six panels; primary boot/poll request |
| `GET /api/v1/indicators/{indicator_id}` | Bearer token | M4: selected panel's series, summaries and comparisons |
| `GET /api/v1/indicators/{indicator_id}/history` | Bearer token | M4: bounded history for validated series/period selections |
| `GET /api/v1/ticker` | Bearer token | M4: individually attributed/timestamped verified market quotes |
| `OPTIONS` for API routes | No token; exact-origin CORS | M5: browser preflight; never returns protected application data |
| `/docs`, `/openapi.json` | Public in development; disabled by default in production | M5 applies the production policy; repository documentation remains available to evaluators |
| Collector ingestion | In-process only | M3 calls M4's transactional ingest service; no public HTTP ingestion route |

There is no `/updates` endpoint in this polling design. Every data route is
protected on FastAPI independently of React guards and CORS. Unknown indicator
or series resources return 404; invalid query/period selections return 422.
Indicator detail accepts an optional catalog `period_id`; an absent observation
for an explicitly selected valid period stays null, never silently switching to
another period. The history query accepts optional `series_id`,
`from_period`, `to_period` and `limit`. Period IDs come from the catalog, are
inclusive and must share a comparable period type; clients do not infer fiscal
boundaries. `limit` defaults to 120, with an allowed range of 1–500 points per series.
Return the latest matching window in chronological order and report `truncated`
when more matching points exist. M2's audited controls determine the offered
windows; this contract does not invent additional controls.

### Stable indicator and series identifiers

| `indicator_id` | Initial series IDs/roles |
| --- | --- |
| `gdp_growth` | `gdp_growth_india`, `gdp_growth_world` |
| `debt_to_gdp` | `debt_to_gdp_india`; audited comparison series added explicitly to the catalog |
| `trade` | `imports`, `exports`, `trade_balance` |
| `gst_collection` | `gst_total`, `gst_monthly_average`; distinct growth series if required by the audited view |
| `inflation_india` | `cpi_yoy`, `rbi_target` |
| `government_expenditure` | `expenditure_total`, `expenditure_capital`, `expenditure_revenue` |

The ticker has its own endpoint and `instrument_id` catalog. M3 verifies each
instrument's identity/provider mapping; a non-NSE instrument must not receive NSE
attribution. Series/catalog IDs are stable application identifiers, independent
of display labels. M2/M3 must still verify debt comparison meaning, GST definitions,
budget coverage and exact Figma control windows. An unresolved definition is
reported unavailable with a reason, rather than filled with an assumed figure.

Ticker items use `instrument_id`, `name`, `value`, `change`, `change_percent`,
`unit`, `market_status` (`open`, `closed`, `unknown`) and the same provenance/date/
status metadata as observations. Numeric fields are decimal strings or null;
change is measured against a verified previous trading close, with null changes
when that reference is unavailable. A closed market retains its real quote time.

### Observation, provenance and numeric conventions — ADR-08

M3's collector hands M4 a normalized batch with `run_id`, source identity,
`started_at`, `completed_at`, outcome (`updated`, `no_new_observation`, `partial`
or `failed`), validated observations and classified failures. Rejected raw records
never become public observations. Missing/failure events cannot overwrite a
previous valid value. Repeated runs must be idempotent, and verified revisions
must preserve the earlier observation's traceability.

The following logical fields are shared across collector, storage and API
adapters; M4 maps storage IDs into the public view rather than exposing raw tables.

| Field/group | Required meaning |
| --- | --- |
| `indicator_id`, `series_id`, `definition_id` | Stable identity plus the verified definition (geography, coverage, real/nominal basis, actual/estimate status as applicable) |
| `observation_period` | Canonical `id`, source-facing `label`, `type`, calendar/fiscal basis and verified `start`/`end` boundaries where known |
| `value` | Finite decimal string or `null`; raw collector arithmetic uses Decimal; API never silently rounds or sends NaN/infinity |
| `unit` | Explicit code such as `percent_yoy`, `percent_of_gdp`, `percent`, `percentage_points`, `inr_crore`, `usd_billion` or `index_points` |
| `as_of`, `as_of_kind`, `as_of_precision` | M3's observation date or explicitly identified reporting-period end; never the API request time |
| `published_at` | Source publication date/time at its known precision; otherwise `null`, without inventing a release timestamp |
| `retrieved_at` | UTC time of the successful source payload underlying the observation |
| `last_checked_at`, `last_success_at` | Latest collection attempt and latest successful check, including a valid no-new-release result |
| `sources` | Array of verified `{source_id, name, url, is_nse}` references; direct points normally have one, derived points preserve all input sources |
| `transform_id`, `input_observation_ids` | Versioned calculation and traceable inputs for derived observations; absent/null for direct observations |
| `revision_id`, `run_id` | Revision/correlation identifiers for reproducibility, without exposing raw secret-bearing payloads |
| `status`, `reason_code`, `stale_after`, `retention_allowed`, `limitations` | Availability/freshness state, safe reason, source-specific deadline, explicit permission to retain a display copy on transport failure, and interpretation limits |

Retrieval/run timestamps use RFC 3339 UTC with `Z`; dates use ISO calendar
notation. `as_of_precision` is `year`, `month`, `day` or `instant`, represented as
`YYYY`, `YYYY-MM`, `YYYY-MM-DD` or a UTC timestamp respectively. `as_of_kind` is
`observation` or `period_end`. An unknown date stays null; the verified reporting
period remains visible. Publication dates retain their actual precision.
Period types are `instant`, `day`, `month`, `quarter`, `year` and `fiscal_year`;
quarter/year labels never silently imply a fiscal calendar. Policy references
such as the RBI target also carry their source and known validity interval.

Valid observations require verified provenance and reporting-period metadata.
Missing points may contain null value/date/source fields with an explicit reason.
The UI displays missing numbers as `—`; a genuine zero remains zero. Decimal
strings preserve precision in storage/transport; the frontend converts validated
values to finite numbers only for chart geometry and applies unit-aware display
rounding. Financial calculations remain on the backend.

Comparisons require aligned definitions, units and periods; otherwise return
`comparison: null` plus `comparison_reason_code`. A comparison identifies its
reference series/period and kind (`previous_period`, `previous_year`,
`other_geography` or `policy_reference`). Subtracting percentage rates yields percentage
points, not percent growth. Relative change is `(current - previous) / previous *
100` only for a positive previous value; other denominators produce null with a
reason unless a separate verified transformation defines the calculation.
Trade balance is exports minus imports for matching coverage/currency/period.
GST averages declare their complete monthly window. Expenditure separates actuals,
provisional data, revised estimates and budget estimates. No interpolation,
forward-fill, mixed fiscal/calendar comparisons or Figma illustration figures
may masquerade as observed data.

ADR-08 chooses lossless decimal strings, explicit units and typed UTC/period
metadata over bare floating-point values and ambiguous date labels. M3/M4 own
normalization and final models; M2 adapts display types and M6 verifies the mapping.

### Response envelope, partial data and errors

Successful data-read responses contain `data` and `meta`. Login returns the
unwrapped token object defined below; `/auth/me` returns a minimal unwrapped
`{id, username}` profile. Metadata for data-read responses
includes `api_version: "v1"`, UTC `generated_at`, opaque `version` and `partial`.
Dashboard data contains `ticker` and `panels`, with panels keyed by the six
indicator IDs. Series, quotes and requested history ranges have independent
statuses. Keep independently valid series when another is missing; `partial`
signals missing/failed required content without hiding the valid parts.

Each panel's `series` is keyed by `series_id`. A series exposes `latest` as an
observation object (including `value: null` when unavailable), `comparison`, and
its chart `history` result. History results contain `points`, `status` and
`truncated`; the dedicated history route returns those results keyed by series.
Ticker data contains `items`. Catalog data contains an `indicators` list with
series definitions and available period/control options. M4 finalizes additional
model fields without silently changing these access paths or meanings.

`version` represents data, revisions, provenance and reported freshness/availability
changes. `generated_at` alone is not an observation update. Clients consume returned
freshness metadata on every poll, even when the economic value did not change.

| State | Meaning and HTTP/UI behavior |
| --- | --- |
| `fresh` | Valid observation and successful checks within that source's release-aware policy; its observation date may still be historical |
| `stale` | A valid observation is retained after a failed due refresh or exceeded freshness deadline; preserve its value/date and show the stale reason |
| `empty` | A successful, supported history query has no observations in the requested range; return an empty list and a useful message |
| `unavailable` | No usable observation exists, including unverified source, not-yet-collected or failed first fetch; value is null with a reason |
| `error` | Processing failed; panel-local failure may accompany independently valid panels, while a failed whole read returns a non-2xx error envelope |

Loading is client request state, not an invented observation status. Upstream
outage with a valid retained snapshot returns 200 plus stale metadata. No valid
snapshot returns honest unavailable fields; a database outage returns 503 instead
of pretend dashboard success. Successful no-new-release checks do not make annual
or monthly series stale solely because their observation date is old. M3 defines
the per-source calendar/deadline; there is no global 60-second freshness TTL.

Errors use this shape (illustrative structure, not an actual request result):

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request.",
    "details": [{"field": "query.limit", "message": "Unsupported limit."}]
  },
  "request_id": "<generated correlation ID>"
}
```

Use 401 `UNAUTHORIZED` with `WWW-Authenticate: Bearer` for absent/invalid/expired
identity; 403 `FORBIDDEN` for authenticated permission denial; 404 `NOT_FOUND` for
unknown resources; 422 `VALIDATION_ERROR` for invalid input; 429 `RATE_LIMITED`
with `Retry-After`; 503 `SERVICE_UNAVAILABLE` for unavailable local dependencies;
and 500 `INTERNAL_ERROR` for an unexpected failure. Details contain safe field
names/messages, never rejected password/token values, SQL, internal paths or stack
traces. M4 implements common handlers; M5 integrates auth failures with them.

### Authentication/session agreement — ADR-07

- Provision evaluator accounts privately; no public registration. M5 uses a
  maintained password-hashing implementation (Argon2id baseline), with M4-owned
  migration mechanics and password hashes instead of plaintext.
- Login accepts JSON `username` and `password`. Success returns `access_token`,
  `token_type: "bearer"`, integer `expires_in` seconds, UTC `expires_at`, and a
  minimal `user` (`id`, `username`). Responses/logs never echo the password.
- Choose HS256 with a server-held secret generated from at least 32 cryptographic
  random bytes. M5 validates an explicit algorithm allowlist, signature, required
  `sub`, `iat`, `exp`, `iss`, `aud`, and the active identity. Issuer is
  `economic-dash-api`; audience is `economic-dash-web`. Lifetime defaults to
  30 minutes via `ACCESS_TOKEN_EXPIRE_MINUTES`, with at most 30 seconds of server
  clock-skew allowance. Reject unsigned, wrong-algorithm and malformed tokens.
- The signing secret is supplied only through backend configuration (`JWT_SECRET`);
  issuer/audience are `JWT_ISSUER`/`JWT_AUDIENCE`. Names are reserved here; M5 adds
  their validated settings and safe examples. Never publish actual key material.
- React keeps the access token and protected responses in memory and sends
  `Authorization: Bearer <token>` over HTTPS. No tokens in URLs, local/session
  storage or cookies. There is no refresh-token flow; page reload requires sign-in.
- Expiry or any protected-request 401 stops polling, aborts pending requests,
  clears token/protected data and returns to sign-in. Do not replay passwords or
  silently retry unauthorized requests. Logout performs the same local cleanup.
- Stateless logout does not revoke a previously issued token server-side; it
  remains usable until expiry unless its account is disabled or the key rotates.
  Immediate per-token revocation is outside this initial policy.
- M5 expands CORS to GET/POST/OPTIONS and `Authorization`/`Content-Type`, exposes
  `Retry-After` if used by the client, and keeps `allow_credentials=false` with
  fetch credentials omitted. Production permits only the actual HTTPS frontend
  origin. No-token preflights are handled without bypassing route authentication.

JWT claim/validation basis: [RFC 7519](https://www.rfc-editor.org/rfc/rfc7519)
and [JWT best current practices](https://www.rfc-editor.org/rfc/rfc8725).
These are application policy choices to implement/test in M5, not claims that
authentication already exists in the current scaffold.

ADR-07 chooses short-lived memory bearer tokens over persistent cookie/refresh
sessions to simplify separate-site authentication. Reload requires re-login and
logout does not provide immediate token revocation. M5/M6 verify guards, expiry,
cleanup and cross-origin behavior.

### Refresh, cache and consumer handoff

Use the ADR-06 60-second visible/signed-in polling policy. Start with an immediate
dashboard fetch, allow only one in-flight poll with a 15-second timeout, pause
hidden tabs, refresh on return and back off network/5xx failures to a maximum of
five minutes; honor
delta-seconds `Retry-After` on 429 even when it exceeds that cap. Stop at expiry/401;
other non-retryable 4xx failures are surfaced rather than repeatedly retried.
A transport failure keeps only the current session's previously validated data
with backend `retention_allowed: true` (absent means false), visibly marks it
stale/disconnected
and preserves original source dates; first-load failure shows an error with no
invented figures. Recovery replaces it only with a validated API response.

M4 serves stored/validated snapshots and may cache them server-side. Browser
polling never triggers source HTTP acquisition. Auth/token/data responses use
`Cache-Control: no-store`; initial polling uses full responses and `version`
metadata rather than ETag/304. No authenticated payload enters a shared public
CDN cache or persistent browser storage.
[Cache-Control semantics](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cache-Control).

Contract review against the M2–M5 planners:

| Consumer | Agreed boundary and later verification |
| --- | --- |
| M2 | Typed adapter, independent series states, decimal/unit/date formatting, real control options and source/as-of labels; verify with its Figma audit |
| M3 | Validated records, provenance, period definitions, transformation references and release-aware run/failure metadata; verify against actual source samples |
| M4 | Transactional ingest, stable read/error envelopes, revision/freshness versions and public health; implement final models and route tests |
| M5 | Login/JWT/session contract, common guards, production docs policy, safe errors, exact-origin CORS and private evaluator provisioning; run negative auth tests |

This review establishes interface agreement by the execution agent across the
module planners. Source availability, exact Figma-derived catalog additions and
live security/behavior remain explicitly unverified until their owning modules
produce evidence. OpenAPI/consumer tests must confirm the final implementation;
do not treat the conceptual examples above as working endpoints or real figures.

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

These routes describe the current scaffold. The M1.5 route/access table above is
the target contract; its protected endpoints and production docs policy are not
implemented yet.

- `GET /`: public bootstrap response, `{"message":"Economic Indicators API"}`.
- `GET /docs`: generated interactive API documentation.
- `GET /openapi.json`: generated OpenAPI schema.

The bootstrap response is not a health contract or authentic indicator data.
M4 owns the final health and dashboard routes; M5 owns authentication.

## Verification and dependency updates

### Local scaffold smoke check — M1.6

Start the API and frontend in separate terminals using the commands above. Run
this PowerShell check from any directory; it throws if a required check fails:

```powershell
$apiOrigin = 'http://127.0.0.1:8000'
$webOrigin = 'http://127.0.0.1:5173'
$apiResponse = Invoke-WebRequest -Uri "$apiOrigin/" -Headers @{ Origin = $webOrigin } -UseBasicParsing -TimeoutSec 15
$webResponse = Invoke-WebRequest -Uri "$webOrigin/" -UseBasicParsing -TimeoutSec 15
if ($apiResponse.StatusCode -ne 200 -or ($apiResponse.Content | ConvertFrom-Json).message -ne 'Economic Indicators API') { throw 'API bootstrap failed' }
if ($apiResponse.Headers['Access-Control-Allow-Origin'] -ne $webOrigin) { throw 'Frontend origin was not allowed' }
if ($webResponse.StatusCode -ne 200 -or -not $webResponse.Content.Contains('/src/main.tsx')) { throw 'Vite entrypoint failed' }
'PASS: API bootstrap, frontend entrypoint and allowed origin'
```

Open the frontend URL in a browser and confirm the title and “The dashboard is
coming soon.” ready state. This also checks that browser JavaScript can reach the
API configured by `VITE_API_BASE_URL`. The HTTP checks passed on 2026-10-15;
the rendered ready state and configuration-only API URL change were verified in
M1.3 with the same application code. The root bootstrap route remains the smoke
endpoint until M4 implements `/health`.

### First authentic indicator handoff — M1.6

The queued slice is **world annual GDP growth**: indicator `gdp_growth`, series
`gdp_growth_world`, unit `percent_yoy`. It establishes one real observation's path
through collection, persistence, API and UI before extending the remaining series.
It does not complete the GDP panel's India series or comparisons.

The reachable source candidate is World Bank World Development Indicators,
indicator `NY.GDP.MKTP.KD.ZG`, geography `WLD`:

- [Indicator definition and attribution](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG).
- [Bounded observation request](https://api.worldbank.org/v2/country/WLD/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=5).
- [Indicator metadata request](https://api.worldbank.org/v2/indicator/NY.GDP.MKTP.KD.ZG?format=json).

Both API requests returned HTTP 200 in the local feasibility probe on 2026-10-15.
The sample contains five non-null observations with year labels 2021–2025;
metadata identifies annual growth based on constant-price GDP. Responses were
saved in the private implementation evidence folder, outside Git. No sample
values have been embedded in the application, ingested or served by FastAPI.

**Source-lock gate, owned by M3:** audit the required series against
[NSE's macro publications](https://www.nseindia.com/static/research/publications-reports-nse-market-insights)
and the M2 design definition before selecting the final source. A reachable World
Bank endpoint does not establish that NSE lacks suitable data. M3 must record
coverage, semantic compatibility, extraction feasibility, attribution and the
fallback reason. If this candidate fails that gate, M3 selects another authentic
first series and updates this handoff explicitly. Hosted-source access remains
an M3/M7 check.

| Hop | Owner | Required output and acceptance |
| --- | --- | --- |
| Source → validated batch | M3 | Lock the source and definition; validate series/geography, annual period basis, finite decimal values and nulls; retain source URLs, source-year precision and retrieval time. Use bounded requests, timeouts, rate handling and the agreed single scheduler. |
| Batch → private persistence | M4, consuming M3's batch | Store validated observations and run/provenance metadata with parameterized SQL; repeated runs are idempotent, revisions are traceable and failed refreshes preserve valid rows. Verify a stored observation survives restart. |
| Persistence → protected API | M4 with M5 | Read stored data through `/api/v1/dashboard` and `/api/v1/indicators/gdp_growth`; expose `gdp_growth_world` using the M1.5 envelope, metadata and state rules. M5 applies bearer authentication; unauthorized access returns 401. A dashboard request never triggers upstream collection. |
| API → GDP panel | M2 with M5 | Render the world series using its year, unit, source and status; format only for display. Show null as `—`, preserve real zero, distinguish loading/failure/stale states and follow the authenticated polling contract. |
| Integrated proof | M6; hosted checks with M7 | Trace one displayed observation back through API and database to its source; verify dates/units, protected access, refresh failures and restart persistence. |

M3 must preserve the supplied year label without inventing a day or timestamp;
confirm the calendar basis before locking the definition. The API's dataset-level
`lastupdated` is not an observation's publication date. Keep `published_at` null
unless independently verified, and record retrieval/check times separately.
Parse numeric source tokens without precision loss and round only in the UI.

Required integrated failure checks, to be implemented by the named owners:

- Timeout, rate limit or malformed source data: M3 records the failure; M4 keeps
  the last valid observation and reports stale status/reason. With no valid stored
  observation, return null/unavailable rather than zero.
- Successful check with no new release: apply M3's documented annual release and
  freshness policy; the 60-second browser polling interval is not a source TTL.
- Partial batch: valid series remain usable and failed series carry their own
  state. M2 may retain previous data only when the API permits retention.
- API/database outage or expired login: M4/M5 return the agreed safe error;
  M2 handles unavailable data or clears the session as the contract requires.

The scaffold smoke check is verified. The real-data pipeline and these integrated
failure checks are queued work for M2–M6; this handoff does not claim them complete.

### Build, configuration tests and dependency updates

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
