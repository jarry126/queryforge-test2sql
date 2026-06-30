"""SQL 难度分级单测。"""

import pytest

from eval.hardness import sql_hardness


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT count(*) FROM singer", "easy"),
        ("SELECT name FROM singer ORDER BY age", "easy"),
        ("SELECT T1.name FROM singer AS T1 JOIN concert AS T2 ON T1.id = T2.sid", "medium"),
        ("SELECT country, count(*) FROM singer GROUP BY country", "medium"),
        (
            "SELECT T1.name FROM a AS T1 JOIN b AS T2 ON T1.id=T2.id JOIN c AS T3 ON T2.id=T3.id",
            "hard",
        ),
        ("SELECT name FROM singer WHERE age > (SELECT avg(age) FROM singer)", "extra"),
        ("SELECT name FROM a UNION SELECT name FROM b", "extra"),
    ],
)
def test_hardness_levels(sql, expected):
    assert sql_hardness(sql) == expected
