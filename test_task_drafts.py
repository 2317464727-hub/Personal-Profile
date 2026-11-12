"""Exercise confirmed scheduled drafts against isolated real stores and files."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from agent_tasks import BEIJING, TaskManager
from desktop_edits import DesktopEditManager, digest
from personal_state import PersonalStateStore
from task_drafts import RESUME_KEY, TaskDraftManager


class TaskDraftTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.desktop_path = self.root / "Desktop"
        self.desktop_path.mkdir()
        self.now = datetime(2026, 11, 3, 10, 0, tzinfo=BEIJING)
        self.state = PersonalStateStore(self.root / "state.sqlite3")
        self.tasks = TaskManager(self.root / "tasks.sqlite3", lambda job, progress: {}, clock=lambda: self.now)
        self.desktop = DesktopEditManager(self.desktop_path, self.root / "backups")
        self.manager = TaskDraftManager(self.state.path, self.tasks, self.state, self.desktop)
        self.initial_resume = {"name": "测试姓名", "experience": "原经历", "skills": "原技能", "phone": "示例联系方式"}
        self.initial_data = {
            RESUME_KEY: json.dumps(self.initial_resume, ensure_ascii=False),
            "whq-personal-logs-v1": json.dumps([{"id": "log-1", "body": "仅在本机测试"}]),
            "whq-personal-profile-v1": json.dumps({"name": "个人中心"}),
        }
        self.state.save({"base_revision": 0, "data": self.initial_data})

    def fixture(self, draft=None, grants=None):
        draft = draft or {"id": "draft-1", "kind": "resume", "target": "experience", "base_text": "原经历",
                          "text": "改进后的完整经历", "state": "pending", "source_ids": ["resume:experience"]}
        grants = grants or {"resume": True, "consent": True, "logs": False, "files": []}
        self.tasks.runner = lambda job, progress: {"status": "needs_decision", "output": "请核对草稿", "drafts": [draft],
                                                  "sources": [{"id": "resume:experience", "label": "实习经历"}]}
        task = self.tasks.create({"title": "测试草稿", "prompt": "根据所选资料提出修改", "kind": "analysis", "repeat": "once",
                                  "run_at": (self.now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"), "grants": grants})
        self.now += timedelta(minutes=2)
        self.assertTrue(self.tasks.run_due())
        task = self.tasks.get_task(task["id"])
        self.assertEqual(task["state"], "needs_decision")
        return {"task_id": task["id"], "run_id": task["last_run"]["id"], "draft_id": draft["id"]}

    def resume(self):
        return json.loads(self.state.snapshot()["data"][RESUME_KEY])

    def update_resume(self, **updates):
        snapshot = self.state.snapshot()
        resume = json.loads(snapshot["data"][RESUME_KEY])
        resume.update(updates)
        snapshot["data"][RESUME_KEY] = json.dumps(resume, ensure_ascii=False)
        return self.state.save({"base_revision": snapshot["revision"], "data": snapshot["data"]})

    def recreate(self):
        self.state = PersonalStateStore(self.state.path)
        self.tasks = TaskManager(self.tasks.path, lambda job, progress: {}, clock=lambda: self.now)
        self.desktop = DesktopEditManager(self.desktop_path, self.root / "backups")
        self.manager = TaskDraftManager(self.state.path, self.tasks, self.state, self.desktop)

    def file_fixture(self):
        target = self.desktop_path / "work.txt"
        target.write_bytes(b"first\r\nsecond\r\n")
        draft = {"id": "file-draft", "kind": "file", "path": str(target), "old_text": "second", "new_text": "revised",
                 "original_hash": digest(target.read_bytes()), "source_ids": ["file:1"], "state": "pending"}
        request = self.fixture(draft, {"files": [str(target)], "resume": False, "logs": False, "consent": True})
        return target, request

    def test_preview_does_not_write_and_confirmation_is_required(self):
        request = self.fixture()
        before = self.state.snapshot()
        preview = self.manager.preview(request)
        self.assertEqual(preview["before"], "原经历")
        self.assertEqual(preview["after"], "改进后的完整经历")
        self.assertEqual(self.state.snapshot(), before)
        for confirm in (None, False, 1, "true"):
            with self.subTest(confirm=confirm), self.assertRaisesRegex(ValueError, "确认"):
                self.manager.apply({"preview_id": preview["preview_id"], "confirm": confirm})
        self.assertEqual(self.state.snapshot(), before)
        self.assertEqual(self.tasks.get_run(request["task_id"], request["run_id"])["drafts"][0]["state"], "pending")

    def test_stale_resume_at_preview_and_after_preview_is_rejected(self):
        request = self.fixture()
        self.update_resume(experience="后来编辑的经历")
        with self.assertRaisesRegex(ValueError, "变化"):
            self.manager.preview(request)
        self.update_resume(experience="原经历")
        preview = self.manager.preview(request)
        self.update_resume(experience="预览后又编辑")
        with self.assertRaisesRegex(ValueError, "变化"):
            self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(self.resume()["experience"], "预览后又编辑")

    def test_resume_replace_backup_undo_survive_restart_and_preserve_other_data(self):
        request = self.fixture()
        preview = self.manager.preview(request)
        self.update_resume(skills="预览后独立修改的技能")
        result = self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(self.resume()["experience"], "改进后的完整经历")
        self.assertEqual(self.resume()["skills"], "预览后独立修改的技能")
        for field in ("name", "phone"):
            self.assertEqual(self.resume()[field], self.initial_resume[field])
        for key, value in self.initial_data.items():
            if key != RESUME_KEY:
                self.assertEqual(self.state.snapshot()["data"][key], value)
        with closing(sqlite3.connect(self.state.path)) as db:
            receipt = db.execute("SELECT before_text,after_text,state FROM draft_reviews WHERE change_id=?", (result["change_id"],)).fetchone()
        self.assertEqual(receipt, ("原经历", "改进后的完整经历", "applied"))
        self.recreate()
        record = self.tasks.get_run(request["task_id"], request["run_id"])["drafts"][0]
        self.assertEqual(record["change_id"], result["change_id"])
        self.assertEqual(record["state"], "applied")
        with self.assertRaisesRegex(ValueError, "确认"):
            self.manager.undo({"change_id": result["change_id"]})
        self.manager.undo({"change_id": result["change_id"], "confirm": True})
        self.assertEqual(self.resume()["experience"], "原经历")
        self.assertEqual(self.resume()["skills"], "预览后独立修改的技能")
        self.assertEqual(self.tasks.get_run(request["task_id"], request["run_id"])["drafts"][0]["state"], "undone")

    def test_repeated_apply_and_undo_are_idempotent(self):
        preview = self.manager.preview(self.fixture())
        first = self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        revision = self.state.snapshot()["revision"]
        self.recreate()
        repeated = self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(first["change_id"], repeated["change_id"])
        self.assertEqual(self.state.snapshot()["revision"], revision)
        self.manager.undo({"change_id": first["change_id"], "confirm": True})
        revision = self.state.snapshot()["revision"]
        self.manager.undo({"change_id": first["change_id"], "confirm": True})
        self.assertEqual(self.state.snapshot()["revision"], revision)
        with self.assertRaisesRegex(ValueError, "撤销"):
            self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})

    def test_file_preview_apply_backup_and_undo_across_restart(self):
        target, request = self.file_fixture()
        original = target.read_bytes()
        preview = self.manager.preview(request)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(self.desktop.history(), [])
        self.recreate()  # In-memory desktop preview cache is intentionally lost.
        result = self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(target.read_bytes(), b"first\r\nrevised\r\n")
        backup = list((self.root / "backups").glob("*.bak"))
        self.assertEqual(len(backup), 1)
        self.assertEqual(backup[0].read_bytes(), original)
        self.recreate()
        repeat = self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(repeat["change_id"], result["change_id"])
        self.assertEqual(len(list((self.root / "backups").glob("*.bak"))), 1)
        self.manager.undo({"change_id": result["change_id"], "confirm": True})
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(self.desktop.history()[0]["status"], "undone")

    def test_file_hash_conflicts_at_preview_apply_and_undo(self):
        target, request = self.file_fixture()
        original = target.read_bytes()
        target.write_bytes(b"external")
        with self.assertRaisesRegex(ValueError, "变化"):
            self.manager.preview(request)
        target.write_bytes(original)
        preview = self.manager.preview(request)
        target.write_bytes(b"external")
        with self.assertRaisesRegex(ValueError, "变化"):
            self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(target.read_bytes(), b"external")
        target.write_bytes(original)
        result = self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        target.write_bytes(b"newer edit")
        with self.assertRaisesRegex(ValueError, "变化"):
            self.manager.undo({"change_id": result["change_id"], "confirm": True})
        self.assertEqual(target.read_bytes(), b"newer edit")

    def test_revoking_resume_scope_after_preview_prevents_apply(self):
        request = self.fixture()
        preview = self.manager.preview(request)
        self.tasks.action(request["task_id"], "pause")
        self.tasks.update({"id": request["task_id"], "title": "已撤回简历授权", "prompt": "只查周历", "kind": "analysis", "repeat": "once",
                           "run_at": (self.now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"),
                           "grants": {"logs": True, "resume": False, "files": [], "consent": True}})
        with self.assertRaisesRegex(ValueError, "没有授权"):
            self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(self.resume(), self.initial_resume)

    def test_revoking_file_scope_after_preview_prevents_apply(self):
        target, request = self.file_fixture()
        preview = self.manager.preview(request)
        self.tasks.action(request["task_id"], "pause")
        self.tasks.update({"id": request["task_id"], "title": "已撤回文件授权", "prompt": "只查周历", "kind": "analysis", "repeat": "once",
                           "run_at": (self.now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"),
                           "grants": {"logs": True, "resume": False, "files": [], "consent": True}})
        with self.assertRaisesRegex(ValueError, "不在任务授权范围"):
            self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(target.read_bytes(), b"first\r\nsecond\r\n")

    def test_cancelled_task_rejects_preview_and_apply(self):
        request = self.fixture()
        preview = self.manager.preview(request)
        self.tasks.action(request["task_id"], "cancel")
        with self.assertRaisesRegex(ValueError, "已取消"):
            self.manager.preview(request)
        with self.assertRaisesRegex(ValueError, "已取消"):
            self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(self.resume(), self.initial_resume)

    def test_new_preview_invalidates_old_token_and_expiration_blocks_write(self):
        request = self.fixture()
        old = self.manager.preview(request)
        new = self.manager.preview(request)
        with self.assertRaisesRegex(ValueError, "找不到预览"):
            self.manager.apply({"preview_id": old["preview_id"], "confirm": True})
        with patch("task_drafts.time.time", return_value=10**12):
            with self.assertRaisesRegex(ValueError, "过期"):
                self.manager.apply({"preview_id": new["preview_id"], "confirm": True})
        self.assertEqual(self.resume(), self.initial_resume)

    def test_resume_undo_conflict_preserves_newer_edit(self):
        preview = self.manager.preview(self.fixture())
        result = self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.update_resume(experience="写入后用户又修改")
        with self.assertRaisesRegex(ValueError, "不能自动撤销"):
            self.manager.undo({"change_id": result["change_id"], "confirm": True})
        self.assertEqual(self.resume()["experience"], "写入后用户又修改")

    def test_resume_receipt_recovers_if_task_status_update_interrupted(self):
        request = self.fixture()
        preview = self.manager.preview(request)
        with patch.object(self.tasks, "mark_draft", side_effect=RuntimeError("simulated interruption")):
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(self.resume()["experience"], "改进后的完整经历")
        revision = self.state.snapshot()["revision"]
        self.recreate()
        result = self.manager.apply({"preview_id": preview["preview_id"], "confirm": True})
        self.assertEqual(self.state.snapshot()["revision"], revision)
        record = self.tasks.get_run(request["task_id"], request["run_id"])["drafts"][0]
        self.assertEqual(record["change_id"], result["change_id"])
        self.assertEqual(record["state"], "applied")


if __name__ == "__main__":
    unittest.main()
