import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from agent_tasks import BEIJING, TaskManager, normalize_grants
from scheduled_agent import ScheduledAgent


class ScheduledAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "工作记录.txt"
        self.path.write_text("完成模拟库存核查。\n尚未修改实际库存。", encoding="utf-8")
        self.state = {"revision": 3, "data": {
            "whq-personal-resume-v1": json.dumps({"name": "不应外发姓名", "phone": "不应外发电话", "experience": "某公司｜实习生\n2026.09—至今\n- 完成模拟验证", "skills": "Python"}),
            "whq-personal-logs-v1": json.dumps([
                {"id": "older", "date": "2026-09-01", "title": "库存模拟核查", "body": "完成模拟流程，未改实际库存。"},
                *[{"id": "recent-%s" % i, "date": "2026-10-30", "title": "其他记录", "body": "整理文档"} for i in range(20)]
            ])}}
        self.payloads = []
        self.inspected = []

    def runner(self, rounds):
        iterator = iter(rounds)

        def consume(payload, calls):
            self.payloads.append(copy.deepcopy(payload))
            step = next(iterator)
            if isinstance(step, Exception):
                raise step
            if isinstance(step, str):
                yield "text", {"delta": step}
            else:
                for index, (name, args) in enumerate(step):
                    calls.append({"type": "function_call", "call_id": "call-%d-%d" % (len(self.payloads), index), "name": name, "arguments": json.dumps(args, ensure_ascii=False)})

        def inspect(path):
            self.inspected.append(path)
            # The runner accepts an already boundary-checked inspector. The desktop
            # boundary itself is covered by test_desktop_edits.
            selected = Path(path)
            raw = selected.read_bytes()
            return {"path": str(selected), "kind": "text", "content": raw.decode("utf-8"), "original_hash": hashlib.sha256(raw).hexdigest()}

        return ScheduledAgent(lambda: copy.deepcopy(self.state), inspect, consume, "test-model")

    def run_job(self, runner, grants=None):
        return runner.run({"kind": "analysis", "prompt": "根据库存工作完善实习经历", "grants": grants or {}}, lambda text: None)

    def test_no_grants_never_reads_private_state_or_files(self):
        runner = self.runner(["完成\n公开结论"])
        runner.snapshot = lambda: self.fail("private store must not be read")
        result = self.run_job(runner)
        self.assertEqual(result, {"status": "completed", "output": "公开结论"})
        self.assertEqual(self.payloads[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(self.inspected, [])

    def test_denied_tool_cannot_read_even_if_model_requests_it(self):
        runner = self.runner([[('read_selected_file', {"path": str(self.path)})], "待决定\n需要授权"])
        result = self.run_job(runner)
        self.assertEqual(result["status"], "needs_decision")
        self.assertEqual(self.inspected, [])
        self.assertIn("未授权", self.payloads[1]["input"][-1]["output"])

    def test_multi_round_retrieval_proposal_has_real_sources_and_no_contacts(self):
        replacement = "某公司｜实习生\n2026.09—至今\n- 完成库存模拟核查，未改实际库存。"
        runner = self.runner([
            [("search_records", {"query": "库存模拟"}), ("read_resume", {"section": "experience"})],
            [("propose_resume", {"target": "experience", "text": replacement, "source_ids": ["周历:older", "简历:experience"]})],
            "待决定\n请核对替换草稿 [周历:older]",
        ])
        result = self.run_job(runner, {"logs": True, "resume": True, "consent": True})
        self.assertEqual(len(self.payloads), 3)
        self.assertEqual(result["status"], "needs_decision")
        draft = result["drafts"][0]
        self.assertEqual(draft["text"], replacement)
        self.assertEqual(draft["base_text"], json.loads(self.state["data"]["whq-personal-resume-v1"])["experience"])
        self.assertEqual(draft["state"], "pending")
        records = json.loads(self.payloads[1]["input"][2]["output"])["records"]
        self.assertEqual(records[0]["source_id"], "周历:older")
        sent = json.dumps(self.payloads, ensure_ascii=False)
        self.assertNotIn("不应外发", sent)
        self.assertNotIn('"type": "web_search"', sent)

    def test_file_draft_reads_only_selected_file_and_preserves_original(self):
        baseline = self.path.read_bytes()
        file_source = "文件:" + hashlib.sha256(os.path.normcase(str(self.path.resolve())).encode()).hexdigest()[:16]
        runner = self.runner([
            [("read_selected_file", {"path": str(self.path)})],
            [("propose_file_edit", {"path": str(self.path), "old_text": "完成模拟库存核查。", "new_text": "已完成库存流程的模拟核查。", "source_ids": [file_source]})],
            "待决定\n请确认文件草稿",
        ])
        result = self.run_job(runner, {"files": [str(self.path)], "consent": True})
        self.assertEqual(result["drafts"][0]["kind"], "file")
        self.assertEqual(result["drafts"][0]["original_hash"], hashlib.sha256(baseline).hexdigest())
        self.assertEqual(self.path.read_bytes(), baseline)
        self.assertEqual(self.inspected, [str(self.path)])

    def test_resume_supplements_are_context_but_not_replacement_base(self):
        self.state["data"]["whq-resume-work-additions-v1"] = json.dumps([
            {"id": "supplement-one", "target": "skills", "text": "使用 Python 批量核对数据", "sourceIds": ["older"], "structured": True},
            {"id": "supplement-other", "target": "projects", "text": "另一栏目的材料不发送"},
        ])
        runner = self.runner([
            [("read_resume", {"section": "skills"})],
            [("propose_resume", {"target": "skills", "text": "熟悉 Python 基础语法", "source_ids": ["简历:skills"]})],
            "待决定\n请核对技能原文替换草稿",
        ])
        result = self.run_job(runner, {"resume": True, "consent": True})
        read = json.loads(self.payloads[1]["input"][-1]["output"])
        self.assertEqual(read["text"], "Python")
        self.assertEqual(read["supplements"], [{"text": "使用 Python 批量核对数据", "readonly": True}])
        self.assertFalse(read["supplements_truncated"])
        self.assertEqual(result["drafts"][0]["base_text"], "Python")
        self.assertNotIn("另一栏目的材料", json.dumps(self.payloads, ensure_ascii=False))
        self.assertIn("不要重复", self.payloads[0]["instructions"])

    def test_fabricated_sources_and_unselected_files_are_rejected(self):
        runner = self.runner([
            [("read_resume", {"section": "skills"}), ("read_selected_file", {"path": str(self.root / "other.txt")})],
            [("propose_resume", {"target": "skills", "text": "熟悉 Python 和测试工作", "source_ids": ["周历:不存在"]})],
            "待决定\n依据不足",
        ])
        result = self.run_job(runner, {"resume": True, "files": [str(self.path)], "consent": True})
        self.assertEqual(result["drafts"], [])
        self.assertEqual(self.inspected, [])
        self.assertIn("实际读取", self.payloads[-1]["input"][-1]["output"])

    def test_drafts_survive_failure_after_proposal(self):
        runner = self.runner([
            [("read_resume", {"section": "skills"})],
            [("propose_resume", {"target": "skills", "text": "使用 Python 开发脚本", "source_ids": ["简历:skills"]})],
            RuntimeError("temporary upstream failure"),
        ])
        result = self.run_job(runner, {"resume": True, "consent": True})
        self.assertEqual(result["status"], "needs_decision")
        self.assertEqual(len(result["drafts"]), 1)
        self.assertIn("分析中断", result["output"])

    def test_repeated_calls_stop_and_missing_consent_is_rejected(self):
        runner = self.runner([[('search_records', {"query": "库存"})]] * 4)
        result = self.run_job(runner, {"logs": True, "consent": True})
        self.assertEqual(len(self.payloads), 3)
        self.assertEqual(result["status"], "needs_decision")
        with self.assertRaisesRegex(ValueError, "每次运行"):
            self.run_job(runner, {"logs": True})


class TaskGrantPersistenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "tasks.sqlite3"
        self.now = datetime(2026, 11, 3, 10, 0, tzinfo=BEIJING)

    def manager(self, runner):
        return TaskManager(self.path, runner, clock=lambda: self.now)

    def body(self):
        return {"title": "核查简历", "prompt": "根据记录核查技能", "kind": "analysis", "repeat": "daily", "run_at": "2026-11-03T10:01", "grants": {"logs": True, "resume": True, "consent": True}}

    def test_grants_results_and_draft_state_survive_restart(self):
        def run(job, progress):
            self.assertTrue(job["grants"]["logs"])
            return {"status": "completed", "output": "请审核", "sources": [{"id": "简历:skills"}], "drafts": [{"id": "draft1", "kind": "resume", "state": "pending"}]}
        first = self.manager(run)
        task = first.create(self.body())
        self.now += timedelta(minutes=2)
        self.manager(run).run_due()
        current = first.get_task(task["id"])
        self.assertEqual(current["state"], "needs_decision")
        run_id = current["last_run"]["id"]
        first.mark_draft(task["id"], run_id, "draft1", "applied", {"change_id": "change1"})
        restarted = self.manager(run)
        result = restarted.get_run(task["id"], run_id)
        self.assertTrue(result["grants"]["resume"])
        self.assertEqual(result["drafts"][0]["state"], "applied")
        self.assertEqual(result["drafts"][0]["change_id"], "change1")

    def test_old_database_is_migrated_without_grants(self):
        manager = self.manager(lambda job, progress: {"status": "completed", "output": "好"})
        body = self.body()
        body.pop("grants")
        task = manager.create(body)
        with sqlite3.connect(self.path) as db:
            db.execute("ALTER TABLE tasks DROP COLUMN grants")
            db.execute("ALTER TABLE runs DROP COLUMN drafts")
            db.execute("ALTER TABLE runs DROP COLUMN sources")
        db.close()
        migrated = self.manager(lambda job, progress: {"status": "completed", "output": "好"})
        current = migrated.get_task(task["id"])
        self.assertEqual(current["grants"], {"logs": False, "resume": False, "files": [], "consent": False})
        self.now += timedelta(minutes=2)
        self.assertTrue(migrated.run_due())

    def test_recurring_task_keeps_previous_applied_draft_available(self):
        def run(job, progress):
            return {"status": "needs_decision", "output": "请审核", "sources": [{"id": "简历:skills", "kind": "resume", "label": "技能"}],
                    "drafts": [{"id": "draft-" + job["run_id"], "kind": "resume", "target": "skills", "state": "pending"}]}
        manager = self.manager(run)
        task = manager.create(self.body())
        self.now += timedelta(minutes=2)
        manager.run_due()
        first_run = manager.get_task(task["id"])["last_run"]
        manager.mark_draft(task["id"], first_run["id"], first_run["drafts"][0]["id"], "applied", {"change_id": "saved-change"})
        with self.assertRaisesRegex(ValueError, "先标记本次已处理"):
            manager.action(task["id"], "retry")
        self.assertEqual(manager.get_run(task["id"], first_run["id"])["drafts"][0]["change_id"], "saved-change")
        # Pausing and resuming a review must not erase it by rerunning the same occurrence.
        manager.action(task["id"], "pause")
        self.assertEqual(manager.action(task["id"], "resume")["state"], "needs_decision")
        self.assertFalse(manager.run_due())
        manager.action(task["id"], "complete")
        self.now += timedelta(days=1)
        self.assertTrue(manager.run_due())
        for current in (self.manager(run).get_task(task["id"]), manager.list()[0]):
            self.assertNotEqual(current["last_run"]["id"], first_run["id"])
            self.assertEqual(len(current["draft_history"]), 1)
            historical = current["draft_history"][0]
            self.assertEqual(historical["id"], first_run["id"])
            self.assertEqual(historical["status"], "resolved")
            self.assertEqual(historical["scheduled_for"], "2026-11-03T10:01")
            self.assertEqual(historical["sources"], first_run["sources"])
            self.assertEqual(historical["drafts"][0]["change_id"], "saved-change")
        manager.mark_draft(task["id"], first_run["id"], first_run["drafts"][0]["id"], "undone")
        self.assertEqual(manager.get_task(task["id"])["draft_history"][0]["drafts"][0]["state"], "undone")

    def test_pause_stops_further_progress_and_invalid_grants_rejected(self):
        manager = self.manager(lambda job, progress: {})
        task = manager.create(self.body())
        self.now += timedelta(minutes=2)
        job = manager._claim()
        manager.action(task["id"], "pause")
        with self.assertRaisesRegex(RuntimeError, "停止"):
            manager._progress(job, "开始读取")
        for bad in ({"logs": "true", "consent": True}, {"logs": True}, {"files": ["relative.txt"], "consent": True}, {"unknown": True}):
            with self.assertRaises(ValueError):
                normalize_grants(bad)
        self.assertEqual(normalize_grants({"logs": True}, "reminder")["logs"], False)


if __name__ == "__main__":
    unittest.main()
