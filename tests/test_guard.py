"""SQL 安全护栏单测（无需外部依赖）。"""

import pytest

from app.sql.guard import SQLGuardError, validate_and_secure


def test_select_passes_and_gets_limit():
    out = validate_and_secure("SELECT name FROM singer", dialect="sqlite", max_rows=50)
    assert "LIMIT 50" in out.upper()


def test_existing_limit_preserved():
    out = validate_and_secure("SELECT * FROM t LIMIT 5", dialect="sqlite")
    assert out.upper().count("LIMIT") == 1
    assert "5" in out


def test_strips_code_fence():
    out = validate_and_secure("```sql\nSELECT count(*) FROM singer\n```", dialect="sqlite")
    assert out.upper().startswith("SELECT")


@pytest.mark.parametrize(
    "bad",
    [
        "DELETE FROM singer",
        "DROP TABLE singer",
        "UPDATE singer SET name='x'",
        "INSERT INTO singer VALUES (1)",
        "SELECT 1; DROP TABLE singer",
    ],
)
def test_forbidden_statements_rejected(bad):
    with pytest.raises(SQLGuardError):
        validate_and_secure(bad, dialect="sqlite")


def test_empty_rejected():
    with pytest.raises(SQLGuardError):
        validate_and_secure("   ", dialect="sqlite")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM singer UNION SELECT name FROM singer",
        "SELECT name FROM singer INTERSECT SELECT name FROM singer",
        "WITH x AS (SELECT name FROM singer) SELECT name FROM x",
    ],
)
def test_readonly_complex_queries_pass(sql):
    out = validate_and_secure(sql, dialect="sqlite", max_rows=50)
    assert "SELECT" in out.upper()
