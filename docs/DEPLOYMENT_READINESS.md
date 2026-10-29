# Deployment readiness blockers

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

## Authentication and run ownership

The FastAPI surface currently has no authentication middleware or trusted
identity provider. `POST /api/ask` accepts a caller-supplied `session_id`, while
run records do not persist an authenticated principal. `GET /api/runs/{run_id}`
and the SSE event route authorize by possession of the run ID alone. A random
UUID is difficult to guess but is not an owner check.

Safe run-owner authorization cannot be completed until deployment supplies a
trusted identity contract: for example, a configured token issuer and audience
with verification keys, or a reverse-proxy identity header whose origin is
authenticated and stripped from untrusted requests. Once selected, the verified
principal must be stored on each run and checked on both result and SSE routes.
Until then, expose the API only on a private or otherwise trusted network; do
not treat the current endpoints as suitable for public deployment.

## Join governance

The catalog now keeps shared-name join candidates as proposals and only uses
database-declared foreign keys for generated paths. This prevents matching
`*_id` names from silently authorizing a join. There is not yet an application
review workflow for approving inferred joins. If the warehouse omits declared
foreign-key constraints, cross-table generated queries remain unavailable until
an explicit, auditable approval mechanism is added.
