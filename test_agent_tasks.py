import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import ai_server
from agent_tasks import BEIJING, TaskManager
from file_tools import is_sensitive_name


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 29, 10, 0, tzinfo=BEIJING)

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


class TaskManagerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / ".agent-tasks.sqlite3"
        self.clock = Clock()

    def manager(self, runner, **kwargs):
        return TaskManager(self.path, runner, clock=self.clock, **kwargs)

    def create(self, manager, kind="reminder", repeat="once"):
        return manager.create({"title": "核对结果", "prompt": "检查结果并决定下一步", "kind": kind,
                               "repeat": repeat, "run_at": (self.clock.value + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")})

    def test_reminder_survives_restart_and_needs_decision(self):
        first = self.manager(lambda job, progress: {"status": "needs_decision", "output": job["prompt"]})
        task = self.create(first)
        second = self.manager(lambda job, progress: {"status": "needs_decision", "output": job["prompt"]})
        self.assertEqual(second.list()[0]["id"], task["id"])
        self.clock.advance(minutes=2)
        self.assertTrue(second.run_due())
        current = first.list()[0]
        self.assertEqual(current["state"], "needs_decision")
        self.assertEqual(current["last_run"]["output"], "检查结果并决定下一步")
        self.assertFalse(second.run_due())
        second.action(task["id"], "complete")
        self.assertEqual(first.list()[0]["state"], "done")

    def test_recurring_analysis_and_pause(self):
        manager = self.manager(lambda job, progress: {"status": "completed", "output": "已核查"})
        task = self.create(manager, kind="analysis", repeat="daily")
        edited = manager.update({"id": task["id"], "title": "每日核对", "prompt": "改过的要求", "kind": "analysis",
                                 "repeat": "daily", "run_at": "2026-10-29T10:01"})
        self.assertEqual(edited["title"], "每日核对")
        self.assertEqual(edited["prompt"], "改过的要求")
        self.clock.advance(minutes=2)
        manager.run_due()
        current = manager.list()[0]
        self.assertEqual(current["state"], "active")
        self.assertEqual(current["last_run"]["output"], "已核查")
        self.assertEqual(current["next_run"], "2026-10-30T10:01")
        manager.action(task["id"], "pause")
        self.clock.advance(days=1)
        self.assertFalse(manager.run_due())
        manager.action(task["id"], "resume")
        self.assertTrue(manager.run_due())
        self.assertEqual(manager.list()[0]["next_run"], "2026-10-31T10:01")

    def test_failure_retry_and_snooze(self):
        attempts = []

        def runner(job, progress):
            attempts.append(job["id"])
            if len(attempts) == 1:
                raise RuntimeError("服务暂不可用")
            return {"status": "completed", "output": "完成"}

        manager = self.manager(runner)
        task = self.create(manager, kind="analysis")
        self.clock.advance(minutes=2)
        manager.run_due()
        self.assertEqual(manager.list()[0]["state"], "needs_decision")
        self.assertIn("服务暂不可用", manager.list()[0]["last_run"]["error"])
        manager.action(task["id"], "retry")
        manager.run_due()
        self.assertEqual(manager.list()[0]["last_run"]["attempt"], 2)
        self.assertEqual(manager.list()[0]["state"], "done")

        reminder = self.create(manager)
        manager.runner = lambda job, progress: {"status": "needs_decision", "output": "提醒"}
        self.clock.advance(minutes=2)
        manager.run_due()
        manager.action(reminder["id"], "snooze")
        self.assertEqual(manager.list()[0]["state"], "active")
        self.assertEqual(manager.list()[0]["next_run"], "2026-10-29T11:04")

    def test_cross_process_claim_and_expired_lease_recovery(self):
        other = None

        def runner(job, progress):
            self.assertFalse(other.run_due())
            progress("运行中")
            return {"status": "completed", "output": "完成"}

        first = self.manager(runner, lease_seconds=5)
        other = self.manager(runner, lease_seconds=5)
        self.create(first, kind="analysis")
        self.clock.advance(minutes=2)
        claim = first._claim()
        self.assertIsNotNone(claim)
        self.assertFalse(other.run_due())
        self.clock.advance(seconds=6)
        self.assertTrue(other.run_due())
        self.assertEqual(first.list()[0]["last_run"]["attempt"], 2)
        self.assertEqual(first.list()[0]["state"], "done")
        self.assertTrue(is_sensitive_name(".agent-tasks.sqlite3-journal"))

    def test_scheduled_runner_has_no_private_or_write_tools(self):
        job = {"kind": "analysis", "prompt": "查公开资料"}
        captured = {}

        def fake_round(payload, calls):
            captured.update(payload)
            yield "text", {"delta": "已分析"}

        with patch.object(ai_server, "API_KEY", "test-key"), patch.object(ai_server, "consume_round", fake_round):
            result = ai_server.run_scheduled_task(job, lambda message: None)
        self.assertEqual(result, {"status": "completed", "output": "已分析"})
        self.assertEqual(captured["tools"], [{"type": "web_search"}])
        self.assertNotIn("查公开资料", captured["instructions"])
        self.assertNotIn("project_replace", str(captured["tools"]))
        self.assertIn("不得访问本机文件", captured["instructions"])

    def test_http_task_workflow_uses_isolated_store(self):
        manager = self.manager(lambda job, progress: {"status": "needs_decision", "output": job["prompt"]})
        with patch.object(ai_server, "TASK_MANAGER", manager):
            server = ThreadingHTTPServer(("127.0.0.1", 0), ai_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:%s" % server.server_port

            def post(endpoint, body):
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                request = Request(base + endpoint, data=raw, headers={"Content-Type": "application/json"})
                with urlopen(request) as response:
                    return json.load(response)

            try:
                created = post("/api/tasks/create", {"title": "测试提醒", "prompt": "检查测试结果", "kind": "reminder",
                                                     "repeat": "once", "run_at": "2026-10-29T10:01"})
                updated = post("/api/tasks/update", {"id": created["id"], "title": "已更新提醒", "prompt": "检查测试结果",
                                                      "kind": "reminder", "repeat": "once", "run_at": "2026-10-29T10:02"})
                self.assertEqual(updated["title"], "已更新提醒")
                self.clock.advance(minutes=3)
                manager.run_due()
                with urlopen(base + "/api/tasks") as response:
                    current = json.load(response)["tasks"][0]
                self.assertEqual(current["state"], "needs_decision")
                resolved = post("/api/tasks/action", {"id": created["id"], "action": "complete"})
                self.assertEqual(resolved["state"], "done")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
