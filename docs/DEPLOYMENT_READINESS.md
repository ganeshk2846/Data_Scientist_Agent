# Deployment readiness and remaining blockers

## Reproducible Python setup

Install the backend and its test tools with `pip install -e "backend[dev]"`.
Install TextToSQL's core runtime and test requirements with
`pip install -r TextToSQL/requirements-dev.txt`. The model embeddings and XLSX
intake integrations are optional and have separate requirement files.

## Olist warehouse fixture

The repository does not contain `brazil_ecommerce.sqlite`. The backend's API,
CLI, and several integration tests use the Olist warehouse and assert specific
results, so those checks cannot run successfully without the real fixture.
The TextToSQL Spider datasets are separate and are not a substitute.

Obtain or build the Olist SQLite database through a source whose terms permit
your intended use. This repository does not redistribute the raw dataset or
grant redistribution rights. Point the application and tests at the authorized
local file with `DS_AGENT_DATABASE`:

```powershell
$env:DS_AGENT_DATABASE = 'C:\data\brazil_ecommerce.sqlite'
```

The setting is read by the API, CLI, and the fixture-dependent backend tests.
The gateway opens SQLite in read-only mode. Without the file, the database-backed
API and CLI calls fail at runtime; unit tests that create their own temporary
databases remain runnable.

## API authentication and run ownership

The API now requires a configured bearer token on `POST /api/ask`,
`GET /api/runs/{run_id}`, and `GET /api/runs/{run_id}/events`. Configure
`DS_AGENT_API_TOKENS` as a JSON object mapping stable user IDs to unique random
tokens (at least 32 characters). For example, use a JSON shape like:

```json
{"alice":"<deployment-secret-managed-token>"}
```

The deployment must inject this setting from a secret manager; never put real
tokens in source control, images, logs, or public browser code. Requests use
`Authorization: Bearer <token>`. Missing or invalid credentials receive 401;
the API fails closed with 503 when no token mapping is configured. Tokens are
compared in constant time. `session_id` is not used as identity. The server
stores the authenticated principal as each run's owner and checks ownership
before returning results or opening an event stream. Cross-owner run IDs and
cross-owner `clarification_of` references return 404 to avoid confirming that
another user's run exists. The static workbench accepts a token at runtime and
does not persist it in browser storage.

The current token map is a minimal deployment authentication mechanism, not a
federated identity provider. Before production, configure secure token issuance,
rotation and revocation, TLS, rate limits, and an operational process for
offboarding users. Keep principal IDs stable and do not reuse a removed user's
ID for a different person. Token-map changes require restarting the API process.
Runs and ownership are held in process memory; the current
service therefore requires a single API process and loses runs on restart.
Horizontal scaling or durable run history requires a shared persistent store
that retains owner IDs and enforces the same authorization rules.

Authentication and authorization regression tests run without the Olist file.
Production access control has not been verified in an identity-provider or
deployment environment, so this application is not marked production-ready.

## Validation status and database requirements

The real Olist database is absent from this checkout, so database-backed
behavior must be exercised against an authorized copy as described above.
Do not infer database behavior from temporary test databases or synthetic data.

### PR validation run

- Backend: `python -m pytest -q --tb=no` — 385 passed, 30 skipped. The skips
  are fixture-dependent Olist tests; the new bearer-authentication and
  owner-isolation regressions ran in this suite.
- TextToSQL: `python -m pytest -q --tb=no` — completed successfully; 123 tests
  collected, with one opt-in live-LLM test skipped (122 passed).
- Python compilation: `python -m compileall -q backend/src backend/tests TextToSQL/src TextToSQL/tests` — passed.
- Dependency consistency: `python -m pip check` — passed.
- Frontend inline workbench JavaScript: `node --check` — passed.
- Frontend dependency audit: `npm audit --omit=dev --audit-level=moderate` —
  zero vulnerabilities reported from the lockfile.
- Frontend TypeScript check and build could not run: `frontend/web/node_modules`
  is absent and `tsc` is unavailable. The browser audit could not run because
  Playwright is absent. There is no frontend lint script in `package.json`.
- Python lint and dependency-audit tools (`ruff`, `bandit`, and `pip-audit`)
  are not installed in this environment.
- The repository has no `.github/workflows/` directory. GitHub reported no
  workflow runs or commit statuses for the PR's prior head revision.
- `brazil_ecommerce.sqlite` is absent and `DS_AGENT_DATABASE` is unset; no
  real Olist-database behavior was validated.

These checks do not establish production readiness. Deploy only after the
environment supplies managed per-user credentials, HTTPS and operational
rotation/revocation, and after the authorized Olist database and deployment
configuration have been validated.

## Join governance

The catalog now keeps shared-name join candidates as proposals and only uses
database-declared foreign keys for generated paths. This prevents matching
`*_id` names from silently authorizing a join. There is not yet an application
review workflow for approving inferred joins. If the warehouse omits declared
foreign-key constraints, cross-table generated queries remain unavailable until
an explicit, auditable approval mechanism is added.
