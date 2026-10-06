import logging
import os
from concurrent.futures import TimeoutError as JobTimeout
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from google.api_core.exceptions import BadRequest, Forbidden, GoogleAPICallError
from google.cloud import bigquery
from pydantic import BaseModel, Field

from app.guardrail import PolicyError, validate_sql

logger = logging.getLogger(__name__)
app = FastAPI(title="BigQuery Guardrail", docs_url="/docs", redoc_url=None)
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
DATA_PROJECT = os.getenv("BQ_DATA_PROJECT", PROJECT)
DATASET = os.environ["BQ_SEMANTIC_DATASET"]
LOCATION = os.environ["BQ_LOCATION"]
MAX_BYTES = int(os.getenv("BQ_MAX_BYTES_BILLED", "1000000000"))
MAX_ROWS = int(os.getenv("BQ_MAX_ROWS", "100"))
TIMEOUT = int(os.getenv("BQ_TIMEOUT_SECONDS", "30"))
if min(MAX_BYTES, MAX_ROWS, TIMEOUT) <= 0:
    raise RuntimeError("Query limits must be positive.")

@lru_cache
def client():
    # ADC uses the attached Cloud Run service account; no JSON keys.
    return bigquery.Client(project=PROJECT, location=LOCATION)

class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.post("/query")
def query(request: QueryRequest):
    try:
        sql = validate_sql(request.sql, DATA_PROJECT, DATASET)
    except PolicyError as exc:
        raise HTTPException(400, str(exc)) from exc
    job = None
    try:
        bq = client()
        preview = bq.query(sql, job_config=bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, use_legacy_sql=False),
            timeout=TIMEOUT)
        if preview.statement_type != "SELECT":
            raise HTTPException(400, "Only SELECT queries are allowed.")
        if preview.total_bytes_processed is None or preview.total_bytes_processed > MAX_BYTES:
            raise HTTPException(400, "Query exceeds the scan budget or cannot be estimated.")
        job = bq.query(sql, job_config=bigquery.QueryJobConfig(
            use_legacy_sql=False, maximum_bytes_billed=MAX_BYTES,
            job_timeout_ms=TIMEOUT * 1000, labels={"application": "bq-guardrail"}),
            timeout=TIMEOUT)
        rows = job.result(timeout=TIMEOUT, max_results=MAX_ROWS)
        return {"job_id": job.job_id, "rows": [dict(row) for row in rows],
                "total_rows": rows.total_rows,
                "truncated": rows.total_rows > MAX_ROWS}
    except JobTimeout as exc:
        if job is not None:
            try:
                job.cancel()
            except GoogleAPICallError:
                logger.warning("Query cancellation failed")
        raise HTTPException(504, "Query timed out.") from exc
    except Forbidden as exc:
        raise HTTPException(403, "BigQuery access denied.") from exc
    except BadRequest as exc:
        raise HTTPException(400, "BigQuery rejected the query.") from exc
    except GoogleAPICallError as exc:
        logger.warning("BigQuery request failed: %s", type(exc).__name__)
        raise HTTPException(502, "BigQuery is unavailable.") from exc
