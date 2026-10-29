# BE-2 local startup and deployment readiness

## Local checks

Use Python 3.11 or newer and the workspace's already provisioned environment.
From the repository root:

```powershell
python -m src.onboarding health --root .
python -m src.onboarding.demo
python -m pytest -v -p no:cacheprovider
```

`health` makes no network calls, prints no secret values, and checks local
runtime and writable-root readiness. Its `optional_models` and `llm` sections
report optional component configuration separately; a green local health
result is not a public service health check.

Build a catalog from a read-only SQLite warehouse:

```powershell
python -m src.onboarding build --warehouse <read-only-sqlite-path> --output <new-catalog-directory>
```

The persistent refresh worker can be run under a supervisor after a service
root and refresh schedule have been configured:

```powershell
python -m src.onboarding.worker --root <service-state-directory> --poll-seconds 5
```

The worker is a local Python process. This repository does not currently expose
the authenticated HTTP routes, public web application, or process supervisor
configuration required for a production deployment.

## Environment and secret handling

Copy `env.example` to a private, ignored `.env` file for local development, or
inject settings through the deployment platform's secret manager. Never put
real keys, principal IDs, privacy approvals, or warehouse credentials in source
control, build logs, or documentation. `LLMGateway` validates URLs, timeouts,
retry limits, and example placeholder keys; errors expose stable codes without
printing key values. Use HTTPS for remote LLM endpoints; plain HTTP is accepted
only for loopback development endpoints.

Optional learned retrieval settings are `TEXTTOSQL_MODEL_CACHE`,
`TEXTTOSQL_EMBEDDING_MODEL_ID`, `TEXTTOSQL_EMBEDDING_MODEL_REVISION`,
`TEXTTOSQL_RERANKER_MODEL_ID`, and `TEXTTOSQL_RERANKER_MODEL_REVISION`.
Overriding an ID requires its paired full 40-character lowercase commit pin.
Install the optional dependency only in an approved build environment, cache
both exact revisions, then run:

```powershell
python -m pip install -r requirements-embeddings.txt
$env:TEXTTOSQL_MODEL_CACHE = "<approved-model-cache>"
python -m src.knowledge.model_assets --cache-dir <approved-model-cache>
python -m src.knowledge.evaluate_retrieval
```

The asset command downloads only the configured pinned public model revisions;
the evaluator must run with those files already present. Record its actual JSON
output, runtime versions, and model pins in the release evidence. A test fixture
or hashed n-gram fallback is not a learned-model result.

Transactional intake remains opt-in and never downloads its source. After the
organization has supplied the reviewed workbook, an approval record, and an
approved XLSX runtime, run:

```powershell
python -m pip install -r requirements-uci-intake.txt
python -m data_gen.transactional_intake --source <reviewed-uci-workbook.xlsx> --output <new-transactions.sqlite> --privacy-approval-ref <actual-review-reference> --privacy-approval-record <organization-approval-record.json> --provenance <provenance-output.json>
```

The approval JSON must contain `reference`, `status`, `dataset_url`, `scope`,
`reviewer`, and ISO-8601 `reviewed_at`; it must identify an approved UCI Online
Retail II development intake. The importer validates these fields but does not
cryptographically authenticate the record or its issuer. Keep the actual
approval record outside this repository and verify it through the organization's
privacy process before running intake.

## Deployment verification checklist

Before deployment, an operator must provision and verify all of the following:

1. A real target, network policy, supported runtime, process supervisor, and
   persistent state volume with backup and restore policy.
2. A secret manager containing the approved LLM/warehouse settings. Verify
   startup and health output without printing secret values.
3. An authenticated BE-1 API that supplies reviewer identity from its verified
   principal. `MetricRegistry` denies decisions unless its host injects an
   authorizer; a reviewer string alone is not authentication.
4. A separate scoring OS identity and protected truth/split storage. The
   `ScoringAccessPolicy` is an application-level deny-by-default boundary;
   environment principal lists and Python checks do not provide OS isolation.
5. A privacy-authorized source workbook and the organization-owned approval
   record required by `data_gen.transactional_intake`. The importer validates
   record fields but cannot authenticate who issued that record.
6. A verification run from a clean deployment image: health check, smoke build,
   privacy canary scan, review authorization negatives, leakage gate, backup /
   recovery check, and externally verified ACL/account separation.

Until an actual target, secret manager, reviewer identity provider, source
approval, and scoring identity are provisioned, status is **BLOCKED for
deployment** and **PARTIAL for local readiness**. No public deployment or
strong-isolation claim is made by this checklist.
