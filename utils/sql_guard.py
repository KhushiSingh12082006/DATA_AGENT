"""Hard, code-level checks for LLM-generated SQL (runs BEFORE the LLM judge)."""
import re


def clean_sql(text) -> str:
    """Remove markdown code fences the LLM may wrap around the SQL."""
    text = str(text).strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if m:
        text = m.group(1)
    return text.strip()


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|call|do|merge|"
    r"vacuum|analyze|reindex|cluster|lock|listen|notify|prepare|execute|set|reset|into|"
    r"pg_sleep|pg_read_file|pg_read_binary_file|pg_ls_dir|lo_import|lo_export|dblink|set_config)\b",
    re.I,
)


def _strip_noise(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)      # block comments
    sql = re.sub(r"--[^\n]*", " ", sql)                    # line comments
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)             # string literals
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)             # quoted identifiers
    return sql


def sql_guard(sql: str):
    """Return (ok, reason). Only a single SELECT / WITH ... SELECT is allowed."""
    if not sql or not sql.strip():
        return False, "The query is empty."
    body = _strip_noise(sql).strip().rstrip(";").strip()
    if ";" in body:
        return False, "Only a single SQL statement is allowed."
    if not re.match(r"(select|with)\b", body, re.I):
        return False, "Only SELECT queries are allowed."
    hit = _FORBIDDEN.search(body)
    if hit:
        return False, f"The keyword '{hit.group(0).upper()}' is not allowed in a read-only query."
    return True, "Passed the read-only check."
