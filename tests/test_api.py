import os
from unittest.mock import Mock
os.environ.update(GOOGLE_CLOUD_PROJECT="p", BQ_SEMANTIC_DATASET="semantic", BQ_LOCATION="EU")
from fastapi.testclient import TestClient
from app import main

def test_invalid_sql_never_calls_bigquery(monkeypatch):
    bq = Mock()
    monkeypatch.setattr(main, "client", lambda: bq)
    response = TestClient(main.app).post("/query", json={"sql": "SELECT * FROM `p.raw.students`"})
    assert response.status_code == 400
    bq.query.assert_not_called()

def test_dry_run_budget_stops_execution(monkeypatch):
    bq = Mock()
    bq.query.return_value = Mock(statement_type="SELECT", total_bytes_processed=main.MAX_BYTES + 1)
    monkeypatch.setattr(main, "client", lambda: bq)
    assert TestClient(main.app).post("/query", json={"sql": "SELECT 1"}).status_code == 400
    assert bq.query.call_count == 1

def test_execution_limits(monkeypatch):
    bq = Mock()
    job = Mock(job_id="test")
    rows = Mock(total_rows=101)
    rows.__iter__ = Mock(return_value=iter([{"id": 1}]))
    job.result.return_value = rows
    bq.query.side_effect = [Mock(statement_type="SELECT", total_bytes_processed=10), job]
    monkeypatch.setattr(main, "client", lambda: bq)
    response = TestClient(main.app).post("/query", json={"sql": "SELECT 1"})
    assert response.status_code == 200
    assert response.json()["truncated"] is True
    assert bq.query.call_args.kwargs["job_config"].maximum_bytes_billed == main.MAX_BYTES
    job.result.assert_called_once_with(timeout=main.TIMEOUT, max_results=main.MAX_ROWS)
