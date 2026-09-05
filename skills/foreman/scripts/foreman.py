#!/usr/bin/env python3
"""Minimal deterministic Foreman v0.1 SQLite CLI."""

from __future__ import annotations
import argparse
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / ".foreman" / "foreman.db"
SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path(value: str | None) -> Path:
    p = Path(value).expanduser() if value else DEFAULT_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(con):
    con.executescript(SCHEMA.read_text())
    con.commit()


def emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def task_context(con, task_id: str):
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
    return {
        "task": dict(task),
        "steps": [dict(x) for x in steps],
        "decisions": [dict(x) for x in decisions],
        "recent_events": [dict(x) for x in events],
        "artifacts": [dict(x) for x in artifacts],
    }


def main():
    ap = argparse.ArgumentParser(prog="foreman")
    ap.add_argument("--db", help="SQLite path")
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp.add_parser("init")

    p = sp.add_parser("create")
    p.add_argument("--title", required=True)
    p.add_argument("--objective", required=True)
    p.add_argument("--type", default="one_off")
    p.add_argument("--status", default="ready", choices=[
        "draft","awaiting_plan_approval","ready","running","waiting","blocked",
        "completed","cancelled","failed","archived"
    ])

    p = sp.add_parser("search")
    p.add_argument("query")

    p = sp.add_parser("context")
    p.add_argument("task_id")

    p = sp.add_parser("update")
    p.add_argument("task_id")
    p.add_argument("--status")
    p.add_argument("--progress", type=float)
    p.add_argument("--next-action")
    p.add_argument("--blocked-reason")
    p.add_argument("--priority", type=int)

    p = sp.add_parser("add-step")
    p.add_argument("task_id")
    p.add_argument("--title", required=True)

    p = sp.add_parser("complete-step")
    p.add_argument("task_id")
    p.add_argument("step_id")
    p.add_argument("--result", default="")

    p = sp.add_parser("decision")
    p.add_argument("task_id")
    p.add_argument("--text", required=True)

    p = sp.add_parser("event")
    p.add_argument("task_id")
    p.add_argument("--type", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--severity", default="info",
                   choices=["info","meaningful","action_required","critical"])

    p = sp.add_parser("artifact")
    p.add_argument("task_id")
    p.add_argument("--path", required=True)
    p.add_argument("--description", default="")

    p = sp.add_parser("list")
    p.add_argument("--status")

    args = ap.parse_args()
    path = db_path(args.db)
    con = connect(path)
    init_db(con)

    if args.cmd == "init":
        emit({"ok": True, "db": str(path)})
        return

    if args.cmd == "create":
        task_id = str(uuid.uuid4())
        t = now()
        con.execute(
            """INSERT INTO tasks
               (id,title,objective,task_type,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (task_id,args.title,args.objective,args.type,args.status,t,t)
        )
        con.execute(
            "INSERT INTO events(task_id,type,severity,summary,created_at) VALUES(?,?,?,?,?)",
            (task_id,"CREATED","info",f"Created task: {args.title}",t)
        )
        con.commit()
        emit({"id": task_id, "status": args.status})
        return

    if args.cmd == "search":
        q = f"%{args.query}%"
        rows = con.execute(
            """SELECT id,title,status,progress,next_action,updated_at
               FROM tasks WHERE title LIKE ? OR objective LIKE ?
               ORDER BY updated_at DESC LIMIT 20""", (q,q)
        ).fetchall()
        emit([dict(r) for r in rows])
        return

    if args.cmd == "context":
        emit(task_context(con, args.task_id))
        return

    if args.cmd == "update":
        fields, vals = [], []
        for col, val in [
            ("status", args.status),
            ("progress", args.progress),
            ("next_action", args.next_action),
            ("blocked_reason", args.blocked_reason),
            ("priority", args.priority),
        ]:
            if val is not None:
                fields.append(f"{col}=?"); vals.append(val)
        if not fields:
            raise SystemExit("no update fields supplied")
        fields.append("updated_at=?"); vals.append(now())
        vals.append(args.task_id)
        con.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", vals)
        con.commit()
        emit(task_context(con, args.task_id))
        return

    if args.cmd == "add-step":
        row = con.execute(
            "SELECT COALESCE(MAX(position),0)+1 AS p FROM steps WHERE task_id=?",
            (args.task_id,)
        ).fetchone()
        sid = str(uuid.uuid4())
        con.execute(
            """INSERT INTO steps(id,task_id,position,title,created_at)
               VALUES(?,?,?,?,?)""",
            (sid,args.task_id,row["p"],args.title,now())
        )
        con.commit()
        emit({"step_id": sid})
        return

    if args.cmd == "complete-step":
        t = now()
        con.execute(
            "UPDATE steps SET status='completed',result=?,completed_at=? WHERE id=? AND task_id=?",
            (args.result,t,args.step_id,args.task_id)
        )
        total = con.execute(
            "SELECT COUNT(*) n FROM steps WHERE task_id=?", (args.task_id,)
        ).fetchone()["n"]
        done = con.execute(
            "SELECT COUNT(*) n FROM steps WHERE task_id=? AND status='completed'",
            (args.task_id,)
        ).fetchone()["n"]
        progress = done / total if total else 1.0
        status = "completed" if total and done == total else "running"
        con.execute(
            "UPDATE tasks SET progress=?,status=?,updated_at=? WHERE id=?",
            (progress,status,t,args.task_id)
        )
        con.execute(
            """INSERT INTO events(task_id,type,severity,summary,created_at)
               VALUES(?,?,?,?,?)""",
            (args.task_id,"STEP_COMPLETED","info",f"Completed step {args.step_id}",t)
        )
        con.commit()
        emit(task_context(con, args.task_id))
        return

    if args.cmd == "decision":
        con.execute(
            "INSERT INTO decisions(id,task_id,text,created_at) VALUES(?,?,?,?)",
            (str(uuid.uuid4()),args.task_id,args.text,now())
        )
        con.commit()
        emit({"ok": True})
        return

    if args.cmd == "event":
        con.execute(
            """INSERT INTO events(task_id,type,severity,summary,created_at)
               VALUES(?,?,?,?,?)""",
            (args.task_id,args.type,args.severity,args.summary,now())
        )
        con.commit()
        emit({"ok": True})
        return

    if args.cmd == "artifact":
        con.execute(
            """INSERT INTO artifacts(id,task_id,path,description,created_at)
               VALUES(?,?,?,?,?)""",
            (str(uuid.uuid4()),args.task_id,args.path,args.description,now())
        )
        con.commit()
        emit({"ok": True})
        return

    if args.cmd == "list":
        if args.status:
            rows = con.execute(
                """SELECT id,title,status,progress,next_action,updated_at
                   FROM tasks WHERE status=? ORDER BY priority DESC,updated_at DESC""",
                (args.status,)
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT id,title,status,progress,next_action,updated_at
                   FROM tasks WHERE status NOT IN ('completed','cancelled','archived')
                   ORDER BY priority DESC,updated_at DESC"""
            ).fetchall()
        emit([dict(r) for r in rows])


if __name__ == "__main__":
    main()
