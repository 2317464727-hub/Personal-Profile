"""HTTP workflow integration with synthetic sources and a deterministic model."""

import copy
import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import ai_server
from agent_tasks import BEIJING, TaskManager
from desktop_edits import DesktopEditManager
from personal_state import PersonalStateStore
from task_drafts import TaskDraftManager


RESUME = "whq-personal-resume-v1"
LOGS = "whq-personal-logs-v1"


class PersonalWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.desktop_path = self.root / "Desktop"
        self.desktop_path.mkdir()
        self.file = self.desktop_path / "synthetic-work.txt"
        self.file.write_text("测试记录：等待核查。\n", encoding="utf-8")
        self.now = datetime(2026, 11, 3, 10, 0, tzinfo=BEIJING)
        self.state = PersonalStateStore(self.root / "personal.sqlite3")
        self.desktop = DesktopEditManager(self.desktop_path, self.root / "backups")
        self.tasks = TaskManager(self.root / "tasks.sqlite3", ai_server.run_scheduled_task, clock=lambda: self.now)
        self.drafts = TaskDraftManager(self.state.path, self.tasks, self.state, self.desktop)
        patches = ExitStack()
        self.addCleanup(patches.close)
        for name, value in (("PERSONAL_STATE", self.state), ("DESKTOP_EDITS", self.desktop),
                            ("TASK_MANAGER", self.tasks), ("DRAFT_MANAGER", self.drafts),
                            ("API_KEY", "synthetic-test-key")):
            patches.enter_context(patch.object(ai_server, name, value))
        patches.enter_context(patch.object(ai_server, "consume_round", side_effect=AssertionError("A test must supply a fake model")))
        patches.enter_context(patch.object(ai_server.Handler, "log_message", lambda *_args: None))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ai_server.Handler)
        patches.enter_context(patch.object(ai_server, "PORT", self.server.server_port))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = "http://127.0.0.1:%s" % self.server.server_port

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, endpoint, body=None, status=200, headers=None):
        request_headers = {"Origin": self.base, **(headers or {})}
        raw = None
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(self.base + endpoint, data=raw, headers=request_headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            result = json.load(response)
            self.assertEqual(response.status, status, result)
            return result

    def source_data(self):
        return {
            RESUME: json.dumps({"name": "PRIVATE_NAME_SENTINEL", "phone": "PRIVATE_PHONE_SENTINEL",
                                "experience": "测试公司｜测试岗位\n参与测试记录整理。", "skills": "基础测试技能"}, ensure_ascii=False),
            LOGS: json.dumps([{"id": "synthetic-1", "title": "测试记录核对", "body": "已在测试环境核对一条记录，未发布到生产。", "date": "2026-11-03"}], ensure_ascii=False),
        }

    def create_task(self, grants=None, status=200):
        body = {"title": "合成资料测试", "prompt": "核对所选资料并提出修改草稿", "kind": "analysis", "repeat": "once",
                "run_at": (self.now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")}
        if grants is not None:
            body["grants"] = grants
        return self.request("/api/tasks/create", body, status)

    def test_state_http_conflict_backup_restore_and_origin_boundaries(self):
        initial = self.request("/api/personal-state")
        self.assertEqual(initial, {"revision": 0, "data": {}, "updated_at": ""})
        saved = self.request("/api/personal-state/save", {"base_revision": 0, "data": self.source_data()})
        conflict = self.request("/api/personal-state/save", {"base_revision": 0, "data": {}}, 409)
        self.assertEqual(conflict["snapshot"], saved)
        backup = self.request("/api/personal-state/backup")
        self.assertEqual(backup["data"], saved["data"])
        self.assertIn("不包含", backup["scope"])
        self.request("/api/personal-state/restore", {"base_revision": 1, "backup": backup}, 400)
        updated = self.request("/api/personal-state/save", {"base_revision": 1, "data": {RESUME: '{"experience":"更新后的测试经历"}'}})
        restored = self.request("/api/personal-state/restore", {"base_revision": updated["revision"], "backup": backup, "confirm": True})
        self.assertEqual(restored["data"], saved["data"])
        previous = self.request("/api/personal-state/previous-backup")
        self.assertEqual(previous["data"], updated["data"])
        self.assertEqual(PersonalStateStore(self.state.path).snapshot(), restored)
        for endpoint in ("/api/personal-state", "/api/personal-state/backup", "/api/tasks"):
            self.request(endpoint, status=403, headers={"Origin": "https://example.invalid"})
            self.request(endpoint, status=403, headers={"Sec-Fetch-Site": "cross-site"})
        self.request("/api/personal-state/save", {"base_revision": restored["revision"], "data": {}}, 403,
                     headers={"Origin": "https://example.invalid"})
        self.assertEqual(self.request("/api/personal-state"), restored)

    def test_authorized_model_drafts_preview_apply_and_undo_over_http(self):
        initial = self.request("/api/personal-state/save", {"base_revision": 0, "data": self.source_data()})
        task = self.create_task({"logs": True, "resume": True, "files": [str(self.file)], "consent": True})
        self.assertTrue(task["grants"]["consent"])
        new_resume = "测试公司｜测试岗位\n参与测试记录整理。\n- 已在测试环境完成核对，未发布到生产。"
        captured = []

        def fake_model(payload, calls):
            captured.append(copy.deepcopy(payload))
            round_number = len(captured)
            def call(name, args):
                calls.append({"type": "function_call", "call_id": "call-%s-%s" % (round_number, name),
                              "name": name, "arguments": json.dumps(args, ensure_ascii=False)})
            if round_number == 1:
                call("read_resume", {"section": "experience"})
            elif round_number == 2:
                outputs = [json.loads(item["output"]) for item in payload["input"] if item.get("type") == "function_call_output"]
                self.assertEqual(outputs[-1]["source_id"], "简历:experience")
                call("search_records", {"query": "测试记录核对"})
                call("read_selected_file", {"path": str(self.file)})
            elif round_number == 3:
                outputs = [json.loads(item["output"]) for item in payload["input"] if item.get("type") == "function_call_output"]
                file_source = outputs[-1]["source_id"]
                self.assertEqual(outputs[-2]["records"][0]["source_id"], "周历:synthetic-1")
                call("propose_resume", {"target": "experience", "text": new_resume,
                                        "source_ids": ["简历:experience", "周历:synthetic-1"]})
                call("propose_file_edit", {"path": str(self.file), "old_text": "等待核查", "new_text": "已在测试环境核查，未发布",
                                           "source_ids": [file_source, "周历:synthetic-1"]})
            else:
                yield "text", {"delta": "待决定\n已生成两份草稿，请核对差异。"}

        self.request("/api/tasks/action", {"id": task["id"], "action": "run_now"})
        with patch.object(ai_server, "consume_round", fake_model):
            self.assertTrue(self.tasks.run_due())
        self.assertEqual(len(captured), 4)
        for payload in captured:
            rendered = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("PRIVATE_NAME_SENTINEL", rendered)
            self.assertNotIn("PRIVATE_PHONE_SENTINEL", rendered)
            self.assertNotIn({"type": "web_search"}, payload["tools"])
        current = self.request("/api/tasks")["tasks"][0]
        self.assertEqual(current["state"], "needs_decision")
        self.assertEqual(len(current["last_run"]["sources"]), 3)
        self.assertEqual(len(current["last_run"]["drafts"]), 2)
        self.assertEqual(self.request("/api/personal-state"), initial)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "测试记录：等待核查。\n")
        # Restart all stores before review to prove persisted runs/drafts are usable.
        restarted_state = PersonalStateStore(self.state.path)
        restarted_tasks = TaskManager(self.tasks.path, ai_server.run_scheduled_task, clock=lambda: self.now)
        restarted_desktop = DesktopEditManager(self.desktop_path, self.root / "backups")
        restarted_drafts = TaskDraftManager(self.state.path, restarted_tasks, restarted_state, restarted_desktop)
        with patch.object(ai_server, "PERSONAL_STATE", restarted_state), patch.object(ai_server, "TASK_MANAGER", restarted_tasks), \
                patch.object(ai_server, "DESKTOP_EDITS", restarted_desktop), patch.object(ai_server, "DRAFT_MANAGER", restarted_drafts):
            for draft in current["last_run"]["drafts"]:
                preview = self.request("/api/tasks/draft/preview", {"task_id": task["id"], "run_id": current["last_run"]["id"], "draft_id": draft["id"]})
                self.assertNotEqual(preview["before"], preview["after"])
                self.request("/api/tasks/draft/apply", {"preview_id": preview["preview_id"]}, 400)
                applied = self.request("/api/tasks/draft/apply", {"preview_id": preview["preview_id"], "confirm": True})
                again = self.request("/api/tasks/draft/apply", {"preview_id": preview["preview_id"], "confirm": True})
                self.assertEqual(again["change_id"], applied["change_id"])
                if draft["kind"] == "resume":
                    resume = json.loads(self.request("/api/personal-state")["data"][RESUME])
                    self.assertEqual(resume["experience"], new_resume)
                    self.assertEqual(resume["phone"], "PRIVATE_PHONE_SENTINEL")
                else:
                    self.assertIn("已在测试环境核查，未发布", self.file.read_text(encoding="utf-8"))
                    self.assertTrue(list((self.root / "backups").glob("*.json")))
                # The undo receipt is durable independently of the manager instance.
                undo_manager = TaskDraftManager(self.state.path, restarted_tasks, restarted_state, restarted_desktop)
                with patch.object(ai_server, "DRAFT_MANAGER", undo_manager):
                    self.request("/api/tasks/draft/undo", {"change_id": applied["change_id"]}, 400)
                    self.request("/api/tasks/draft/undo", {"change_id": applied["change_id"], "confirm": True})
                saved_draft = next(item for item in self.request("/api/tasks")["tasks"][0]["last_run"]["drafts"] if item["id"] == draft["id"])
                self.assertEqual(saved_draft["state"], "undone")
        self.assertEqual(json.loads(self.request("/api/personal-state")["data"][RESUME]), json.loads(initial["data"][RESUME]))
        self.assertEqual(self.file.read_text(encoding="utf-8"), "测试记录：等待核查。\n")

    def test_private_grants_need_consent_and_paths_stay_scoped(self):
        self.create_task({"logs": True, "resume": True, "files": [], "consent": False}, 400)
        outside = self.root / "outside.txt"
        outside.write_text("not authorized", encoding="utf-8")
        self.create_task({"files": [str(outside)], "consent": True}, 400)
        self.assertEqual(self.request("/api/tasks")["tasks"], [])

    def test_no_grants_means_no_private_snapshot_or_tool_result(self):
        self.request("/api/personal-state/save", {"base_revision": 0, "data": self.source_data()})
        task = self.create_task()
        self.assertFalse(task["grants"]["consent"])
        captured = []

        def fake_model(payload, calls):
            captured.append(copy.deepcopy(payload))
            if len(captured) == 1:
                # Even a misbehaving upstream cannot invoke an ungranted read.
                calls.append({"call_id": "denied", "name": "read_resume", "arguments": '{"section":"experience"}'})
            else:
                yield "text", {"delta": "待决定\n需要先授权所选资料。"}

        self.request("/api/tasks/action", {"id": task["id"], "action": "run_now"})
        with patch.object(ai_server, "consume_round", fake_model), \
                patch.object(self.state, "snapshot", side_effect=AssertionError("Private state must not be read")), \
                patch.object(self.desktop, "inspect", side_effect=AssertionError("Desktop must not be read")):
            self.assertTrue(self.tasks.run_due())
        self.assertEqual(len(captured), 2)
        for payload in captured:
            self.assertEqual(payload["tools"], [{"type": "web_search"}])
            rendered = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("PRIVATE_NAME_SENTINEL", rendered)
            self.assertNotIn("参与测试记录整理", rendered)
            self.assertNotIn("已在测试环境核对一条记录", rendered)
        tool_output = json.loads(captured[-1]["input"][-1]["output"])
        self.assertIn("未授权", tool_output["error"])
        current = self.request("/api/tasks")["tasks"][0]
        self.assertEqual(current["state"], "needs_decision")
        self.assertEqual(current["last_run"]["drafts"], [])
        self.assertEqual(current["last_run"]["sources"], [])


if __name__ == "__main__":
    unittest.main()
