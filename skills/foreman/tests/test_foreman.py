#!/usr/bin/env python3
"""Automated battle tests for the Foreman CLI.

Exercises the behaviors described narratively in tests/contract-test.md and
tests/smoke-test.md: lifecycle transitions, timestamp/current_step_id
maintenance, complete-step idempotency, concurrency, and cross-session
context reconstruction. Runs with stdlib unittest only.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
FOREMAN_PY = SCRIPTS_DIR / "foreman.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import foreman  # noqa: E402


class ForemanTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / "foreman.db")

    def tearDown(self):
        self._tmpdir.cleanup()

    def run_cli(self, *args) -> dict:
        buf = io.StringIO()
        argv = ["--db", self.db_path, *args]
        with contextlib.redirect_stdout(buf):
            foreman.main(argv)
        return json.loads(buf.getvalue())

    def run_cli_raises(self, *args) -> str:
        argv = ["--db", self.db_path, *args]
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                foreman.main(argv)
        return str(ctx.exception)

    def create_task(self, status: str | None = None, title: str = "t") -> str:
        args = ["create", "--title", title, "--objective", "obj"]
        if status:
            args += ["--status", status]
        return self.run_cli(*args)["id"]

    def add_step(self, task_id: str, title: str = "step") -> str:
        return self.run_cli("add-step", task_id, "--title", title)["step_id"]


class TestLifecycleTransitions(ForemanTestCase):
    def test_valid_transition_ready_to_running_sets_started_at(self):
        tid = self.create_task()
        ctx = self.run_cli("update", tid, "--status", "running")
        self.assertEqual(ctx["task"]["status"], "running")
        self.assertIsNotNone(ctx["task"]["started_at"])

    def test_invalid_transition_completed_to_running_rejected(self):
        tid = self.create_task()
        self.run_cli("update", tid, "--status", "running")
        self.run_cli("update", tid, "--status", "completed")
        msg = self.run_cli_raises("update", tid, "--status", "running")
        self.assertIn("invalid status transition", msg)

    def test_invalid_status_string_rejected_by_argparse_choices(self):
        tid = self.create_task()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                foreman.main(["--db", self.db_path, "update", tid, "--status", "banana"])

    def test_self_transition_is_noop_allowed(self):
        tid = self.create_task()
        ctx = self.run_cli("update", tid, "--status", "ready")
        self.assertEqual(ctx["task"]["status"], "ready")

    def test_ready_running_blocked_ready_running_cycle_preserves_started_at(self):
        tid = self.create_task()
        ctx = self.run_cli("update", tid, "--status", "running")
        first_started = ctx["task"]["started_at"]
        self.run_cli("update", tid, "--status", "blocked", "--blocked-reason", "waiting on X")
        self.run_cli("update", tid, "--status", "ready")
        ctx = self.run_cli("update", tid, "--status", "running")
        self.assertEqual(ctx["task"]["started_at"], first_started)

    def test_terminal_states_reject_non_archive_transitions(self):
        tid = self.create_task()
        self.run_cli("update", tid, "--status", "running")
        self.run_cli("update", tid, "--status", "cancelled")
        msg = self.run_cli_raises("update", tid, "--status", "ready")
        self.assertIn("invalid status transition", msg)

    def test_archived_is_fully_terminal(self):
        tid = self.create_task()
        self.run_cli("update", tid, "--status", "running")
        self.run_cli("update", tid, "--status", "failed")
        self.run_cli("update", tid, "--status", "archived")
        msg = self.run_cli_raises("update", tid, "--status", "ready")
        self.assertIn("invalid status transition", msg)


class TestTimestampAndCurrentStep(ForemanTestCase):
    def test_started_at_only_set_once(self):
        tid = self.create_task()
        ctx = self.run_cli("update", tid, "--status", "running")
        started_at = ctx["task"]["started_at"]
        self.run_cli("update", tid, "--status", "blocked")
        ctx = self.run_cli("update", tid, "--status", "running")
        self.assertEqual(ctx["task"]["started_at"], started_at)

    def test_completed_at_set_on_completion(self):
        tid = self.create_task()
        self.run_cli("update", tid, "--status", "running")
        ctx = self.run_cli("update", tid, "--status", "completed")
        self.assertIsNotNone(ctx["task"]["completed_at"])

    def test_current_step_id_advances_as_steps_complete(self):
        tid = self.create_task()
        s1 = self.add_step(tid, "one")
        s2 = self.add_step(tid, "two")
        ctx = self.run_cli("update", tid, "--status", "running")
        self.assertEqual(ctx["task"]["current_step_id"], s1)
        ctx = self.run_cli("complete-step", tid, s1)
        self.assertEqual(ctx["task"]["current_step_id"], s2)
        ctx = self.run_cli("complete-step", tid, s2)
        self.assertIsNone(ctx["task"]["current_step_id"])
        self.assertEqual(ctx["task"]["status"], "completed")

    def test_blocked_reason_autoclears_on_leaving_blocked(self):
        tid = self.create_task()
        self.run_cli("update", tid, "--status", "running")
        self.run_cli("update", tid, "--status", "blocked", "--blocked-reason", "waiting")
        ctx = self.run_cli("update", tid, "--status", "ready")
        self.assertIsNone(ctx["task"]["blocked_reason"])


class TestCompleteStepIdempotency(ForemanTestCase):
    def test_complete_step_twice_is_idempotent_no_duplicate_event(self):
        tid = self.create_task()
        sid = self.add_step(tid)
        self.run_cli("update", tid, "--status", "running")
        self.run_cli("complete-step", tid, sid, "--result", "done")
        ctx = self.run_cli("complete-step", tid, sid, "--result", "done")
        self.assertTrue(ctx.get("idempotent"))
        events = [e for e in ctx["recent_events"] if e["type"] == "STEP_COMPLETED"]
        self.assertEqual(len(events), 1)

    def test_complete_step_retry_with_different_result_keeps_last_write(self):
        tid = self.create_task()
        sid = self.add_step(tid)
        self.run_cli("update", tid, "--status", "running")
        self.run_cli("complete-step", tid, sid, "--result", "first")
        ctx = self.run_cli("complete-step", tid, sid, "--result", "second")
        self.assertTrue(ctx.get("idempotent"))
        step = next(s for s in ctx["steps"] if s["id"] == sid)
        self.assertEqual(step["result"], "second")
        events = [e for e in ctx["recent_events"] if e["type"] == "STEP_COMPLETED"]
        self.assertEqual(len(events), 1)

    def test_complete_nonexistent_step_id_raises_clear_error(self):
        tid = self.create_task()
        msg = self.run_cli_raises("complete-step", tid, str(uuid.uuid4()))
        self.assertIn("step not found", msg)

    def test_complete_step_wrong_task_id_raises_error(self):
        tid1 = self.create_task()
        tid2 = self.create_task()
        sid = self.add_step(tid1)
        msg = self.run_cli_raises("complete-step", tid2, sid)
        self.assertIn("step not found", msg)

    def test_complete_step_does_not_resurrect_cancelled_task(self):
        tid = self.create_task()
        sid = self.add_step(tid)
        self.run_cli("update", tid, "--status", "running")
        self.run_cli("update", tid, "--status", "cancelled")
        ctx = self.run_cli("complete-step", tid, sid, "--result", "done")
        self.assertEqual(ctx["task"]["status"], "cancelled")
        step = next(s for s in ctx["steps"] if s["id"] == sid)
        self.assertEqual(step["status"], "completed")


class TestConcurrency(ForemanTestCase):
    def _cli_subprocess(self, *args):
        return subprocess.run(
            [sys.executable, str(FOREMAN_PY), "--db", self.db_path, *args],
            capture_output=True, text=True,
        )

    def test_wal_mode_and_busy_timeout_configured(self):
        con = foreman.connect(Path(self.db_path))
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = con.execute("PRAGMA busy_timeout").fetchone()[0]
        con.close()
        self.assertEqual(mode.lower(), "wal")
        self.assertEqual(timeout, 5000)

    def test_concurrent_complete_step_different_steps_no_lock_errors(self):
        tid = self.create_task()
        step_ids = [self.add_step(tid, f"s{i}") for i in range(6)]
        self.run_cli("update", tid, "--status", "running")

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(
                lambda sid: self._cli_subprocess("complete-step", tid, sid),
                step_ids,
            ))

        for r in results:
            self.assertEqual(r.returncode, 0, msg=r.stderr)

        ctx = self.run_cli("context", tid)
        self.assertTrue(all(s["status"] == "completed" for s in ctx["steps"]))
        self.assertEqual(ctx["task"]["status"], "completed")
        self.assertEqual(ctx["task"]["progress"], 1.0)

    def test_concurrent_duplicate_complete_step_same_step_only_one_event(self):
        tid = self.create_task()
        sid = self.add_step(tid)
        self.run_cli("update", tid, "--status", "running")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: self._cli_subprocess("complete-step", tid, sid, "--result", "done"),
                range(8),
            ))

        for r in results:
            self.assertEqual(r.returncode, 0, msg=r.stderr)

        con = sqlite3.connect(self.db_path)
        n = con.execute(
            "SELECT COUNT(*) FROM events WHERE task_id=? AND type='STEP_COMPLETED'",
            (tid,),
        ).fetchone()[0]
        con.close()
        self.assertEqual(n, 1)


class TestArtifactAndDecisionContinuity(ForemanTestCase):
    def test_artifact_and_decision_persist_and_appear_in_context(self):
        tid = self.create_task()
        self.run_cli("decision", tid, "--text", "use approach A")
        self.run_cli("artifact", tid, "--path", "research.md", "--description", "notes")
        ctx = self.run_cli("context", tid)
        self.assertEqual(len(ctx["decisions"]), 1)
        self.assertEqual(ctx["decisions"][0]["text"], "use approach A")
        self.assertEqual(len(ctx["artifacts"]), 1)
        self.assertEqual(ctx["artifacts"][0]["path"], "research.md")

    def test_cross_session_context_reconstruction_end_to_end(self):
        tid = self.create_task(title="Investment memo")
        s1 = self.add_step(tid, "market sizing")
        s2 = self.add_step(tid, "competitive landscape")
        s3 = self.add_step(tid, "validate ARR")
        self.run_cli("update", tid, "--status", "running")
        self.run_cli("decision", tid, "--text", "exclude public companies")
        self.run_cli("complete-step", tid, s1, "--result", "sized at $2B")
        self.run_cli("complete-step", tid, s2, "--result", "5 competitors identified")
        self.run_cli("artifact", tid, "--path", "companies.csv", "--description", "shortlist")

        # Simulate "agent B" resuming with only the task id, as an independent read.
        ctx = self.run_cli("context", tid)
        self.assertEqual(ctx["task"]["status"], "running")
        self.assertEqual(ctx["task"]["current_step_id"], s3)
        self.assertAlmostEqual(ctx["task"]["progress"], 2 / 3)
        self.assertEqual(len(ctx["decisions"]), 1)
        self.assertEqual(len(ctx["artifacts"]), 1)
        completed_titles = {s["title"] for s in ctx["steps"] if s["status"] == "completed"}
        self.assertEqual(completed_titles, {"market sizing", "competitive landscape"})


class TestBackwardCompatibility(ForemanTestCase):
    def test_create_list_search_unchanged(self):
        tid = self.create_task(title="Alpha")
        created = self.run_cli("create", "--title", "Alpha", "--objective", "obj")
        self.assertIn("id", created)
        self.assertIn("status", created)

        listed = self.run_cli("list")
        self.assertTrue(any(t["id"] == tid for t in listed))
        self.assertEqual(
            set(listed[0].keys()),
            {"id", "title", "status", "progress", "next_action", "updated_at"},
        )

        found = self.run_cli("search", "Alpha")
        self.assertTrue(any(t["id"] == tid for t in found))

    def test_context_and_update_json_shape_unchanged(self):
        tid = self.create_task()
        ctx = self.run_cli("context", tid)
        self.assertEqual(
            set(ctx.keys()),
            {"task", "steps", "decisions", "recent_events", "artifacts",
             "dependencies", "blocks"},
        )
        updated = self.run_cli("update", tid, "--next-action", "do the thing")
        self.assertEqual(updated["task"]["next_action"], "do the thing")


class TestDependencyAutoBlockUnblock(ForemanTestCase):
    def test_add_dependency_on_incomplete_task_autoblocks_dependent(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        ctx = self.run_cli("add-dependency", a, "--depends-on", b)
        self.assertEqual(ctx["task"]["status"], "blocked")
        self.assertTrue(ctx["task"]["blocked_reason"].startswith("[auto:dependency]"))
        self.assertEqual(ctx["dependencies"], [{"id": b, "title": "B", "status": "ready"}])

    def test_auto_unblock_when_dependency_completed(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        self.run_cli("add-dependency", a, "--depends-on", b)
        self.run_cli("update", b, "--status", "running")
        ctx = self.run_cli("update", b, "--status", "completed")
        ctx_a = self.run_cli("context", a)
        self.assertEqual(ctx_a["task"]["status"], "ready")
        self.assertIsNone(ctx_a["task"]["blocked_reason"])

    def test_auto_unblock_when_dependency_removed(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        self.run_cli("add-dependency", a, "--depends-on", b)
        ctx = self.run_cli("remove-dependency", a, "--depends-on", b)
        self.assertEqual(ctx["task"]["status"], "ready")
        self.assertIsNone(ctx["task"]["blocked_reason"])

    def test_cancelled_dependency_does_not_satisfy(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        self.run_cli("add-dependency", a, "--depends-on", b)
        self.run_cli("update", b, "--status", "cancelled")
        ctx_a = self.run_cli("context", a)
        self.assertEqual(ctx_a["task"]["status"], "blocked")
        blockers = self.run_cli("check-blockers", a)
        self.assertEqual(len(blockers["incomplete_dependencies"]), 1)
        self.assertEqual(blockers["incomplete_dependencies"][0]["status"], "cancelled")

    def test_manually_blocked_reason_not_autounblocked_by_unrelated_dependency(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        self.run_cli("add-dependency", a, "--depends-on", b)
        self.run_cli("update", a, "--status", "blocked", "--blocked-reason", "manual: waiting on legal")
        self.run_cli("update", b, "--status", "running")
        self.run_cli("update", b, "--status", "completed")
        ctx_a = self.run_cli("context", a)
        self.assertEqual(ctx_a["task"]["status"], "blocked")
        self.assertEqual(ctx_a["task"]["blocked_reason"], "manual: waiting on legal")

    def test_duplicate_dependency_add_is_idempotent(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        self.run_cli("add-dependency", a, "--depends-on", b)
        ctx = self.run_cli("add-dependency", a, "--depends-on", b)
        self.assertTrue(ctx.get("idempotent"))
        self.assertEqual(len(ctx["dependencies"]), 1)

    def test_remove_nonexistent_dependency_is_noop(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        ctx = self.run_cli("remove-dependency", a, "--depends-on", b)
        self.assertEqual(ctx["task"]["status"], "ready")

    def test_context_includes_dependencies_and_blocks_arrays(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        self.run_cli("add-dependency", a, "--depends-on", b)
        ctx_a = self.run_cli("context", a)
        ctx_b = self.run_cli("context", b)
        self.assertEqual(ctx_a["dependencies"], [{"id": b, "title": "B", "status": "ready"}])
        self.assertEqual(ctx_b["blocks"], [{"id": a, "title": "A", "status": "blocked"}])


class TestCycleDetection(ForemanTestCase):
    def test_direct_cycle_rejected(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        self.run_cli("add-dependency", a, "--depends-on", b)
        msg = self.run_cli_raises("add-dependency", b, "--depends-on", a)
        self.assertIn("cycle", msg)

    def test_transitive_cycle_rejected(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        c = self.create_task(title="C")
        self.run_cli("add-dependency", a, "--depends-on", b)
        self.run_cli("add-dependency", b, "--depends-on", c)
        msg = self.run_cli_raises("add-dependency", c, "--depends-on", a)
        self.assertIn("cycle", msg)

    def test_self_dependency_rejected_with_clear_message(self):
        a = self.create_task(title="A")
        msg = self.run_cli_raises("add-dependency", a, "--depends-on", a)
        self.assertIn("self-dependency", msg)


class TestPauseResumeCancel(ForemanTestCase):
    def test_pause_from_running_transitions_to_waiting_and_logs_event(self):
        tid = self.create_task()
        self.run_cli("update", tid, "--status", "running")
        ctx = self.run_cli("pause", tid, "--reason", "waiting on input")
        self.assertEqual(ctx["task"]["status"], "waiting")
        events = [e for e in ctx["recent_events"] if e["type"] == "PAUSED"]
        self.assertEqual(len(events), 1)
        self.assertIn("waiting on input", events[0]["summary"])

    def test_resume_from_waiting_transitions_to_running_and_logs_event(self):
        tid = self.create_task()
        self.run_cli("update", tid, "--status", "running")
        started_at = self.run_cli("context", tid)["task"]["started_at"]
        self.run_cli("pause", tid)
        ctx = self.run_cli("resume", tid)
        self.assertEqual(ctx["task"]["status"], "running")
        self.assertEqual(ctx["task"]["started_at"], started_at)
        events = [e for e in ctx["recent_events"] if e["type"] == "RESUMED"]
        self.assertEqual(len(events), 1)

    def test_resume_rejected_when_dependency_incomplete(self):
        # "blocked" is not a valid transition from "waiting" (ALLOWED_TRANSITIONS),
        # so adding a dependency while a task sits in "waiting" cannot auto-block it --
        # it stays "waiting" with an unresolved dependency, the exact loophole resume
        # must independently guard against.
        b = self.create_task(title="B")
        a = self.create_task(title="A")
        self.run_cli("update", a, "--status", "running")
        self.run_cli("pause", a)
        ctx = self.run_cli("add-dependency", a, "--depends-on", b)
        self.assertEqual(ctx["task"]["status"], "waiting")
        msg = self.run_cli_raises("resume", a)
        self.assertIn(b, msg)

    def test_resume_succeeds_once_dependency_completed(self):
        b = self.create_task(title="B")
        a = self.create_task(title="A")
        self.run_cli("update", a, "--status", "running")
        self.run_cli("pause", a)
        self.run_cli("add-dependency", a, "--depends-on", b)
        self.run_cli("update", b, "--status", "running")
        self.run_cli("update", b, "--status", "completed")
        ctx = self.run_cli("resume", a)
        self.assertEqual(ctx["task"]["status"], "running")

    def test_cancel_does_not_cascade_to_dependents(self):
        a = self.create_task(title="A")
        b = self.create_task(title="B")
        self.run_cli("add-dependency", a, "--depends-on", b)
        ctx_b = self.run_cli("cancel", b, "--reason", "no longer needed")
        self.assertEqual(ctx_b["task"]["status"], "cancelled")
        ctx_a = self.run_cli("context", a)
        self.assertEqual(ctx_a["task"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
