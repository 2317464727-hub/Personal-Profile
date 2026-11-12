import unittest
import http.client
import threading
from http.server import ThreadingHTTPServer

from resume_suggestions import draft_suggestions, prepare_request


class ResumeSuggestionTests(unittest.TestCase):
    def request(self, logs, resume=None):
        return prepare_request({"logs": logs, "resume": resume or {}})

    def test_drafts_use_recent_record_and_keep_source(self):
        material = self.request([
            {"id": "older", "date": "2026-10-20", "workspace": "personal", "title": "整理平台界面", "body": "调整记录展示和预览"},
            {"id": "newer", "date": "2026-10-27", "workspace": "agent", "title": "完成发布平台接入核对", "body": "核对授权流程，尚未发布成功"},
        ])
        suggestions = draft_suggestions(material)
        self.assertEqual(suggestions[0]["source_ids"], ["newer"])
        self.assertEqual(suggestions[0]["target"], "experience")
        self.assertTrue(suggestions[0]["structured"])
        self.assertIn("北京四方小仓科技有限公司", suggestions[0]["text"])
        self.assertIn("社交内容发布平台接入", suggestions[0]["text"])
        self.assertIn("尚未发布成功", suggestions[0]["text"])

    def test_related_records_are_summarized_with_sources(self):
        material = self.request([
            {"id": "first", "date": "2026-10-26", "workspace": "agent", "title": "核对 X 账号与 CMS 分组", "body": "确认授权范围"},
            {"id": "second", "date": "2026-10-27", "workspace": "agent", "title": "整理发布平台交付报告", "body": "保留未完成项说明"},
        ])
        suggestions = draft_suggestions(material)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["source_ids"], ["second", "first"])
        self.assertIn("核对 X 账号与 CMS 分组", suggestions[0]["text"])
        self.assertIn("整理发布平台交付报告", suggestions[0]["text"])

    def test_skips_existing_text_and_duplicate_records(self):
        record = {"id": "one", "date": "2026-10-27", "workspace": "agent", "title": "完成渠道接入核对", "body": "核对权限范围"}
        material = self.request([record, record], {"projects": "完成渠道接入核对：核对权限范围"})
        self.assertEqual(len(material["logs"]), 1)
        self.assertEqual(draft_suggestions(material), [])

    def test_redacts_secrets_from_drafts(self):
        material = self.request([{"id": "secret", "date": "2026-10-27", "workspace": "agent", "title": "梳理接口权限", "body": "access_token=abcdef123456 与 sk-abcdefghijklmnopqrst 及 https://example.com/callback 均已检查"}])
        text = draft_suggestions(material)[0]["text"]
        self.assertNotIn("abcdef123456", text)
        self.assertNotIn("sk-abcdefghijklmnopqrst", text)
        self.assertNotIn("https://example.com/callback", text)

    def test_rejects_more_than_40_records(self):
        with self.assertRaisesRegex(ValueError, "40"):
            self.request([{"id": str(i), "date": "2026-10-27", "title": "工作记录"} for i in range(41)])

    def test_current_template_gives_projects_a_title_date_and_work_items(self):
        material = prepare_request({"template": "current-a4-v1", "resume": {}, "logs": [
            {"id": "one", "date": "2026-10-27", "workspace": "personal", "title": "调整简历模板", "body": "完成双栏展示，PDF 仍待核对"},
            {"id": "two", "date": "2026-10-28", "workspace": "personal", "title": "核对单页导出", "body": "修复排版容量限制"},
        ]})
        draft = draft_suggestions(material)[0]
        self.assertEqual(draft["target"], "projects")
        self.assertTrue(draft["structured"])
        self.assertTrue(draft["text"].startswith("项目名称：个人平台\n2026.10\n工作内容：\n- "))
        self.assertIn("PDF 仍待核对", draft["text"])
        self.assertEqual(draft["source_ids"], ["two", "one"])
        self.assertNotIn("至今", draft["text"])

    def test_current_template_keeps_company_grouping_and_uncertain_results(self):
        material = prepare_request({"template": "current-a4-v1", "resume": {}, "logs": [
            {"id": "one", "date": "2026-10-27", "workspace": "agent", "title": "核对平台授权入口", "body": "图片上传尚未测试"},
            {"id": "two", "date": "2026-10-28", "workspace": "inventory", "title": "完成 CSV 字段映射", "body": "实际库存未修改"},
        ]})
        text = draft_suggestions(material)[0]["text"]
        self.assertEqual(text.count("北京四方小仓科技有限公司"), 1)
        self.assertIn("社交内容发布平台接入", text)
        self.assertIn("库存风险工作台", text)
        self.assertIn("尚未测试", text)
        self.assertIn("实际库存未修改", text)

    def test_template_script_is_served_by_local_platform(self):
        from ai_server import Handler

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/resume_template.js")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("javascript", response.getheader("Content-Type"))
            self.assertIn(b"root.ResumeTemplate", response.read())
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
