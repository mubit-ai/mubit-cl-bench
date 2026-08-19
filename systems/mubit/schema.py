"""Durable schema facts for the ``database_exploration`` task.

The generic lesson distiller stored prose summaries of prior *questions*, which
tells the next question nothing about the database. Replaying
``results/database_exploration/mubit-genai-db-3.json.gz``: the database has 14
objects, and each run spends ~110 of its 543 queries re-discovering them —
88% of those discovery queries repeat an object an earlier question already
looked up, ~2.5 wasted queries per question against a 15-query budget. Another
18 queries per run die on columns that were never there.

So a fact is keyed by the *object* it describes, not by the SQL that found it:
one entry per table, refreshed when the schema migrates mid-run (a rename
overwrites the stale entry rather than leaving it to be recalled — the mem0
failure mode).

Stdlib only, no relative imports: ``python3 systems/mubit/schema.py`` self-checks.
"""

from __future__ import annotations

import re
from typing import Optional

MISSING_OBJECT = re.compile(r"no such (table|column):\s*([\w.]+)", re.I)
_TABLE_INFO = re.compile(r"pragma\s+table_info\s*\(\s*['\"]?(\w+)", re.I)
_TABLE_LIST = re.compile(r"sqlite_master|\.tables|\.schema", re.I)
_RESULT_HEADER = re.compile(r"^Query result \([^)]*\):\s*", re.I)

MAX_FACT_CHARS = 600

Fact = tuple[str, str]


def strip_result_header(observation: str) -> str:
    """Drop the ``Query result (3/15 queries used, ...)`` preamble."""
    return _RESULT_HEADER.sub("", observation.strip()).strip()


def drift_fact(observation: str) -> Optional[Fact]:
    """``(key, text)`` when a query hit an object that no longer exists.

    A missing table reuses that table's own key, so the upsert replaces the
    stale column list instead of leaving it recallable alongside the correction.
    """
    m = MISSING_OBJECT.search(observation)
    if not m:
        return None
    kind, name = m.group(1).lower(), m.group(2).lower()
    if kind == "table":
        return (
            f"db:schema:table:{name}",
            f"SCHEMA DRIFT: table `{name}` no longer exists — it was renamed or "
            f"reshaped. Look for the same data under a new name; match on what "
            f"the table held, not on the old name.",
        )
    return (
        f"db:drift:column:{name}",
        f"SCHEMA DRIFT: column `{name}` does not exist. Read the owning table's "
        f"column list before naming columns.",
    )


def schema_fact(sql: str, observation: str) -> Optional[Fact]:
    """``(key, text)`` for a schema-discovery query that succeeded."""
    sql = (sql or "").strip()
    if not sql:
        return None
    body = strip_result_header(observation)
    if not body or MISSING_OBJECT.search(body) or body.lstrip().upper().startswith("ERROR"):
        return None
    m = _TABLE_INFO.search(sql)
    if m:
        table = m.group(1).lower()
        return f"db:schema:table:{table}", f"SCHEMA table `{table}`:\n{body[:MAX_FACT_CHARS]}"
    if _TABLE_LIST.search(sql):
        return "db:schema:tables", f"SCHEMA tables in this database:\n{body[:MAX_FACT_CHARS]}"
    return None


if __name__ == "__main__":
    # Fixtures lifted verbatim from the shipped run artifacts.
    tables = (
        "Query result (1/15 queries used, 14 remaining):\n\nname           \n"
        "---------------\nitems_g1       \nfdbk_g1        \ntaxn_g1        \n"
    )
    pragma = (
        "Query result (3/15 queries used, 12 remaining):\n\n"
        "cid | name    | type    | notnull | dflt_value | pk\n"
        "0   | id      | INTEGER | 0       | NULL       | 1 \n"
        "1   | ref_id  | TEXT    | 0       | NULL       | 0 \n"
    )
    err = "Query result (6/15 queries used, 9 remaining):\n\nERROR: no such table: taxn_g3"

    k, t = schema_fact("SELECT name FROM sqlite_master WHERE type='table';", tables)
    assert k == "db:schema:tables" and "items_g1" in t and "Query result" not in t, (k, t)

    k, t = schema_fact("PRAGMA table_info(fdbk_g1);", pragma)
    assert k == "db:schema:table:fdbk_g1" and "ref_id" in t, (k, t)
    # Same object, different spelling of the query -> same key, so the second
    # lookup is a no-op upsert instead of a second entry (and, at recall time,
    # a query the agent never has to run again).
    assert schema_fact('PRAGMA table_info("FDBK_G1")', pragma)[0] == k
    assert schema_fact("SELECT name FROM sqlite_master WHERE type='table'", tables)[0] == "db:schema:tables"

    # Failed discovery is not a fact; it is drift, and it lands on the same key
    # so the stale column list is replaced rather than kept.
    assert schema_fact("PRAGMA table_info(taxn_g3);", err) is None
    k, t = drift_fact(err)
    assert k == "db:schema:table:taxn_g3" and "no longer exists" in t, (k, t)
    assert drift_fact("ERROR: no such column: price")[0] == "db:drift:column:price"
    assert drift_fact(tables) is None

    # Ordinary answer-seeking SQL stays out of the registry.
    assert schema_fact("SELECT COUNT(*) FROM fdbk_g1;", tables) is None

    print("schema.py self-check OK")
