import pytest
from app.guardrail import PolicyError, validate_sql

@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM `p.semantic.students`",
    "WITH s AS (SELECT id FROM `p.semantic.students`) SELECT * FROM s",
    "SELECT 1 UNION ALL SELECT 2",
    "SELECT s.id FROM `p.semantic.students` s JOIN `p.semantic.schools` t ON s.id=t.id",
])
def test_allowed(sql):
    assert validate_sql(sql, "p", "semantic")

@pytest.mark.parametrize("sql", [
    "DELETE FROM `p.semantic.students` WHERE TRUE",
    "SELECT 1; SELECT 2", "SELECT * FROM `p.raw.students`",
    "SELECT * FROM `other.semantic.students`", "SELECT * FROM students",
    "SELECT * FROM `p.semantic.students*`",
    "SELECT * FROM `p.semantic.INFORMATION_SCHEMA.TABLES`",
    "SELECT * FROM EXTERNAL_QUERY('connection', 'SELECT 1')",
    "SELECT `p.semantic.remote_fn`('secret')",
    "SELECT SESSION_USER()", "EXPORT DATA OPTIONS(uri='gs://x/*',format='CSV') AS SELECT 1",
    "WITH s AS (SELECT * FROM `p.raw.students`) SELECT * FROM s",
    "SELECT * FROM `p.semantic.students` WHERE id IN (SELECT id FROM `p.raw.students`)",
    "SELECT * FROM `p.semantic.table_fn`()",
])
def test_blocked(sql):
    with pytest.raises(PolicyError):
        validate_sql(sql, "p", "semantic")
