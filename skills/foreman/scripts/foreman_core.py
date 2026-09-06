"""Foreman semantic operations library.

Plain Python functions over a sqlite3.Connection implementing Foreman's
durable-work operations. foreman.py is a thin CLI wrapper around this module;
any other consumer (an adapter, a script, a future MCP server) can import it
directly instead of shelling out to the CLI.
"""
from __future__ import annotations
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / ".foreman" / "foreman.db"
SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"

ALLOWED_TRANSITIONS = {
    "draft": {"draft", "awaiting_plan_approval", "ready", "cancelled"},
    "awaiting_plan_approval": {"awaiting_plan_approval", "draft", "ready", "cancelled"},
    "ready": {"ready", "running", "blocked", "cancelled"},
    "running": {"running", "waiting", "blocked", "completed", "cancelled", "failed"},
    "waiting": {"waiting", "running", "ready", "cancelled", "failed"},
    "blocked": {"blocked", "ready", "running", "cancelled", "failed"},
    "completed": {"completed", "archived"},
    "cancelled": {"cancelled", "archived"},
    "failed": {"failed", "archived"},
    "archived": {"archived"},
}

AUTO_BLOCK_TAG = "[auto:dependency] "


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path(value: str | None) -> Path:
    p = Path(value).expanduser() if value else DEFAULT_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init_db(con):
    con.executescript(SCHEMA.read_text())
    con.commit()


def emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def validate_transition(current: str, new: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise SystemExit(f"unknown current status: {current}")
    if new not in allowed:
        raise SystemExit(
            f"invalid status transition: {current} -> {new} "
            f"(allowed from {current}: {sorted(allowed)})"
        )


def first_incomplete_step_id(con, task_id: str):
    row = con.execute(
        "SELECT id FROM steps WHERE task_id=? AND status!='completed' "
        "ORDER BY position LIMIT 1",
        (task_id,),
    ).fetchone()
    return row["id"] if row else None


@contextmanager
def transaction(con):
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def _get_task_or_die(con, task_id: str):
    task = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        raise SystemExit(f"task not found: {task_id}")
    return task


def get_context(con, task_id: str) -> dict:
    task = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        raise SystemExit(f"task not found: {task_id}")
    steps = con.execute(
        "SELECT id,title,status,result FROM steps WHERE task_id=? ORDER BY position",
        (task_id,),
    ).fetchall()
    decisions = con.execute(
        "SELECT text,created_at FROM decisions WHERE task_id=? ORDER BY created_at DESC LIMIT 10",
        (task_id,),
    ).fetchall()
    events = con.execute(
        """SELECT type,severity,summary,created_at FROM events
           WHERE task_id=? ORDER BY id DESC LIMIT 10""",
        (task_id,),
    ).fetchall()
    artifacts = con.execute(
        "SELECT path,description,created_at FROM artifacts WHERE task_id=? ORDER BY created_at DESC",
        (task_id,),
    ).fetchall()
    dependencies = con.execute(
        """SELECT t.id, t.title, t.status FROM dependencies d
           JOIN tasks t ON t.id = d.depends_on_task_id
           WHERE d.task_id = ? ORDER BY t.title""",
        (task_id,),
    ).fetchall()
    blocks = con.execute(
        """SELECT t.id, t.title, t.status FROM dependencies d
           JOIN tasks t ON t.id = d.task_id
           WHERE d.depends_on_task_id = ? ORDER BY t.title""",
        (task_id,),
    ).fetchall()
    return {
        "task": dict(task),
        "steps": [dict(x) for x in steps],
        "decisions": [dict(x) for x in decisions],
        "recent_events": [dict(x) for x in events],
        "artifacts": [dict(x) for x in artifacts],
        "dependencies": [dict(x) for x in dependencies],
        "blocks": [dict(x) for x in blocks],
    }


def create_work(con, *, title, objective, task_type="one_off", status="ready") -> dict:
    with transaction(con):
        task_id = str(uuid.uuid4())
        t = now()
        started_at = t if status == "running" else None
        completed_at = t if status == "completed" else None
        con.execute(
            """INSERT INTO tasks
               (id,title,objective,task_type,status,created_at,updated_at,started_at,completed_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (task_id, title, objective, task_type, status, t, t, started_at, completed_at),
        )
        con.execute(
            "INSERT INTO events(task_id,type,severity,summary,created_at) VALUES(?,?,?,?,?)",
            (task_id, "CREATED", "info", f"Created task: {title}", t),
        )
    return {"id": task_id, "status": status}


def update_work(con, task_id, *, status=None, progress=None, next_action=None,
                 blocked_reason=None, priority=None) -> dict:
    with transaction(con):
        task = _get_task_or_die(con, task_id)

        new_status = status
        if new_status is not None:
            validate_transition(task["status"], new_status)

        fields, vals = [], []
        for col, val in [
            ("status", new_status),
            ("progress", progress),
            ("next_action", next_action),
            ("priority", priority),
        ]:
            if val is not None:
                fields.append(f"{col}=?"); vals.append(val)

        if blocked_reason is not None:
            fields.append("blocked_reason=?"); vals.append(blocked_reason)
        elif new_status is not None and task["status"] == "blocked" and new_status != "blocked":
            fields.append("blocked_reason=?"); vals.append(None)

        if new_status == "running" and not task["started_at"]:
            fields.append("started_at=?"); vals.append(now())
        if new_status == "completed":
            fields.append("completed_at=?"); vals.append(now())
        if new_status == "running":
            fields.append("current_step_id=?"); vals.append(first_incomplete_step_id(con, task_id))
        elif new_status == "completed":
            fields.append("current_step_id=?"); vals.append(None)

        if not fields:
            raise SystemExit("no update fields supplied")
        fields.append("updated_at=?"); vals.append(now())
        vals.append(task_id)
        con.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", vals)

        if new_status == "completed":
            for row in con.execute(
                "SELECT task_id FROM dependencies WHERE depends_on_task_id=?", (task_id,)
            ).fetchall():
                _recompute_dependency_block(con, row["task_id"])

    return get_context(con, task_id)


def add_step(con, task_id, *, title) -> dict:
    with transaction(con):
        row = con.execute(
            "SELECT COALESCE(MAX(position),0)+1 AS p FROM steps WHERE task_id=?",
            (task_id,),
        ).fetchone()
        sid = str(uuid.uuid4())
        con.execute(
            """INSERT INTO steps(id,task_id,position,title,created_at)
               VALUES(?,?,?,?,?)""",
            (sid, task_id, row["p"], title, now()),
        )
    return {"step_id": sid}


def complete_step(con, task_id, step_id, *, result="") -> dict:
    t = now()
    with transaction(con):
        step = con.execute(
            "SELECT * FROM steps WHERE id=? AND task_id=?",
            (step_id, task_id),
        ).fetchone()
        if step is None:
            raise SystemExit(f"step not found: {step_id} for task {task_id}")

        already_completed = step["status"] == "completed"
        if not already_completed:
            cur = con.execute(
                """UPDATE steps SET status='completed',result=?,completed_at=?
                   WHERE id=? AND task_id=? AND status!='completed'""",
                (result, t, step_id, task_id),
            )
            already_completed = cur.rowcount == 0

        if already_completed:
            if result != step["result"]:
                con.execute("UPDATE steps SET result=? WHERE id=?", (result, step_id))
            ctx = get_context(con, task_id)
            ctx["idempotent"] = True
            return ctx

        total = con.execute(
            "SELECT COUNT(*) n FROM steps WHERE task_id=?", (task_id,)
        ).fetchone()["n"]
        done = con.execute(
            "SELECT COUNT(*) n FROM steps WHERE task_id=? AND status='completed'",
            (task_id,),
        ).fetchone()["n"]
        progress = done / total if total else 1.0
        task = con.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()

        fields, vals = ["progress=?", "updated_at=?"], [progress, t]
        became_completed = False
        if task["status"] == "running":
            new_status = "completed" if total and done == total else "running"
            fields.append("status=?"); vals.append(new_status)
            if new_status == "completed":
                fields.append("completed_at=?"); vals.append(t)
                fields.append("current_step_id=?"); vals.append(None)
                became_completed = True
            else:
                fields.append("current_step_id=?")
                vals.append(first_incomplete_step_id(con, task_id))
        else:
            fields.append("current_step_id=?")
            vals.append(first_incomplete_step_id(con, task_id))
        vals.append(task_id)
        con.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", vals)

        con.execute(
            """INSERT INTO events(task_id,type,severity,summary,created_at)
               VALUES(?,?,?,?,?)""",
            (task_id, "STEP_COMPLETED", "info", f"Completed step {step_id}", t),
        )

        if became_completed:
            for row in con.execute(
                "SELECT task_id FROM dependencies WHERE depends_on_task_id=?", (task_id,)
            ).fetchall():
                _recompute_dependency_block(con, row["task_id"])

    return get_context(con, task_id)


def record_decision(con, task_id, *, text) -> dict:
    with transaction(con):
        con.execute(
            "INSERT INTO decisions(id,task_id,text,created_at) VALUES(?,?,?,?)",
            (str(uuid.uuid4()), task_id, text, now()),
        )
    return {"ok": True}


def record_event(con, task_id, *, type, summary, severity="info") -> dict:
    with transaction(con):
        con.execute(
            """INSERT INTO events(task_id,type,severity,summary,created_at)
               VALUES(?,?,?,?,?)""",
            (task_id, type, severity, summary, now()),
        )
    return {"ok": True}


def attach_artifact(con, task_id, *, path, description="") -> dict:
    with transaction(con):
        con.execute(
            """INSERT INTO artifacts(id,task_id,path,description,created_at)
               VALUES(?,?,?,?,?)""",
            (str(uuid.uuid4()), task_id, path, description, now()),
        )
    return {"ok": True}


def search_work(con, query) -> list:
    q = f"%{query}%"
    rows = con.execute(
        """SELECT id,title,status,progress,next_action,updated_at
           FROM tasks WHERE title LIKE ? OR objective LIKE ?
           ORDER BY updated_at DESC LIMIT 20""",
        (q, q),
    ).fetchall()
    return [dict(r) for r in rows]


def list_work(con, status=None) -> list:
    if status:
        rows = con.execute(
            """SELECT id,title,status,progress,next_action,updated_at
               FROM tasks WHERE status=? ORDER BY priority DESC,updated_at DESC""",
            (status,),
        ).fetchall()
    else:
        rows = con.execute(
            """SELECT id,title,status,progress,next_action,updated_at
               FROM tasks WHERE status NOT IN ('completed','cancelled','archived')
               ORDER BY priority DESC,updated_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def _incomplete_dependencies(con, task_id: str) -> list:
    rows = con.execute(
        """SELECT t.id, t.title, t.status FROM dependencies d
           JOIN tasks t ON t.id = d.depends_on_task_id
           WHERE d.task_id = ? AND t.status != 'completed'
           ORDER BY t.title""",
        (task_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _would_create_cycle(con, task_id: str, depends_on_task_id: str) -> bool:
    seen = set()
    stack = [depends_on_task_id]
    while stack:
        node = stack.pop()
        if node == task_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        rows = con.execute(
            "SELECT depends_on_task_id FROM dependencies WHERE task_id=?", (node,)
        ).fetchall()
        stack.extend(r["depends_on_task_id"] for r in rows)
    return False


def _recompute_dependency_block(con, task_id: str) -> None:
    task = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if task is None:
        return
    incomplete = _incomplete_dependencies(con, task_id)
    status = task["status"]
    reason = task["blocked_reason"] or ""
    t = now()

    if incomplete:
        can_auto_block = "blocked" in ALLOWED_TRANSITIONS.get(status, set())
        waiting_on = ", ".join(
            f"{d['title']} ({d['id']}, status={d['status']})" for d in incomplete
        )
        if can_auto_block and status != "blocked":
            con.execute(
                "UPDATE tasks SET status='blocked', blocked_reason=?, updated_at=? WHERE id=?",
                (AUTO_BLOCK_TAG + f"waiting on: {waiting_on}", t, task_id),
            )
            con.execute(
                """INSERT INTO events(task_id,type,severity,summary,created_at)
                   VALUES(?,?,?,?,?)""",
                (task_id, "BLOCKED", "info", "Auto-blocked: unresolved dependency", t),
            )
        elif status == "blocked" and reason.startswith(AUTO_BLOCK_TAG):
            con.execute(
                "UPDATE tasks SET blocked_reason=?, updated_at=? WHERE id=?",
                (AUTO_BLOCK_TAG + f"waiting on: {waiting_on}", t, task_id),
            )
        # else: draft/awaiting_plan_approval (blocked unreachable), or blocked for an
        # unrelated/manual reason -> leave alone.
    else:
        if status == "blocked" and reason.startswith(AUTO_BLOCK_TAG):
            con.execute(
                "UPDATE tasks SET status='ready', blocked_reason=NULL, updated_at=? WHERE id=?",
                (t, task_id),
            )
            con.execute(
                """INSERT INTO events(task_id,type,severity,summary,created_at)
                   VALUES(?,?,?,?,?)""",
                (task_id, "UNBLOCKED", "info", "Auto-unblocked: dependencies satisfied", t),
            )


def add_dependency(con, task_id, depends_on_task_id) -> dict:
    with transaction(con):
        _get_task_or_die(con, task_id)
        _get_task_or_die(con, depends_on_task_id)
        if task_id == depends_on_task_id:
            raise SystemExit(f"cannot create self-dependency: {task_id}")

        exists = con.execute(
            "SELECT 1 FROM dependencies WHERE task_id=? AND depends_on_task_id=?",
            (task_id, depends_on_task_id),
        ).fetchone()
        idempotent = exists is not None

        if not idempotent:
            if _would_create_cycle(con, task_id, depends_on_task_id):
                raise SystemExit(
                    f"adding dependency {task_id} -> {depends_on_task_id} would "
                    f"create a cycle in the dependency graph"
                )
            con.execute(
                "INSERT INTO dependencies(task_id, depends_on_task_id, created_at) VALUES (?,?,?)",
                (task_id, depends_on_task_id, now()),
            )
        _recompute_dependency_block(con, task_id)

    result = get_context(con, task_id)
    if idempotent:
        result["idempotent"] = True
    return result


def remove_dependency(con, task_id, depends_on_task_id) -> dict:
    with transaction(con):
        _get_task_or_die(con, task_id)
        con.execute(
            "DELETE FROM dependencies WHERE task_id=? AND depends_on_task_id=?",
            (task_id, depends_on_task_id),
        )
        _recompute_dependency_block(con, task_id)
    return get_context(con, task_id)


def get_dependencies(con, task_id) -> dict:
    _get_task_or_die(con, task_id)
    depends_on = con.execute(
        """SELECT t.id, t.title, t.status FROM dependencies d
           JOIN tasks t ON t.id = d.depends_on_task_id
           WHERE d.task_id=? ORDER BY t.title""",
        (task_id,),
    ).fetchall()
    blocks = con.execute(
        """SELECT t.id, t.title, t.status FROM dependencies d
           JOIN tasks t ON t.id = d.task_id
           WHERE d.depends_on_task_id=? ORDER BY t.title""",
        (task_id,),
    ).fetchall()
    return {
        "depends_on": [dict(r) for r in depends_on],
        "blocks": [dict(r) for r in blocks],
    }


def check_blockers(con, task_id) -> dict:
    _get_task_or_die(con, task_id)
    return {"task_id": task_id, "incomplete_dependencies": _incomplete_dependencies(con, task_id)}


def pause_work(con, task_id, *, reason=None) -> dict:
    with transaction(con):
        task = _get_task_or_die(con, task_id)
        validate_transition(task["status"], "waiting")
        t = now()
        con.execute("UPDATE tasks SET status='waiting', updated_at=? WHERE id=?", (t, task_id))
        summary = "Paused" + (f": {reason}" if reason else "")
        con.execute(
            "INSERT INTO events(task_id,type,severity,summary,created_at) VALUES(?,?,?,?,?)",
            (task_id, "PAUSED", "info", summary, t),
        )
    return get_context(con, task_id)


def resume_work(con, task_id) -> dict:
    with transaction(con):
        task = _get_task_or_die(con, task_id)
        validate_transition(task["status"], "running")
        incomplete = _incomplete_dependencies(con, task_id)
        if incomplete:
            first = incomplete[0]
            raise SystemExit(
                f"cannot resume {task_id}: blocked by incomplete dependency "
                f"{first['id']} ({first['title']}, status={first['status']})"
            )
        t = now()
        fields, vals = ["status=?", "updated_at=?"], ["running", t]
        if not task["started_at"]:
            fields.append("started_at=?"); vals.append(t)
        fields.append("current_step_id=?"); vals.append(first_incomplete_step_id(con, task_id))
        vals.append(task_id)
        con.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", vals)
        con.execute(
            "INSERT INTO events(task_id,type,severity,summary,created_at) VALUES(?,?,?,?,?)",
            (task_id, "RESUMED", "info", "Resumed", t),
        )
    return get_context(con, task_id)


def cancel_work(con, task_id, *, reason=None) -> dict:
    with transaction(con):
        task = _get_task_or_die(con, task_id)
        validate_transition(task["status"], "cancelled")
        t = now()
        con.execute("UPDATE tasks SET status='cancelled', updated_at=? WHERE id=?", (t, task_id))
        summary = "Cancelled" + (f": {reason}" if reason else "")
        con.execute(
            "INSERT INTO events(task_id,type,severity,summary,created_at) VALUES(?,?,?,?,?)",
            (task_id, "CANCELLED", "info", summary, t),
        )
    return get_context(con, task_id)
