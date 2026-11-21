"""
LOGIX API - the layer between the web page and your LangGraph agents.

Run (from the project root):
    uvicorn api:app --reload --port 8000
then open http://127.0.0.1:8000
"""
import io
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, HumanMessage

load_dotenv()
ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))

# NOTE: we do NOT import agents/data_agent.py here, because it draws a graph image
# (needs internet) at import time. We reuse its router idea directly below.
from agents.sql_analyst import sql_analyst        # noqa: E402
from agents.etl_analyst import etl_analyst        # noqa: E402
from utils.llm_pick import pick_llm               # noqa: E402
from utils import history                         # noqa: E402

DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "static"
FILE_EXTS = {".csv", ".json", ".parquet"}
GREETING = re.compile(r"^\s*(hi+|hello+|hey+|yo|good (morning|afternoon|evening)|thanks?|thank you|help|\?)\W*$", re.I)
# The ETL agent runs LLM-written pandas code with exec(). Keep this on only on a
# machine you trust. Set ETL_ENABLED=false in .env to switch the ETL agent off.
ETL_ENABLED = os.environ.get("ETL_ENABLED", "true").lower() == "true"

FILES: dict = {}                 # file id -> Path (only these files can be downloaded)
ETL_LOCK = threading.Lock()      # one ETL run at a time, so output files are not mixed up

# What to show AFTER each node has finished (i.e. the step that is starting now)
NEXT_SQL = {
    "curate_ques": "Reading the database schema",
    "prompt_query_context": "Writing the SQL",
    "generate_sql": "Checking the query is safe",
    "is_safe_sql": "Running the query",
    "execute_sql": "Writing your answer",
}
NEXT_ETL = {
    "llm_node": "Running the ETL tools",
    "tool_node": "Checking the result",
}


class Ask(BaseModel):
    question: str = Field(..., max_length=1000)
    mode: str = "auto"           # auto | sql | etl


STRONG_ETL = re.compile(r"\b(extract|transform|etl|pipeline)\b|https?://", re.I)
FILE_WORDS = re.compile(r"\b(csv|json|parquet|file|folder|api|url|endpoint)\b", re.I)
SQL_WORDS = re.compile(
    r"\b(select|how many|count|average|avg|sum|total|most|least|top|highest|lowest|list|name|show|which|what|who|"
    r"when|where|database|table|query|rides?|users?|drivers?|vehicles?|payments?|ratings?|fare|city)\b", re.I)


def decide_route(question: str) -> str:
    """Pick the agent with simple rules first; ask the LLM (plain text, no tool calling) only if unclear."""
    if STRONG_ETL.search(question):
        return "etl"
    if SQL_WORDS.search(question) and not FILE_WORDS.search(question):
        return "sql"
    try:
        out = pick_llm("low").invoke(
            "Reply with exactly one word: sql or etl.\n"
            "sql = a question about data stored in the database.\n"
            "etl = a request to extract, transform or load data from an API or a file.\n"
            "Request: " + question).content
        return "etl" if "etl" in str(out).lower() else "sql"
    except Exception:
        return "sql"


def _get(state, key, default=None):
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def _last_ai_text(messages) -> str:
    for m in reversed(messages or []):
        if isinstance(m, AIMessage):
            c = m.content
            if isinstance(c, list):
                c = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
            if str(c).strip():
                return str(c).strip()
    return "The ETL run finished."


def _read_table(path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext == ".parquet":
        return pd.read_parquet(path)
    try:
        return pd.read_json(path, lines=True)
    except ValueError:
        return pd.read_json(path)


def _collect_outputs(started: float) -> list:
    """Files the ETL run created or changed inside ./data"""
    found = []
    if DATA_DIR.exists():
        for p in DATA_DIR.rglob("*"):
            if p.is_file() and p.suffix.lower() in FILE_EXTS and p.stat().st_mtime >= started - 1:
                found.append(p)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in found[:5]:
        fid = uuid.uuid4().hex[:12]
        FILES[fid] = p
        out.append({"id": fid, "name": p.name, "ext": p.suffix.lstrip(".").lower()})
    if len(FILES) > 300:                       # keep the registry small
        for k in list(FILES)[:100]:
            FILES.pop(k, None)
    return out


# ------------------------------- the two agent runners (yield events) -------------------------------

def _run_sql(question: str):
    init = {
        "messages": [], "user_question": question, "curated_ques": "",
        "prompt_query_context": "", "generated_sql_query": "", "is_safe": "No",
        "comments": "", "sql_query_execution_result": "", "final_answer": "",
        "columns": [], "rows": [],
    }
    yield {"type": "step", "label": "Reading your question"}
    final = None
    for kind, chunk in sql_analyst.stream(init, stream_mode=["updates", "values"]):
        if kind == "updates" and isinstance(chunk, dict):
            for node in chunk:
                label = NEXT_SQL.get(node)
                if label:
                    yield {"type": "step", "node": node, "label": label}
        elif kind == "values":
            final = chunk
    if final is None:
        raise RuntimeError("The SQL agent returned nothing.")
    yield {
        "type": "result",
        "route": "sql",
        "answer": _get(final, "final_answer", ""),
        "sql": _get(final, "generated_sql_query", ""),
        "safe": str(_get(final, "is_safe", "No")).lower() == "yes",
        "comments": _get(final, "comments", ""),
        "columns": _get(final, "columns", []) or [],
        "rows": _get(final, "rows", []) or [],
    }


def _run_etl(question: str):
    yield {"type": "step", "label": "Planning the pipeline"}
    with ETL_LOCK:
        started = time.time()
        final = None
        for kind, chunk in etl_analyst.stream(
            {"messages": [HumanMessage(content=question)]},
            stream_mode=["updates", "values"],
            config={"recursion_limit": 15},
        ):
            if kind == "updates" and isinstance(chunk, dict):
                for node in chunk:
                    label = NEXT_ETL.get(node)
                    if label:
                        yield {"type": "step", "node": node, "label": label}
            elif kind == "values":
                final = chunk
        files = _collect_outputs(started)
    answer = _last_ai_text(_get(final, "messages", []))

    columns, rows = [], []
    if files:
        try:
            df = _read_table(FILES[files[0]["id"]]).head(10)
            part = json.loads(df.to_json(orient="split", date_format="iso", default_handler=str))
            columns, rows = part["columns"], part["data"]
        except Exception:
            pass
    yield {"type": "result", "route": "etl", "answer": answer, "files": files,
           "columns": columns, "rows": rows}


def _events(req: Ask):
    question = req.question.strip()
    if not question:
        yield {"type": "error", "message": "Please type a question."}
        return
    mode = req.mode if req.mode in ("sql", "etl") else "auto"
    if GREETING.match(question):                  # small talk: answer directly, no agent, not saved
        yield {"type": "route", "route": mode if mode in ("sql", "etl") else "sql"}
        yield {"type": "result", "route": "sql", "chat": True, "safe": True, "comments": "", "sql": "",
               "columns": [], "rows": [],
               "answer": "Hi! Ask me a question about your data, for example \"average fare by city\", "
                         "or describe an ETL job, for example \"extract data from an API URL and save it as csv\"."}
        return
    status, saved = "error", False
    try:
        if mode == "auto":
            yield {"type": "step", "label": "Choosing the right agent"}
            mode = decide_route(question)
        yield {"type": "route", "route": mode}
        if mode == "etl" and not ETL_ENABLED:
            yield {"type": "error", "message": "The ETL agent is switched off on this server."}
            return
        for ev in (_run_sql(question) if mode == "sql" else _run_etl(question)):
            if ev["type"] == "result":
                status = "ok" if ev.get("safe", True) else "blocked"
                history.add(question, mode, status)       # saved BEFORE the page asks for the history
                saved = True
            yield ev
    except Exception as e:                       # show a readable message in the page
        text = str(e)
        route = mode if mode in ("sql", "etl") else "sql"
        if "tool_use_failed" in text and route == "etl":     # the model answered in plain text instead of calling a tool
            m = re.search(r"'failed_generation': '(.*?)'\}", text, re.S)
            yield {"type": "result", "route": "etl", "files": [], "columns": [], "rows": [],
                   "answer": m.group(1) if m else "I could not use my tools for that. Please describe the ETL job, "
                                                  "for example: extract data from an API URL and save it as csv."}
            history.add(question, "etl", "ok")
            saved = True
        elif "tool_use_failed" in text:
            yield {"type": "error", "message": "The language model could not format its reply. Please ask the question again."}
        else:
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
    finally:
        if not saved:
            history.add(question, mode if mode in ("sql", "etl") else "", status)


# ------------------------------------------------ app ------------------------------------------------

app = FastAPI(title="LOGIX API")


@app.get("/api/health")
def health():
    return {"status": "ok", "etl_enabled": ETL_ENABLED}


@app.post("/api/ask/stream")
def ask_stream(req: Ask):
    def gen():
        for ev in _events(req):
            yield f"data: {json.dumps(ev, default=str)}\n\n"
    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/history")
def get_history(date: str = "", limit: int = 100):
    if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(400, "date must look like 2026-10-08")
    return history.query(date, max(1, min(limit, 500)))


@app.post("/api/ask")
def ask(req: Ask):
    """Same as /api/ask/stream but returns only the final JSON (handy for testing)."""
    out = {"type": "error", "message": "No result."}
    for ev in _events(req):
        if ev["type"] in ("result", "error"):
            out = ev
    return out


@app.get("/api/files/{fid}")
def download(fid: str, fmt: str = ""):
    path = FILES.get(fid)
    if not path or not path.exists():
        raise HTTPException(404, "File not found. Run the pipeline again.")
    ext = path.suffix.lstrip(".").lower()
    fmt = (fmt or ext).lower()
    if fmt not in ("csv", "json", "parquet"):
        raise HTTPException(400, "fmt must be csv, json or parquet")
    if fmt == ext:
        return FileResponse(path, filename=path.name)
    df = _read_table(path)
    if fmt == "csv":
        data, media = df.to_csv(index=False).encode("utf-8"), "text/csv"
    elif fmt == "json":
        data, media = df.to_json(orient="records", indent=2).encode("utf-8"), "application/json"
    else:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)        # needs pyarrow
        data, media = buf.getvalue(), "application/octet-stream"
    return Response(
        data, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{path.stem}.{fmt}"'},
    )


# The web page itself (must be mounted last)
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")