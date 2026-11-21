"""PostgreSQL helper: schema text for the LLM + safe, structured query execution."""
import datetime
import decimal
import os
import time
import uuid

import psycopg2
from psycopg2 import sql as pgsql
from dotenv import load_dotenv

load_dotenv()


def db_config_from_env(readonly: bool = False) -> dict:
    """Reads your existing .env names (host, port, user, password, database).
    If ro_user / ro_password exist and readonly=True, the read-only role is used."""
    use_ro = readonly and bool(os.environ.get("ro_user"))
    return {
        "host": os.environ["host"],
        "port": int(os.environ.get("port", "5432")),
        "user": os.environ["ro_user"] if use_ro else os.environ["user"],
        "password": os.environ["ro_password"] if use_ro else os.environ["password"],
        "dbname": os.environ["database"],
    }


def jsonable(v):
    """Make a database value safe to send as JSON."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, datetime.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, (datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "<binary>"
    if isinstance(v, uuid.UUID):
        return str(v)
    return str(v)


class DatabaseUtil:
    def __init__(self, db_config, readonly: bool = False, timeout_ms: int = 15000):
        self.db_config = db_config
        self.readonly = readonly
        self.connection = None
        try:
            self.connection = psycopg2.connect(**db_config, options=f"-c statement_timeout={timeout_ms}")
            if readonly:
                self.connection.set_session(readonly=True)
        except Exception as e:
            print(f"Error connecting to the database: {e}")

    # Text description of the schema (context for the LLM)
    def schema_details(self, schema_name: str) -> str:
        conn = self.connection
        if conn is None:
            return "Error fetching schema details: no database connection"
        out = f"Database Schema: {schema_name}\n"
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name;",
                (schema_name,),
            )
            for (table_name,) in cur.fetchall():
                out += f"\nTable: {table_name}\n"
                cur.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position;",
                    (schema_name, table_name),
                )
                for column_name, data_type in cur.fetchall():
                    out += f"  Column: {column_name}, Data Type: {data_type}\n"
                cur.execute(
                    pgsql.SQL("SELECT * FROM {}.{} LIMIT 5;").format(
                        pgsql.Identifier(schema_name), pgsql.Identifier(table_name)
                    )
                )
                out += "  Sample Data:\n"
                for row in cur.fetchall():
                    out += f"    {row}\n"
        except Exception as e:
            print(f"Error fetching schema details: {e}")
            out = f"Error fetching schema details: {e}"
        finally:
            cur.close()
            conn.close()
        return out

    # Structured result: {"columns": [...], "rows": [[...]], "truncated": bool}
    def run_query(self, query: str, max_rows: int = 500) -> dict:
        conn = self.connection
        if conn is None:
            raise RuntimeError("No database connection")
        cur = conn.cursor()
        try:
            cur.execute(query)
            if cur.description is None:
                return {"columns": [], "rows": [], "truncated": False}
            columns = [d[0] for d in cur.description]
            data = cur.fetchmany(max_rows + 1)
            rows = [[jsonable(v) for v in r] for r in data[:max_rows]]
            return {"columns": columns, "rows": rows, "truncated": len(data) > max_rows}
        finally:
            try:
                conn.rollback()          # never commit: this path is read-only
            except Exception:
                pass
            cur.close()
            conn.close()

    # Kept for old code: returns the rows as a string, or None on error
    def execute_sql(self, query: str):
        try:
            return str([tuple(r) for r in self.run_query(query)["rows"]])
        except Exception as e:
            print(f"Error executing query: {e}")
            return None


_schema_cache = {}


def get_schema_text(schema_name: str = "public", ttl: int = 300) -> str:
    """Schema text cached for `ttl` seconds so each question does not re-scan the database."""
    now = time.time()
    hit = _schema_cache.get(schema_name)
    if hit and now - hit[0] < ttl:
        return hit[1]
    db = DatabaseUtil(db_config_from_env(readonly=True), readonly=True)
    text = db.schema_details(schema_name)
    if not text.startswith("Error"):
        _schema_cache[schema_name] = (now, text)
    return text
