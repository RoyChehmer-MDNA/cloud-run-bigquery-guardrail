"""Conservative GoogleSQL policy. IAM is an independent enforcement layer."""
import re
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

class PolicyError(ValueError):
    pass

SAFE_FUNCTIONS = {
    "COUNT", "SUM", "AVG", "MIN", "MAX", "COALESCE", "NULLIF",
    "CAST", "TRY_CAST", "ROUND", "ABS", "LOWER", "UPPER", "LENGTH",
    "DATE", "CURRENT_DATE", "CURRENT_TIMESTAMP", "EXTRACT",
    "ROW_NUMBER", "RANK", "DENSE_RANK", "IF", "CASE",
}
FORBIDDEN = {
    "Into", "Lock", "Command", "Insert", "Update", "Delete", "Merge",
    "Create", "Drop", "Alter", "Execute", "Transaction", "Commit",
    "Rollback", "Export", "Copy", "Grant", "Revoke",
}

def validate_sql(sql: str, project: str, dataset: str) -> str:
    try:
        statements = sqlglot.parse(sql, read="bigquery")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise PolicyError("Only a single SELECT query is allowed.")
        tree = statements[0]
        for node in tree.walk():
            if type(node).__name__ in FORBIDDEN:
                raise PolicyError("This SQL operation is not allowed.")
            if isinstance(node, exp.Func):
                if isinstance(node, exp.Anonymous) or node.sql_name() not in SAFE_FUNCTIONS:
                    raise PolicyError("This function is not allowed.")
                if isinstance(node.parent, exp.Dot):
                    raise PolicyError("Qualified functions are not allowed.")
        for scope in traverse_scope(tree):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table):
                    if (source.catalog != project or source.db != dataset
                            or not isinstance(source.this, exp.Identifier)
                            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", source.name)):
                        raise PolicyError("Use fully qualified tables in the semantic dataset only.")
        # Submit the parsed form, not a second interpretation of the original text.
        return tree.sql(dialect="bigquery")
    except PolicyError:
        raise
    except Exception as exc:
        raise PolicyError("SQL could not be validated.") from exc
