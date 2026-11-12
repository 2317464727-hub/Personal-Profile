import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from intern_summary import BEIJING, SummaryManager


class SummaryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.calls = []

        def generate(start, end, logs):
            self.calls.append((start, end, logs))
            return {"title": "工作回顾", "highlights": ["完成记录整理"], "next": "继续核对"}

        self.manager = SummaryManager(self.temp.name, generate)
        self.manager.sync_logs([
            {"id": "one", "date": "2030-01-12", "workspace": "agent", "title": "平台接入", "body": "记录测试结果"},
            {"id": "old", "date": "2029-12-01", "workspace": "agent", "title": "过期记录"},
        ])

    def configure(self, enabled=True):
        with patch("intern_summary.now_beijing", return_value=datetime(2030, 1, 1, 9, tzinfo=BEIJING)):
            self.manager.configure({"enabled": enabled, "date": "2030-01-14", "time": "09:00"})

    def test_due_run_uses_two_week_window_and_does_not_duplicate(self):
        self.configure()
        with patch("intern_summary.now_beijing", return_value=datetime(2030, 1, 14, 9, tzinfo=BEIJING)):
            self.assertTrue(self.manager.run_due())
            self.assertFalse(self.manager.run_due())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((self.calls[0][0], self.calls[0][1]), ("2030-01-01", "2030-01-14"))
        self.assertEqual([item["id"] for item in self.calls[0][2]], ["one"])
        status = self.manager.status()
        self.assertEqual(status["next_run"], "2030-01-28T09:00")
        self.assertEqual(len(status["summaries"]), 1)

    def test_disabled_schedule_does_not_run(self):
        self.configure(False)
        with patch("intern_summary.now_beijing", return_value=datetime(2030, 1, 14, 9, tzinfo=BEIJING)):
            self.assertFalse(self.manager.run_due())
        self.assertFalse(self.calls)

    def test_failure_retries_after_one_hour(self):
        self.configure()

        def broken(*args):
            raise RuntimeError("temporary failure")

        self.manager.generate = broken
        with patch("intern_summary.now_beijing", return_value=datetime(2030, 1, 14, 9, tzinfo=BEIJING)):
            self.assertFalse(self.manager.run_due())
            self.assertFalse(self.manager.run_due())
        self.assertEqual(self.manager.status()["retry_after"], "2030-01-14T10:00")
        self.manager.generate = lambda *args: {"title": "重试成功", "highlights": ["已完成"]}
        with patch("intern_summary.now_beijing", return_value=datetime(2030, 1, 14, 10, tzinfo=BEIJING)):
            self.assertTrue(self.manager.run_due())
        self.assertEqual(len(self.manager.status()["summaries"]), 1)
        self.assertEqual(self.manager.status()["last_error"], "")


if __name__ == "__main__":
    unittest.main()
