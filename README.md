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

M1.7 records the architecture handoff and change policy below. The shared baseline
is frozen for implementation; overall M1 acceptance remains conditional on the
open design/source gates. Hosting decisions have feasibility evidence, with live
verification assigned to M7.

M2.1 adds a provisional PNG-derived UI audit below. M2.2 implements the styled
header, unavailable-data ticker and six-panel shell, with a repeatable browser
layout check. Exact Figma properties and interaction states remain unverified.

M2.3 adds shared display/metadata/state components, SVG chart foundations and a
development-only synthetic preview. The dashboard now uses shared unavailable
states and source/date footers.

M2.4 implements the six specialized panels, their summaries, original SVG icon
substitutes and populated development previews. Production panels show missing
values until validated data is connected. Exact design/source definitions remain
open as described below.

M2.5 adds the typed market ticker, quote details, keyboard scrolling and explicit
availability/cadence states. Its development preview exercises synthetic quotes;
production still has no market feed. The interaction choices are documented below.

M2.6 adds response validation, the dashboard adapter, per-observation retention
rules and a synthetic API-state preview. Additional wire fields are a documented
M4 handoff proposal. Production still uses the bootstrap connection check until
the authenticated dashboard endpoint is implemented and integrated.

Authentic observations, database storage, authentication,
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
outstanding. Charting uses the custom SVG foundation documented below.

## Repository and local materials

```text
economic-dash/
  frontend/
    src/
      App.tsx          Dashboard shell and bootstrap connection state
      api.ts           Bootstrap API connection check
      config.ts        Public API URL configuration
      dashboard-panels.ts  Stable panel IDs/titles; no observations
      components/      DashboardLayout, DashboardHeader, MarketTicker, PanelShell
      data/            Draft response validation, dashboard adapter/client/state
        ui/            Values, comparisons, periods, states and source/as-of footer
        charts/        SVG chart frame, point tooltips and legend
        panels/        Six specialized panels, plots and original SVG icons
      ui/              Presentation types, ticker model, formatting, plot geometry
      preview/         Development-only primitives/panel/ticker/API-state previews
      main.tsx         Browser entrypoint
      tokens.css       Shared provisional visual tokens
      styles.css       Shell, grid, surfaces and responsive layout
      primitives.css   Shared UI/chart styling and developer preview layout
      panels.css       Specialized panel layouts, marks and responsive icons
    scripts/
      verify-layout.mjs  Isolated Chromium viewport/screenshot checks
      test-ui.mjs        Formatting and component tests using Node/Vite
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

## Tooling and repository decisions — ADR-01/02

**ADR-01 — tooling.** Use React with TypeScript, Vite and npm, plus Python,
FastAPI and uv-managed pinned requirements. React/FastAPI are assignment
requirements; TypeScript provides checked frontend contracts and Vite supplies
the existing development/build workflow. Plain JavaScript and a larger frontend
framework were alternatives; another Python package manager was also possible.
The selected stack keeps the current application small and reproducible.
Runtime pins and installation commands are below. M1.3 verified fresh installs,
builds, configuration tests and independent service startup; M7 must reproduce
the build on its hosts. M2 owns later chart-library selection; M3–M5 own justified
backend dependencies and their pinned updates.

**ADR-02 — repository.** Use one repository with distinct `frontend/` and
`backend/` trees, explicit ownership, `.editorconfig`, reviewed environment
templates and generated/secret files ignored. Separate repositories and a
repository `docs/` tree were alternatives. The monorepo coordinates interface
changes; the user explicitly chose root README documentation and private planning
and implementation logs outside Git. This supersedes the planners' proposed
`docs/` layout. M1.2 and its documentation-layout checkpoint verified the tracked
tree and ignore rules. Each module updates its README contract/setup details and
the private log; M7 owns final delivery documentation.

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

## Architecture freeze and module handoff — M1.7

This review uses the assignment, master/module planners and M1.2–M1.6 evidence.
It freezes the **interface baseline**, not unfinished functionality. The execution
agent reviewed the module boundaries; no separate module sign-offs, deployed
security results or completed authentic-data pipeline are claimed.

### ADR status register

| Decision | Baseline and owner | Evidence/status at handoff |
| --- | --- | --- |
| ADR-01 | TypeScript/Vite/npm; Python/FastAPI/uv — M1, then module maintainers | Implemented and locally verified in M1.3; hosted build pending M7 |
| ADR-02 | Monorepo, frontend/backend boundaries, README plus external private logs — M1/all modules | Implemented and checkpointed in M1.2; user documentation override recorded |
| ADR-03 | Backend-private SQLite on persistent API disk — M4/M7 | Design selected; live persistence/isolation pending |
| ADR-04 | Separate Vercel/Render HTTPS deployments — M7 | Feasibility baseline; funding/account/host verification pending |
| ADR-05 | One lifespan-owned collector, one instance/worker — M3/M7 | Design selected; scheduler/restart evidence pending |
| ADR-06 | Authenticated visible-tab polling every 60 seconds — M4/M6, session integration M5 | Interface selected; client/API integration tests pending |
| ADR-07 | Protected data routes, memory bearer session, public login/health — M5 | Interface selected; authentication and negative tests pending |
| ADR-08 | Versioned envelopes, decimal strings, provenance/period/state semantics — M3/M4/M2 | Interface selected; executable models and consumer tests pending |

### M1 acceptance evidence

| Planner condition | Review result and evidence |
| --- | --- |
| Requirements owned; design access explicit | Assignment rechecked; module ownership below covers all obligations. User can access Figma and supplied a PNG; exact agent measurements/interactions remain open under R1. |
| React starts after clean install | Verified M1.3: `npm ci`, production build and browser ready state. |
| FastAPI starts after clean install; smoke route works | Verified M1.3 pinned install and service startup; M1.6 root smoke check passed. Final `/health` belongs to M4. |
| API URL configurable | Verified M1.3 alternate environment-only build; no source edit needed. |
| Restrictive CORS principle | M1.3 configuration tests and M1.6 allowed-origin check; actual production-origin test pending M5/M7. |
| Known environment names and safe templates | Current variable table and `.env.example` files reviewed in M1.3; future JWT/database settings added by their owners when implemented. No real credentials are required for the scaffold. |
| Separate HTTPS hosting viable | M1.4 provider feasibility and configuration recorded; live checks pending M7. |
| Private DB and persistence semantics understood | ADR-03 specifies backend-only disk storage; M4/M5/M7 must prove isolation and restart/redeploy persistence. |
| Server-side scheduler supported | ADR-05 has a feasible single-process design; M3/M7 must demonstrate actual scheduled runs. |
| Update delivery/cadence assigned | ADR-06 defines polling independently of M3 collection; M4/M6 implement and verify transport behavior. |
| Source/date/unit/error/stale contracts written | M1.5 specifies metadata, null versus zero, retention and failure rules. |
| First authentic slice has explicit handoffs | M1.6 queues `gdp_growth_world` through M3 → M4 → M2, with M5/M6/M7 integration roles; source lock remains R2. |
| ADRs and risks reviewed | ADR-01–08 registered here; unresolved dependencies have owners and resolution paths below. |

The M1.7 review artifact is complete. **Overall M1 is not yet fully verified or
locked:** precise design extraction and first-source approval remain open. Live
deployment checks are deliberately later-module evidence, not local test results.

### Open gates and resolution paths

| ID | Dependency/risk and effect | Owner and resolution/escalation |
| --- | --- | --- |
| R1 | Exact Figma tokens, control behavior and ambiguous labels are unverified by the agent. | M2 starts its design audit using the user-provided PNG as authorized reference; obtain Figma measurements/annotations or focused user clarification for unknowns. Record provisional choices; do not claim final visual parity until M2/M6 verify them. |
| R2 | World GDP candidate is reachable but NSE coverage, semantic match and annual period definition are not locked. | M3 audits NSE and the candidate before ingestion; records a justified fallback or selects another real first series. M2/M4 receive catalog/definition changes explicitly. No fabricated substitute observations. |
| R3 | Paid backend/disk budget, provider accounts and frontend-plan eligibility remain unconfirmed. | M7 checks current plans and account access before provisioning; obtain the user's spending approval then. If unsuitable, revise ADR-03/04/05 together before deploying storage or scheduler. |
| R4 | Upstream endpoints may reject cloud-host requests. | M3/M7 probe actual endpoints from the selected API host early; document failures and evaluate another compliant source/host. Local HTTP success does not resolve this gate. |
| R5 | Hosted runtime compatibility, DB isolation/persistence and single scheduler ownership are unproven. | M4/M5/M7 run the deployment checklist; M3 verifies scheduler recovery/overlap. Failed persistence or privacy checks block production acceptance and require a topology correction. |
| R6 | Illustrated planner payloads, source semantics or future model choices could diverge across modules. | M2–M5 use the M1.5 baseline; resolve discrepancies through the change policy below before dependent code proceeds. M6 checks actual API/consumer compatibility. |

### Implementation queue and directory ownership

These are sequential workstreams in this collaboration, with dependency ordering;
the table does not claim that other agents or deployments have been started.

| Module | Safe starting work and handoff required before completion |
| --- | --- |
| M2 — `frontend/src/` | Begin design audit/component map; resolve R1 and give M3/M4 the actual series/control definitions. UI fixtures remain clearly marked and outside production observations. |
| M3 — future backend collector modules | Begin source register and R2 audit; pass validated records/run events to M4 using M1.5. Confirm source-specific refresh rules and R4 before hosted collection. |
| M4 — `backend/app/`, migrations and backend tests | Implement private schema/ingest/read/health boundaries; finalize models with M3 and consumers with M2. Wire M5 guards before protected data is made available to evaluators. |
| M5 — backend auth plus frontend session UI | Implement the agreed token/session contract with M4 identity persistence, route guards and safe evaluator provisioning. M4 owns common error handlers and migration mechanics. |
| M6 — frontend/backend integration and QA | Bind the authenticated API adapter/polling to M2 views and verify the first slice, all states, controls, fidelity, accessibility and performance. Reuse the scaffold smoke commands. |
| M7 — deployment configuration and README | Investigate R3/R4 early; provision only with required account/budget authorization. Verify separate HTTPS sites, strict CORS, health, private durable storage and evaluator access. |

M7 also owns the submission repository/schema/README, live URLs, assumptions and
fallback-source list, private evaluation instructions, portfolio/flagship project
links with role/technology summaries, and the post-assessment demonstration and
AI-use explanation. Those assignment obligations remain pending.

### Change policy

The baseline is identified as **`m1-baseline-1`**, carried by the M1.7 Git
checkpoint once committed. `/api/v1` remains the API namespace; this baseline ID
is a documentation revision, not another route prefix or a Git tag.

For a changed route, required field/type, numeric/date meaning, auth rule or
topology assumption: record the reason and affected ADR/contract in README;
name the producer and consumers; update their implementation/verification and
private log together. Additive optional fields can remain in v1. Breaking changes
require an explicit coordinated contract revision or a new API version. An
unresolved conflict pauses only its dependent work; unaffected tasks may proceed.
Internal filenames/classes remain each module's choice within the directory map.

## UI specification — M2.1 provisional PNG audit

The supplied `Economic Indicator 1.png` was inspected at its original **4992 ×
8772** raster size. The user authorized this reference for implementation planning.
The [Figma frame](https://www.figma.com/design/brsbeMh0t7dB6ibf3cJN4D/Economic-Indicator-Assignment?node-id=1-2)
could not be opened through the available web tool in this audit; no callable
Figma integration was available. Frame-specific dimensions, layers, font names,
assets and interactive states are therefore not verified. This completes the
provisional raster specification; M2.1's exact-Figma acceptance gate remains open.

### Screen inventory and component map

`DashboardPage` contains `DashboardHeader`, `MarketTicker` and a two-column,
three-row `IndicatorGrid`. Each specialized panel uses a shared `PanelShell`,
two `SummaryCard` regions, its own chart, legends where shown, and a required
`SourceAsOf`/availability region. These names describe the M2.1 component plan;
M2.2 implements the header/ticker/panel shell, with `App` as the page and CSS Grid
as the grid. Summary, chart and metadata primitives remain pending.
Common axis, annotation, value/change and state primitives belong to M2.3;
its implementation and custom-SVG choice are recorded below. Final icons and
font fidelity remain subject to U1 and the panel implementation.

The header reads **ECONOMIC INDICATOR**, with red/blue candlestick decoration on
a dark background. The full-width navy ticker has a red `LIVE` badge, separators,
instrument/value/change groups and a repeated/clipped sequence. Visible instrument
labels include `SENSEX`, `NIFTY BANK` and `NIFTY IT`; M3 must verify their identities,
providers and timestamps. The PNG does not establish a complete instrument list,
animation behavior or tick-level refresh. No navigation, sign-in form, tabs or
period-selector buttons are visible in this export; M5 supplies sign-in separately.

| Position / API indicator | Visible heading and summary labels | Chart and annotations visible in the PNG |
| --- | --- | --- |
| Top left / `gdp_growth` | `GDP Growth - India vs World (YOY%)`; `India`, `World` | Grouped vertical bars; cyan India/orange World legend; value labels above bars; years 2021–2025; 0–10% axis in 2-point steps. |
| Top right / `debt_to_gdp` | `Debt to GDP Ratio (IND)`; `India (FY25)`, `Ind vs US` | Cyan line with area fill and rounded value callouts; 50–100% axis in 10-point steps; ticks `25 Jul`, `1 Aug`, `8 Aug`, `15 Aug`, `22 Aug`. Comparison and dates require U2 below. |
| Middle left / `trade` | `Imports, Exports & Trade Balance`; `Exports`, `Imports` | Cyan Imports/orange Exports grouped bars plus green Trade Balance line/markers; bar labels and line callouts; 2021–2025, percentage axis as illustrated, subject to U3. |
| Middle right / `gst_collection` | `GST Tax Collection (YOY%)`; `GST Collections`, `Monthly Average` | Cyan columns and yellow line/markers; bar labels and line callouts; 2021–2025, percentage axis. Legend literally says `Imports` and `Trade Balance`; resolve U4. |
| Bottom left / `inflation_india` | `Inflation (IND)`; `Inflation Rate`, `RBI Target` | Line/area plot with brighter middle and muted outer segments, a value callout and a thin low horizontal cyan rule; 2021–2025 and percentage ticks. Target-line interpretation remains U5. |
| Bottom right / `government_expenditure` | `Government Expenditure`; `Total Expenditure`, `Capital Expenditure` | Stacked columns; orange Capital Expenditure below blue Revenue Expenditure; segment and total labels; 2021–2025, percentage axis subject to U6. |

All twelve summaries have a prominent value and a comparison strip; flags/globe
appear in the top row and illustrated finance/trade icons in the other rows.
Panels have dark gradients, thin borders, rounded corners, a reflective upper-left
detail and a separated heading band. Charts use fine gray grids and light labels.
The export has a large dark decorative area below the six panels and no visible
source/as-of footer. The assignment still requires source/date/non-NSE/status
information; M2.2–M2.6 must allocate it without clipping the chart or inventing dates.

### Measurement sheet

Measurements below are **approximate raster-derived CSS sizes at 1214px width**,
not extracted Figma properties. Uniform scale is `1214 / 4992`; the image then
occupies about **2133.25px** in height, leaving **25.75px** within the 2159px
evaluation viewport. Do not stretch the raster vertically to conceal this mismatch.

| Region/property | Initial measurement for M2.2 |
| --- | --- |
| Header / ticker bands | Approximately 84px / 47px high; ticker spans the viewport. |
| Grid | Left inset about 29px; right inset about 28px; columns about 566–567px with a 23px gap. |
| Panel rows | Tops near 158px, 710px and 1263px; height about 529px; vertical gap about 23px; last panel ends near 1792px. |
| Panel heading / summary cards | Heading band about 66px; each summary about 247 × 109px; individual plot bounds saved in private audit evidence. |
| Corners / icons | Estimated panel radius 16px and summary radius 12px; flag/globe diameter around 44px, illustrated icons roughly 72–88px. Exact vector/asset bounds unknown. |
| Typography | Estimated title 36px, panel heading 20px, summary label 18px, primary value 34px, chart ticks 14–16px. Family, weights, line heights and metrics remain unknown. |
| Sampled surfaces | Page `#0A0A0A`; ticker `#05102A`; heading `#1E1F27`; body sample `#060A1D`; summary sample `#0B283B`; grid sample `#5B5B5B`. |
| Sampled accents | White `#FFFFFF`, cyan `#0FCBFF`, positive `#45FF5B`, ticker positive `#69F6B8`, red `#D62D2A`, yellow `#F4E15C`, green `#22D700`, orange `#E99E10`. Gradients are not single flat tokens. |

The private M2 evidence contains the source hash, source-pixel panel/plot bounds,
palette samples and a **1214 × 2159 annotated PNG layout guide**. Green outlines
mark panels and magenta outlines estimated plot regions. The guide is a scaled
reference with annotations, not a browser capture or a visual-fidelity test result.

### Visible controls and proposed behavior

| Surface | Observed evidence / implementation rule |
| --- | --- |
| `LIVE` badge | Status-like appearance only; no click/toggle behavior established. M2/M3 must label actual freshness and cadence honestly. |
| Ticker overflow/repetition | Movement cannot be inferred from one PNG. M2.5 records its motion choice and accessible reduced-motion behavior; every item remains readable. |
| Legends | Colored keys/text are visible; no selected/disabled state is shown. Initially presentational; add series toggling only with an explicitly documented decision. |
| Chart callouts | Static rounded labels are visible; hover/focus behavior is unknown. M2.3/M2.5 may add accessible point inspection, recording it as an implementation choice. |
| Years, day/month ticks and `FY25` | These are labels in the export, not demonstrated selectors. M2/M3 use verified catalog periods and record any actual control requirement. |
| Summary icons / header | No action is evidenced. Treat as decorative/informational unless Figma clarifies behavior. |

### Uncertainties and data handoff

| ID | Unresolved detail | Owner and required resolution |
| --- | --- | --- |
| U1 | Exact font, spacing, gradients, texture, icons, asset rights and interaction states | M2: obtain properties/assets where available; otherwise record a provisional substitute before implementation. Confirm Figma disagreements before claiming parity. |
| U2 | Debt's `Ind vs US` summary, FY label and day/month trend conflict with an annual debt ratio interpretation | M2/M3: verify comparator, denominator, period and chart meaning; M4 exposes only the approved definition/catalog. |
| U3 | Trade summaries use a dollar/B display while chart ticks use percentages | M3/M4: establish monetary level versus growth series, currency, coverage and period; M2 labels each axis with that verified unit. |
| U4 | GST legend names trade metrics and its monthly average lacks a unit | M2/M3: confirm intended series/legend and receipt/growth/average definitions; no trade labels silently mapped to GST data. |
| U5 | RBI target summary and the low horizontal rule do not establish one coherent target scale | M2/M3: verify policy value/validity and whether that rule is a target; label the actual reference accurately. |
| U6 | Expenditure percentage summaries/axis and stacked labels do not establish amounts, shares or growth; shown totals are not reliable arithmetic | M3/M4: verify budget coverage, actual/estimate status, units and revenue/capital/total relationship before binding data. |
| U7 | Repeated annotations, example years, green upward arrows alongside negative changes and line/bar heights are not reliable observations | M2/M3/M4: calculate display values, sign/direction, labels and geometry from validated observations. Record any visual deviation needed for truthful semantics. |
| U8 | Source/date/state UI is absent from the PNG | M2/M4: add compact truthful metadata/state treatment and test it at the target viewport; M6 verifies visibility and overflow. |

No illustrated economic value is a source-backed observation. Keep any later
fixture previews explicitly labeled and outside the production data path. Existing
M1.5 IDs/contracts remain unchanged; unresolved comparisons/series additions require
an approved catalog definition. A missing definition/value remains unavailable/`—`.
M2.2 can start the provisional structural shell from this specification; final
visual acceptance waits for the design audit's open items and M2/M6 comparison.

## Dashboard shell — M2.2

The shell follows the provisional PNG geometry: two columns at the evaluation
width, six 529px panels in the audited order, 23px gaps, and 84px/47px header/ticker
bands. At widths of 800px or less it reflows to one column. The ticker has its own
keyboard-focusable horizontal scroller on narrow screens; it does not widen the
page. No ticker animation is introduced at this checkpoint.

- **UI-ADR-02:** plain CSS, semantic custom properties in `src/tokens.css`, CSS Grid
  and a reusable `PanelShell` keep the measured layout consistent without a styling
  dependency. `src/styles.css` owns surfaces, responsive rules and focus treatment.
- **UI-ADR-03, provisional:** use local Arial/Helvetica/sans-serif fallbacks;
  no font download or external image is required. CSS gradients and original
  decorative SVG candle shapes approximate the reference. These are documented
  substitutes; the actual Figma font/assets remain U1.
- **UI-ADR-04, provisional:** preserve the target two-column geometry and use an
  800px single-column breakpoint. Panels have minimum heights, allowing later
  content to expand rather than being hidden behind a fixed-height clip.

At M2.2 the two summary regions were decorative reservations; M2.4 replaces them
with labeled summary cards. Each panel has
a truthful unavailable/loading/error message. The ticker uses `NO DATA` with `—`
quotes; it does not claim a live feed. Bootstrap connectivity is still checked
through the configured API URL. M2.3 adds the shared source/date footer and state
components; charts, authenticated observations and final ticker behavior remain
later work.

### Repeatable viewport check

With the frontend running, from `frontend/`:

```powershell
npm run verify:layout
```

The Node script launches an isolated headless Chrome/Edge profile, captures PNGs
and writes `layout-report.json` under ignored
`frontend/node_modules/.cache/layout-check/results/`. It checks **1214 × 2159**,
**390 × 844**, **320 × 740**, plus target-size API-request failure. Assertions cover
panel count/order, approximate PNG-derived target bounds (4px tolerance), heading
clipping, document overflow against usable width, single-column reflow, browser
exceptions and initial layout-shift score below 0.01. The failure case blocks
observed API fetch URLs in that isolated browser and requires the error state.
This is a shell/layout check, not indicator-data or final visual-parity validation.

Options: `--url <frontend URL>`, `--output <evidence directory>`, and
`--browser <Chrome/Edge executable>`; `CHROME_PATH` can also select the browser.
It does not install a browser or start/stop application servers. Profiles remain
in the ignored cache; your normal browser profile is never used.

M2.2 verification passed all four cases, with zero horizontal overflow and no
clipped headings/panels or uncaught page exceptions. Target panel tops were
158px, 710px and 1262px; the final row ended at 1791px. Production build/type-check
passed. Screenshots/report are in the private implementation evidence folder.
Exact Figma matching remains open; this checkpoint verifies the provisional shell.

Driver references: [Chrome viewport emulation](https://chromedevtools.github.io/devtools-protocol/tot/Emulation/#method-setDeviceMetricsOverride)
and [screenshot capture](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot).

## Shared primitives and chart foundation — M2.3

| Component/helper | Responsibility |
| --- | --- |
| `SummaryValue`, `ComparisonChange` | Reusable value cards and signed changes; real zero remains zero and missing/invalid values render `—`. Change direction follows the supplied sign, without computing financial comparisons. |
| `PeriodLabel` | Displays the supplied label and optional fiscal/calendar basis without deriving boundaries. |
| `SourceAsOf` | Lists sources, marks non-NSE attribution and displays observation/period-end dates at their supplied precision; unknown provenance remains explicit. Links accept HTTP(S) without embedded credentials. |
| `StateMessage` | Separate loading, fresh, stale, empty, error and unavailable messages; announcements are opt-in to avoid six simultaneous alerts. |
| `ChartFrame`, `Legend` | SVG axes, supplied scales/ticks, reference lines, legends, inspectable points and an accessible data table. |
| `ui/format.ts`, `ui/chart-geometry.ts` | Shared display/date validation and finite chart geometry, including missing-point path breaks. |

**UI-ADR-01:** use composable custom SVG for the chart foundation. The reference
requires several distinct bar/line/area combinations; shared axes, scales and
inspection can support those without another package. A charting library remains
an alternative if later panel fidelity/interaction needs justify it. M2 owns the
custom rendering/accessibility work; M2.4 constructs the six specialized plots and
M2.7/M6 verify their final behavior and fidelity.

**UI-ADR-06, display policy:** callers explicitly provide audited units and display
precision (0–6 decimal places). Plain signed decimal strings are formatted using
BigInt arithmetic with half-away-from-zero display rounding; values above Number's
safe integer range remain accurate. Currency grouping uses `en-IN` for INR crore
and `en-US` otherwise. Rates use `%`, differences use `pp`, and currency amounts
retain their currency/scale label. Unsupported representations, including raw
scientific notation, stay missing; the later adapter must normalize them if needed.
The presentation inputs are not a replacement for M4's final API models.

Year/month/day dates retain that precision. UTC instants display their actual
date/time in UTC; invalid calendar dates and offset/non-UTC instant strings are
rejected. Unknown dates never fall back to retrieval time or today. Comparison
arrows/colors communicate numeric increase/decrease, not economic desirability;
backend calculations and compatible comparison definitions remain M3/M4 work.

Chart domains, ticks, labels and reference values are explicit caller inputs.
Only chart geometry converts valid decimal strings to finite numbers; overflow,
underflow and out-of-domain points are not plotted as zero; unplottable non-null
values have a visible note. Nulls split line
paths instead of being bridged. Invalid/missing reference lines have a visible
unavailable note. Tooltips respond to pointer hover and point focus; Escape
dismisses them. Axis abbreviations retain full labels in SVG titles, and the
screen-reader table provides the point values, including missing observations.

### Preview and verification

With Vite running, open **`http://127.0.0.1:5173/__ui-preview`**. This page clearly
labels every example as synthetic; it covers positive/negative/zero/null values,
large amounts, long labels, precision-aware dates, source metadata, all states,
and a sample chart with a gap, real zero and a reference line. Its dynamic import
is guarded by `import.meta.env.DEV`; the production build excludes its fixture
module and example values. The production dashboard still has no observations.

From `frontend/`:

```powershell
npm run test:ui
npm run verify:primitives
npm run verify:layout
```

The initial 12 Node/Vite tests verify decimal rounding/precision, missing versus zero,
units, signs, valid/invalid dates, safe source links, period/state semantics,
finite geometry, path gaps and chart reference/data alternatives. Browser preview
checks cover 1214 × 2159, 390 × 844 and 320 × 740, including long-label overflow,
SVG bounds, tooltip hover, focus on the zero-value point and Escape dismissal.
Use the same browser/output/URL options as the layout check; preview artifacts
default to `node_modules/.cache/layout-check/primitives/`.

At the M2.3 checkpoint, those 12 tests, three preview cases, four dashboard
layout/failure cases and the production build passed. Production JS was checked for absent synthetic fixture
markers/values. Private screenshots/reports are recorded in the implementation
log. M2.4 extends this foundation below; actual API adaptation, source definitions, authentication
and exact Figma parity remain with their owning tasks.

Test tooling references: [Node test runner](https://nodejs.org/api/test.html) and
[Vite module loading](https://vite.dev/guide/ssr.html#setting-up-the-dev-server).

## Six specialized indicator panels — M2.4

`components/panels/IndicatorPanels.tsx` exports individually testable `GdpPanel`,
`DebtPanel`, `TradePanel`, `GstPanel`, `InflationPanel` and `ExpenditurePanel`.
They share `PanelShell`, summary/metadata/state primitives and `DashboardLayout`;
each selects its own plot composition, icons, captions and series treatment.
`ui/panel-models.ts` defines frontend presentation inputs for the later API adapter.
It does not introduce backend routes or change the M1 API contract.

| Panel | Implemented presentation |
| --- | --- |
| GDP | India/World summaries with flag/globe artwork; grouped cyan/orange bars and value labels. |
| Debt/GDP | Country/comparison summaries; cyan line and area fill, percentage-of-GDP scale and rounded callouts. |
| Trade | Export/import summaries and original ship/arrow icons; two monetary bar series plus a green balance line, including negative balances. |
| GST | Collection/average summary slots with receipt/calendar artwork; cyan columns plus yellow comparison line. Final receipt/growth definitions remain U4. |
| Inflation | Inflation/target summaries; CPI line/area, callouts and a labeled reference line only when supplied. No production target value is assumed. |
| Expenditure | Total/capital summaries; orange capital and blue revenue stacks, segment labels and separately supplied total annotations. |

Grouped bars use category bands; negative bars use a true zero baseline. Area
fills split at missing periods. A stack with an unknown segment is not drawn as
complete, while its supplied values remain in the data alternative. Stack
addition is used solely for SVG coordinates; exact segment/total labels and
comparison values come from the input model, never from chart arithmetic.
Bars and point marks support hover/focus tooltips and Escape dismissal.

`PanelIcon` contains original SVG substitutes for the reference illustrations.
Circular country/globe symbols and finance/trade artwork occupy the audited
summary regions; narrow layouts put financial artwork in normal flow to avoid
covering values. The supplied raster remains a visual reference, not an asset
pack. Actual Figma fonts, original artwork and exact fidelity are still U1 checks.

### Panel preview and known differences

With Vite running, open **`http://127.0.0.1:5173/__panel-preview`**. A persistent
synthetic-data notice identifies the entire view; example periods and sources
are also labeled synthetic. Fixture data stays under `src/preview/`, loaded only
by a DEV-guarded import. Production uses the real panel components with `—`,
unknown sources/periods and unavailable history until data is connected.

The illustrative source contains conflicting numbers, labels and units. This
preview preserves the layout/chart families while making these choices explicit:

- Debt uses synthetic annual periods, not unexplained July/August ticks. Its US
  summary is an explicitly synthetic comparator, not a verified source decision.
- Trade uses one monetary scale for imports, exports and balance, with a visible
  currency/scale caption. Expenditure uses INR-crore levels instead of copying
  an inconsistent percentage axis.
- GST's example explicitly shows growth and average growth, with synthetic-only
  series IDs. Those IDs/definitions do not amend the real indicator catalog;
  M3/M4 still resolve U4 before actual-data binding.
- The example inflation reference is **synthetic**, not an assertion of the
  current RBI target or its validity period. Production leaves it unavailable.
- Numeric annotations follow supplied sample values; comparison arrows follow
  their signs. Unverified muted-line/highlight behavior and exact illustrated
  assets are not presented as Figma-confirmed implementation.

U2–U7 retain the M2/M3/M4 ownership recorded in the audit. M2.6 adapts verified
definitions/periods to these views; M2.7/M6 confirm final presentation and fidelity.

### Verification

From `frontend/`, with Vite running for browser checks:

```powershell
npm run test:ui
npm run verify:panels
npm run verify:primitives
npm run verify:layout
npm run build
```

All **18 tests** and **10 browser cases** passed: three panel-preview widths,
three shared-primitives widths and four dashboard/layout/API-failure cases.
The panel check verifies all six plot families, twelve summaries/icons, SVG/text
bounds, reference grid geometry, no horizontal overflow and hover/focus/Escape
for each panel. Target preview row tops remain 158px, 710px and 1262px with 529px
panels. It saves the full frame, six panel crops and a full narrow-page capture.
Use the existing browser/URL/output options; default panel evidence is under
ignored `node_modules/.cache/layout-check/panels/`.

Production build/type-check passed. Fixture routes/modules and distinctive
synthetic values were checked for exclusion from the production JS. Screenshots,
reports and remaining limitations are recorded in the private implementation log.

## Market ticker and visible interactions — M2.5

`MarketTicker` takes a `TickerPresentation`: overall state, refresh-in-progress
flag, supplied cadence/description and attributed quotes. Each quote carries an
instrument ID/label, independent state, decimal-string value, supplied point and
percent changes, comparison label, display precision, observation date and sources.
This is a presentation boundary; M2.6/M4 still own validated API adaptation.

Values render only when both the overall and item states allow `fresh` or `stale`
observations. Loading/error/empty/unavailable states suppress numeric fields even
if values remain in the input object. Explicit stale state allows retention and
labels it in the strip and details. Zero remains zero; point and percent changes
are displayed separately and are never calculated from quotes in the browser.
Missing quotes, changes, dates and comparison periods remain explicit.

The badge shows `LOADING`, `ERROR`, `NO DATA`, `STALE`, `UPDATING`, `SCHEDULED`,
`DELAYED` or `AVAILABLE`, according to supplied state and actual quote availability.
It never labels scheduled observations `LIVE`. Quote details show the supplied
schedule, observation timestamp, original source link and Non-NSE attribution
where applicable. Unknown schedule/source/date stays unavailable. A refresh flag
only describes model state; this component does not start requests or a timer.
The production bootstrap maps connection loading/failure to ticker state; a
successful bootstrap does not establish market-data availability.

### Interaction inventory and provisional choices

The PNG cannot establish animation, clickable legends or selectable periods.
Manual scrolling and quote-detail disclosure are documented implementation choices,
pending exact Figma interaction evidence. No automatic ticker movement is used;
scrolling is immediate under both motion preferences. The status badge, legends,
period labels, icons and header remain informational. No speculative date tabs,
series toggles or refresh buttons are added.

| Surface | Observable behavior | Verification |
| --- | --- | --- |
| Skip link | Visible on keyboard focus; Enter focuses indicator content | Layout/panel browser cases; ticker preview equivalent |
| Ticker strip | Native touch/trackpad scrolling; Left/Right scroll by viewport-relative steps, Home/End reach bounds when strip itself is focused | Four ticker cases, including reduced motion |
| Quote button | Tab focus indicator; Enter, Space or click toggles details; selecting another quote changes details | Ticker keyboard/pointer checks |
| Quote details | Shows supplied points/percent change, comparison basis, cadence, source and observation date | Ticker metadata, zero, stale and partial-data checks |
| Dismissal | Escape or Close dismisses and returns focus to quote; outside pointer or focus dismisses without stealing focus | Ticker dismissal checks |
| Source links | Native keyboard activation; safe HTTP(S) source URLs open separately with `noopener noreferrer`; unknown/unsafe URLs have no link | Formatter tests; ticker and all panel-preview widths exercise activation |
| Chart points/bars | Hover or focus shows exact formatted value; Escape dismisses; accessible data table remains available | All six panels at three widths |

### Preview and verification

With Vite running, visit `http://127.0.0.1:5173/__ticker-preview`. Its clearly labeled
synthetic scenario controls exercise scheduled, delayed, updating, stale, partial,
loading, error, empty and unavailable presentations. The existing panel preview
also receives the synthetic ticker. Preview routes and fixture imports are guarded
by `import.meta.env.DEV` and excluded from production output. Reference instrument
labels do not establish source coverage; M3 must approve the market catalog/feed.

From `frontend/`:

```powershell
npm run test:ui
npm run verify:ticker
npm run verify:panels
npm run verify:layout
npm run build
```

All **22 component tests** passed; TypeScript/production build passed with no new
dependencies or lockfile changes. **11 browser cases** passed: four ticker cases
(1214/390/320px and 390px reduced motion), three populated-panel cases and four
dashboard/layout/API-failure cases. Ticker cases verify actual Enter/Space/Tab,
scroll bounds, focus return, source activation, dismissal, zero/missing/stale
values and all scenario changes. Source activation uses a test-only navigation
interceptor to avoid visiting fixture URLs. Ticker preview makes no data fetches.

The ticker remains 47px high across states, with no page horizontal overflow,
uncaught exceptions or initial layout shift in preview cases. The target panel
grid retains its measured geometry. Evidence defaults to ignored
`node_modules/.cache/layout-check/ticker/`, including details/stale captures and
`ticker-report.json`; private review captures/logs stay outside the repository.
Exact Figma behavior/fidelity, approved sources/cadence and authenticated backend
updates remain open integration work. M2.5 does not complete the overall module.

## Data adapter and failure states — M2.6

The `frontend/src/data/` boundary validates unknown responses before creating
presentation models. `DashboardScreen` renders that result through the existing
six panels and ticker. The production app still checks the bootstrap route;
the protected dashboard client is available for M4/M5/M6 integration and is not
called by that bootstrap. No real data endpoint, login, collector or database is
introduced by this checkpoint.

### Draft M4 projection

The established access paths remain `data.panels[indicator_id].series[series_id]`,
`latest`, `comparison`, `history.points`, `data.ticker.items` and `meta`. The adapter
checks the fields it consumes; M4 can supply additional ADR-08 traceability fields.
The table below describes **proposed additional wire fields**, not an already
implemented backend schema. M4 must accept or revise them with adapter tests.

| Input | Fields used by the adapter |
| --- | --- |
| Envelope | `meta.api_version: "v1"`, valid UTC `generated_at`, nonempty opaque `version`, boolean `partial`; object `data.panels` |
| Panel | `series` keyed by the agreed catalog; supplied `period_label`; optional validated `chart` projection |
| Series | `name`, display `precision` (0–6), `latest`, nullable `comparison`, `history` with `status`, `points`, boolean `truncated` |
| Observation | Decimal-string/null `value`; expected `unit`; `definition_id`; `observation_period` with canonical `id`, source-facing `label`, calendar/fiscal `basis`; `status`, nullable `reason_code`, boolean `retention_allowed`; source/as-of fields below |
| Provenance | `sources: [{source_id, name, url, is_nse}]`; nullable `as_of` with `as_of_precision` and `as_of_kind` when present |
| Comparison | Supplied `value`, compatible difference `unit`, `precision`, `reference_label`, `kind`, `reference_series_id`, `reference_period_id`, explicit `verified: true`; otherwise omitted |
| Policy reference | RBI series additionally requires `policy.applicable: true`, valid day-precision `valid_from` and nullable `valid_to`; M3/M4 establish applicability and validity, the browser does not infer it from today's date |
| Chart projection | Explicit ordered `periods: [{id,label,basis}]`, decimal-string `domain: [min,max]`, 2–20 decimal-string `ticks`, compatible `unit`, display `precision` and `annotation_precision` |
| Ticker | `status`, `cadence` (`scheduled`, `delayed`, `unknown`), nullable `cadence_label`, `items` |
| Quote | Observation fields plus `instrument_id`, `name`, `change`, `change_percent`, nullable `comparison_label`, `precision`, `market_status` (`open`, `closed`, `unknown`) |

For example, this is the chart projection's structure, using illustrative axis
settings and no financial observations:

```json
{
  "unit": "percent_yoy",
  "domain": ["0", "10"],
  "ticks": ["0", "5", "10"],
  "periods": [
    {"id": "2024", "label": "2024", "basis": "calendar"},
    {"id": "2025", "label": "2025", "basis": "calendar"}
  ],
  "precision": 2,
  "annotation_precision": 1
}
```

These bounds/order are supplied projection metadata. The adapter does not derive
economic values, growth rates, policy targets, averages or totals. Local bindings
choose the six existing panel roles, plot types and colors. GST level series use
INR crore, including the panel heading; synthetic growth IDs from the older
illustration preview are not silently accepted as the real GST catalog. The debt
comparison stays unavailable until an approved catalog definition is supplied.

### Validation and independent availability

Non-null observations need a valid decimal string, matching unit, definition,
period, source and date, and an explicit fresh/stale state. Numeric JSON values,
NaN/infinity, invalid calendar dates, unsafe source URLs, unknown units and
missing provenance fail validation. Large valid decimals remain strings for
display; conversion to finite numbers is limited to chart geometry. Year/month
dates retain their precision. Publication/retrieval/request times are never
substituted for observation dates.

Malformed envelope metadata fails the whole read safely. Invalid or missing
series are isolated, preserving valid neighboring series/panels. Invalid history
is unavailable independently of a valid latest value; an invalid comparison
becomes missing. History points align by canonical period ID, label and basis,
not by array position. Explicit null points remain gaps; mismatched/duplicate
periods and invalid chart projections do not invent a replacement history.
History windows are limited to 500 points; source arrays to 20 entries and
instrument lists to 100. Unknown series are not mapped into a visible metric.

Summary and chart availability are independent. Every supplied series has a
keyboard-accessible **Series details** disclosure with original source, as-of
date, latest/history state, safe explanatory text and truncation/policy validity
where applicable. Enter/Space opens it; Escape closes and returns focus. The
disclosure overlays the plot without moving the grid. If latest observation
dates differ, the group date stays `—`; individual dates remain in the disclosure.
An old annual observation can remain fresh according to the backend's release
policy; the browser imposes no global age-based stale deadline.

### Request and refresh behavior

`readDashboard` requests only the configured backend's `/api/v1/dashboard`, with
an in-memory bearer token supplied by M5. It omits cookies, disables browser
caching, rejects redirects, uses a 15-second timeout and supports caller aborts.
It bounds the decoded JSON text to 2,000,000 characters and exposes safe errors
without echoing backend bodies or credentials. No persistent token/data storage,
upstream URL, polling timer or hidden fallback constant is added.

| Event | Presentation result |
| --- | --- |
| First request pending | Loading with missing values and reserved card space |
| Valid response | Replace snapshot with validated current states, even when `version` is unchanged |
| Partial response | Preserve independently valid content; mark missing/invalid series explicitly |
| Supported history query with no observations | Empty state; missing values are not zero |
| No usable observation/source | Unavailable state |
| Refresh pending with a snapshot | Keep current validated content; show refresh-in-progress status |
| Network/HTTP/validation failure | Check cached `retention_allowed` independently for each latest value, history point and quote; retain permitted values as stale, clear all other numeric fields |
| 401/403 | Clear the display snapshot and require sign-in; M5 owns session-token clearing/navigation |
| Caller abort | Reject the canceled read; it cannot commit a result into the preview state |

Retention preserves original dates/sources and supplied comparisons; it never
uses `generated_at` as a new observation timestamp. Denied values do not return
on subsequent failures. This module supplies pure transition functions; M6 still
owns live request ordering, single-flight polling and final integrated behavior.

### State preview and verification

With Vite running, visit `http://127.0.0.1:5173/__states-preview`. The clearly labeled
preview starts with a synthetic validated snapshot, then exercises fresh, loading,
partial, empty, unavailable, error, retained, no-retention, mixed-retention,
malformed and unauthorized scenarios. Its injected transport returns synthetic
HTTP/JSON outcomes through the same client/adapter; it does not contact a real
protected endpoint or send a real token. Changing scenarios aborts the old read.
The route and all API-state fixtures are development-only.

```powershell
npm run test:ui
npm run verify:states
npm run verify:panels
npm run verify:ticker
npm run verify:layout
npm run build
```

All **36 tests** and the production build/type-check passed. **14 browser cases**
passed: three state-matrix widths, three panel widths, four ticker/reduced-motion
cases and four dashboard/API-failure cases. Each matrix case checks all eleven
scenarios plus disclosure/source-link/Escape behavior. Target panels remain 529px
high at row tops 158/710/1262, with stable heights across simulated states and no
page horizontal overflow. Stale plot labels overlay rather than enlarging cards.
Preview transports make no data fetches; actual bootstrap browser requests were
recorded as configured-backend-only. Client tests assert the protected request URL
and options. This is not a live authenticated endpoint test.

Evidence defaults to ignored `node_modules/.cache/layout-check/states/`, including
per-state captures and `states-report.json`; private evidence/logs stay outside
Git. Distinctive fixtures and all four preview routes are excluded from production
JS. M4 wire-schema acceptance, M3 semantics/source approval, M5 authentication,
live polling/integration and exact Figma fidelity remain open. M2 is not locked.

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

Open `http://127.0.0.1:5173`. The styled shell displays six unavailable-data panels
and no-data quote placeholders. The API bootstrap check resolves independently;
failed API requests produce an error message while preserving the layout.

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

At M1.6, browser evidence showed the title and “The dashboard is coming soon.”
placeholder, and HTTP checks passed on 2026-10-15. M1.3 also verified that changing
only `VITE_API_BASE_URL` changed the generated API configuration. M2.2 replaces the
old placeholder with the dashboard shell and supplies the current browser check
above. The root bootstrap route remains the smoke endpoint until M4 implements
`/health`.

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
