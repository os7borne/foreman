#!/usr/bin/env python3
"""Minimal deterministic Foreman v0.1 SQLite CLI.

Thin argparse wrapper over foreman_core.py, which holds the actual
semantic operations (create_work, get_context, update_work, ...).
"""

from __future__ import annotations
import argparse
import sqlite3

import foreman_core as core
from foreman_core import (  # re-exported for direct callers/tests
    DEFAULT_DB, ALLOWED_TRANSITIONS, now, db_path, connect, init_db,
    emit, validate_transition, first_incomplete_step_id, transaction,
)


def dispatch(con, args, path):
    if args.cmd == "init":
        emit({"ok": True, "db": str(path)})
        return

    if args.cmd == "create":
        emit(core.create_work(
            con, title=args.title, objective=args.objective,
            task_type=args.type, status=args.status,
        ))
        return

    if args.cmd == "search":
        emit(core.search_work(con, args.query))
        return

    if args.cmd == "context":
        emit(core.get_context(con, args.task_id))
        return

    if args.cmd == "update":
        emit(core.update_work(
            con, args.task_id, status=args.status, progress=args.progress,
            next_action=args.next_action, blocked_reason=args.blocked_reason,
            priority=args.priority,
        ))
        return

    if args.cmd == "add-step":
        emit(core.add_step(con, args.task_id, title=args.title))
        return

    if args.cmd == "complete-step":
        emit(core.complete_step(con, args.task_id, args.step_id, result=args.result))
        return

    if args.cmd == "decision":
        emit(core.record_decision(con, args.task_id, text=args.text))
        return

    if args.cmd == "event":
        emit(core.record_event(
            con, args.task_id, type=args.type, summary=args.summary, severity=args.severity,
        ))
        return

    if args.cmd == "artifact":
        emit(core.attach_artifact(con, args.task_id, path=args.path, description=args.description))
        return

    if args.cmd == "list":
        emit(core.list_work(con, status=args.status))
        return

    if args.cmd == "add-dependency":
        emit(core.add_dependency(con, args.task_id, args.depends_on))
        return

    if args.cmd == "remove-dependency":
        emit(core.remove_dependency(con, args.task_id, args.depends_on))
        return

    if args.cmd == "check-blockers":
        emit(core.check_blockers(con, args.task_id))
        return

    if args.cmd == "pause":
        emit(core.pause_work(con, args.task_id, reason=args.reason))
        return

    if args.cmd == "resume":
        emit(core.resume_work(con, args.task_id))
        return

    if args.cmd == "cancel":
        emit(core.cancel_work(con, args.task_id, reason=args.reason))
        return


def main(argv=None):
    ap = argparse.ArgumentParser(prog="foreman")
    ap.add_argument("--db", help="SQLite path")
    sp = ap.add_subparsers(dest="cmd", required=True)

    STATUS_CHOICES = [
        "draft","awaiting_plan_approval","ready","running","waiting","blocked",
        "completed","cancelled","failed","archived"
    ]

    sp.add_parser("init")

    p = sp.add_parser("create")
    p.add_argument("--title", required=True)
    p.add_argument("--objective", required=True)
    p.add_argument("--type", default="one_off")
    p.add_argument("--status", default="ready", choices=STATUS_CHOICES)

    p = sp.add_parser("search")
    p.add_argument("query")

    p = sp.add_parser("context")
    p.add_argument("task_id")

    p = sp.add_parser("update")
    p.add_argument("task_id")
    p.add_argument("--status", choices=STATUS_CHOICES)
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

    p = sp.add_parser("add-dependency")
    p.add_argument("task_id")
    p.add_argument("--depends-on", required=True, dest="depends_on")

    p = sp.add_parser("remove-dependency")
    p.add_argument("task_id")
    p.add_argument("--depends-on", required=True, dest="depends_on")

    p = sp.add_parser("check-blockers")
    p.add_argument("task_id")

    p = sp.add_parser("pause")
    p.add_argument("task_id")
    p.add_argument("--reason", default=None)

    p = sp.add_parser("resume")
    p.add_argument("task_id")

    p = sp.add_parser("cancel")
    p.add_argument("task_id")
    p.add_argument("--reason", default=None)

    args = ap.parse_args(argv)
    path = db_path(args.db)
    con = connect(path)
    init_db(con)

    try:
        dispatch(con, args, path)
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            raise SystemExit(f"database is locked (busy_timeout exceeded): {e}") from e
        raise


if __name__ == "__main__":
    main()
