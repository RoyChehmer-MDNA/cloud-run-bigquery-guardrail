# Cloud Run BigQuery Guardrail

A Python service for running SELECT queries against a semantic dataset only.
Cloud Run authenticates to BigQuery using Application Default Credentials (ADC)
and its attached service account, without JSON keys.

## Structure and permissions

- `app/`: API with `POST /query` and `GET /healthz`.
- `infra/`: Terraform configuration that creates `bq-agent-guardrail`, attaches it to the service, and grants `roles/bigquery.jobUser` in the billing project.
- Dataset-level `READER` access (equivalent to BigQuery Data Viewer) is granted only on an existing semantic dataset. No datasets are created and no source data is modified.
- The agent identity receives `roles/run.invoker` on this service only.
- The deployment principal receives `roles/iam.serviceAccountUser` on the service account only. Permissions to manage infrastructure and perform deployments are prerequisites.
- The service requires IAM authentication. No access is granted to `allUsers` or `allAuthenticatedUsers`.

## Run with Docker Compose

Edit `.env` in the project root and replace the project IDs, dataset, and location
with your actual values. For a fresh checkout, copy `.env.example` to `.env` first.
The `.env` file is ignored by Git and excluded from the Docker image.
Docker Compose loads it into the container automatically.

Start Docker Desktop with Linux containers, then run from the project root:

```powershell
gcloud auth application-default login
docker compose up --build
```

Open http://localhost:8080/docs. Stop any previously running container using port
8080 before starting Compose. Press Ctrl+C to stop the service.

Compose mounts the local Windows gcloud ADC file read-only. If you use a different
credentials location (including Linux/macOS), set `ADC_CREDENTIALS_PATH` in `.env`
to the absolute path of your ADC file. Use forward slashes in that path. The file
must exist; run the login command before starting Compose. Credentials are not
copied into the image. Queries run using your local ADC identity.

After changing `.env`, apply the settings by running:

```powershell
docker compose up -d
```

Compose recreates the container when its configuration changes; `docker compose
restart` alone does not load new values. No image rebuild is needed for `.env`
changes. To stop and remove the Compose container:

```powershell
docker compose down
```

This `.env` workflow is for local Docker Compose. Direct Python runs use the
shell environment as shown below; Cloud Run uses the Terraform configuration.

## Local testing

Python 3.13 is required:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
```

To run locally against BigQuery (requires gcloud and ADC authentication):

```powershell
gcloud auth application-default login
$env:GOOGLE_CLOUD_PROJECT = "YOUR_PROJECT_ID"
$env:BQ_DATA_PROJECT = "YOUR_DATA_PROJECT_ID"
$env:BQ_SEMANTIC_DATASET = "semantic_layer"
$env:BQ_LOCATION = "EU"
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

When running locally, the server uses your local ADC identity and does not have
Cloud Run's IAM authentication checks. Do not expose it to a public network.
Do not set `GOOGLE_APPLICATION_CREDENTIALS` in Cloud Run.

Open http://localhost:8080/docs for Swagger UI while the server is running.
Expand an endpoint, select **Try it out**, enter the request body if needed,
and select **Execute**. Real queries require BigQuery credentials and access;
`GET /healthz` and rejected SQL can be checked without credentials.
After code changes, rebuild the Docker image and recreate the container if
running with Docker.

## Deployment

Prerequisites: a GCP project with billing enabled, an existing semantic dataset,
an existing agent service account, Google Cloud CLI, Terraform >= 1.5, and
permissions to enable APIs, create a service account, manage project and service
account IAM, update dataset permissions, and deploy Cloud Run.
These permissions are required by the infrastructure administrator; they are not
granted to the runtime identity.

1. Build a container image in Artifact Registry. Replace the project ID in this PowerShell example:

```powershell
$project = "YOUR_PROJECT_ID"
$region = "europe-west1"
gcloud auth login
gcloud auth application-default login
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com --project=$project
gcloud artifacts repositories create guardrail --repository-format=docker --location=$region --project=$project
gcloud builds submit . --tag="${region}-docker.pkg.dev/${project}/guardrail/service:initial" --project=$project
```

If the repository already exists, skip its creation. The build account needs
appropriate Cloud Build permissions and write access to the repository.
For deployments across projects, the Cloud Run service agent also needs
appropriate permissions to read the image.
The Dockerfile copies only application code and dependencies.

2. Copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars` and replace all example values.
The BigQuery location must match the dataset location; it is separate from the
Cloud Run region. Pinning the image by digest is recommended.

3. Run:

```powershell
terraform -chdir=infra init
terraform -chdir=infra fmt
terraform -chdir=infra validate
terraform -chdir=infra plan -out=guardrail.tfplan
terraform -chdir=infra apply guardrail.tfplan
```

Review the plan before applying it. Store Terraform state in a protected, shared
location according to your organization's policy. Do not commit state or tfvars
to Git. After initialization, committing the provider lock file to Git is recommended.
Terraform protects the service from deletion using `deletion_protection`.

This configuration is intended for new resources. If a service or account with
the same name already exists, import it into the state and review its permissions
before applying. The configuration adds permissions; it does not remove existing
broad permissions or permissions inherited from the organization. Do not manage
the same dataset concurrently through an IAM policy/binding or an authoritative
ACL elsewhere: this may overwrite access and authorized-view permissions.

## Calling from the agent

The agent must obtain a Google ID token with an audience equal to the service URL
(without `/query`), then send:

```http
POST /query
Authorization: Bearer ID_TOKEN
Content-Type: application/json

{"sql":"SELECT COUNT(*) AS total FROM `YOUR_DATA_PROJECT_ID.semantic_layer.students`"}
```

The response includes `rows`, `total_rows`, `truncated`, and `job_id`.
The server does not use a user identity header or parameter to change the
BigQuery identity.

## Guardrail scope and limitations

The policy allows SELECT and UNION queries, including CTEs and JOINs, with fully
qualified table names and a limited list of built-in functions defined in
`app/guardrail.py`. Unsupported SQL is rejected.
Writes, scripts, wildcard tables, INFORMATION_SCHEMA, custom functions, and
external queries are not supported. SQL is validated using an abstract syntax
tree (AST), then submitted in its canonical form.

A dry run is performed before execution. The defaults allow up to 1 GB scanned
per query, up to 100 rows in the response, and a 30-second wait. The row limit
does not limit the amount of data scanned. Cancelling a job after a timeout is
best effort; there is no overall spending budget or request quota.
Application validation is not a substitute for IAM. View definitions and their
permissions must also be reviewed.

If semantic-layer views read from raw/core, the data administrator must configure
authorized views on the source dataset. This configuration does not grant the
service access to source data or create views.

BigQuery's `SESSION_USER()` reflects the service account, so this does not provide
row-level security (RLS) based on the human user. This solution does not implement
delegated user identity.

## Verification after deployment

- Cloud Run should reject a request without an ID token.
- The authorized agent identity should successfully query the semantic dataset.
- The application should reject a query against raw/core.
- An authorized administrator should separately impersonate the runtime service account and verify that IAM also denies direct reads from raw/core.
- Verify access to authorized views, if any, using the runtime identity.

Unit tests use a mocked BigQuery client. They do not verify cloud permissions or access.

## References

- [Cloud Run service identity](https://docs.cloud.google.com/run/docs/configuring/services/service-identity)
- [BigQuery query permissions](https://docs.cloud.google.com/bigquery/docs/running-queries)
- [Authorized Views](https://docs.cloud.google.com/bigquery/docs/authorized-views)
- [Service-to-service authentication](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)
#   c l o u d - r u n - b i g q u e r y - g u a r d r a i l  
 