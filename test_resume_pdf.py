import http.client
import base64
import io
import json
import re
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader
from PIL import Image
from resume_pdf import _fit_resume, _fonts, render_resume_pdf, validate_resume


def sample_resume():
    return {
        "name": "测试用户", "role": "AI 应用开发工程师", "contacts": ["北京", "test@example.com"],
        "main": [
            {"title": "实习经历", "items": [
                {"type": "title", "text": "示例科技有限公司"},
                {"type": "meta", "text": "2025.12 - 2026.03 · 全栈开发实习生"},
                {"type": "paragraph", "text": "参与智能求职管理平台开发，完成业务接口和大模型模块。"},
                {"type": "bullet", "text": "完成身份认证、Redis 缓存优化及 2000+ 岗位数据入库。"},
            ]},
            {"title": "项目经历", "items": [
                {"type": "title", "text": "本地 Agent 系统"},
                {"type": "meta", "text": "2026.05 - 至今 · AI 应用开发"},
                {"type": "label", "text": "核心设计"},
                {"type": "bullet", "text": "实现工具调用、流式输出、任务检查点与上下文管理。"},
                {"type": "bullet", "text": "支持 JSON-RPC 2.0、NDJSON 和多客户端订阅。"},
            ]},
        ],
        "aside": [
            {"title": "教育背景", "items": [{"type": "paragraph", "text": "2023.09 - 2027.07 示例大学 · 计算机科学 · 本科"}]},
            {"title": "技术与方法", "items": [{"type": "bullet", "text": "熟悉 Python、FastAPI、RAG、Agent 与 MCP。"}]},
            {"title": "荣誉奖项", "items": [{"type": "bullet", "text": "数学建模竞赛省二等奖"}]},
        ],
        "footer": [{"title": "个人优势", "items": [{"type": "bullet", "text": "学习上：自学能力强，重视工程实践。"}]}],
    }


def dense_resume():
    """Anonymized real-world layout: retain word widths, lengths and item order.

    CJK runs are encoded as ~length~ and replaced with a generic character.
    Latin letters use equal or wider anonymous glyphs; no resume text is stored.
    """
    path = Path(__file__).with_name("testdata") / "dense_resume.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for column in ("main", "aside", "footer"):
        for section in data[column]:
            section["items"] = [
                {"type": kind, "text": re.sub(r"~(\d+)~", lambda m: "文" * int(m[1]), text)}
                for kind, text in section["items"]
            ]
    return data


class ResumePdfTests(unittest.TestCase):
    def test_dense_body_type_is_slightly_smaller(self):
        _fonts()
        layout = _fit_resume(validate_resume(dense_resume()))
        self.assertLessEqual(layout["size"], 8.0)
        self.assertGreaterEqual(layout["size"], 6.8)

    def test_realistic_dense_layout_keeps_every_item_on_one_page(self):
        payload = dense_resume()
        reader = PdfReader(io.BytesIO(render_resume_pdf(payload)))
        self.assertEqual(len(reader.pages), 1)
        text = "".join(reader.pages[0].extract_text().split())
        for column in ("main", "aside", "footer"):
            for section in payload[column]:
                for row in section["items"]:
                    with self.subTest(column=column, text=row["text"]):
                        self.assertIn("".join(row["text"].split()), text)

    def test_searchable_single_a4_and_footer(self):
        result = render_resume_pdf(sample_resume())
        self.assertTrue(result.startswith(b"%PDF"))
        reader = PdfReader(io.BytesIO(result))
        self.assertEqual(len(reader.pages), 1)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.276, places=2)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.height), 841.890, places=2)
        text = reader.pages[0].extract_text()
        for value in ("测试用户", "示例科技有限公司", "2000+", "JSON-RPC", "省二等奖", "个人优势", "自学能力强"):
            self.assertIn(value, text)
        self.assertGreater(text.index("个人优势"), text.index("荣誉奖项"))
        self.assertNotIn("127.0.0.1", text)

    def test_uploaded_photo_is_embedded_without_hiding_resume_text(self):
        image = Image.new("RGB", (120, 160), (36, 107, 117))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        payload = sample_resume()
        payload["photo"] = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        reader = PdfReader(io.BytesIO(render_resume_pdf(payload)))
        self.assertEqual(len(reader.pages), 1)
        self.assertIn("示例科技有限公司", reader.pages[0].extract_text())
        images = reader.pages[0]["/Resources"].get("/XObject", {})
        self.assertTrue(any(item.get_object().get("/Subtype") == "/Image" for item in images.values()))
        portrait_layout = _fit_resume(validate_resume(payload))
        self.assertLess(portrait_layout["photo_width"], portrait_layout["photo_height"])
        square = Image.new("RGB", (120, 120), (36, 107, 117))
        buffer = io.BytesIO()
        square.save(buffer, format="JPEG")
        payload["photo"] = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        square_layout = _fit_resume(validate_resume(payload))
        self.assertAlmostEqual(square_layout["photo_width"], square_layout["photo_height"])
        self.assertGreater(square_layout["top"], portrait_layout["top"])

    def test_dense_resume_is_fitted_without_losing_last_items(self):
        payload = sample_resume()
        for column in ("main", "aside"):
            for section in payload[column]:
                section["items"] *= 5
        payload["main"][-1]["items"].append({"type": "bullet", "text": "项目末尾核对标记"})
        reader = PdfReader(io.BytesIO(render_resume_pdf(payload)))
        self.assertEqual(len(reader.pages), 1)
        self.assertIn("项目末尾核对标记", reader.pages[0].extract_text())

    def test_excess_content_reports_error_instead_of_clipping(self):
        payload = sample_resume()
        payload["main"][0]["items"] = [{"type": "paragraph", "text": "这是一段需要保留的项目经历。" * 250}] * 20
        with self.assertRaisesRegex(ValueError, "文字过小"):
            render_resume_pdf(payload)

    def test_imported_markup_remains_plain_text(self):
        payload = sample_resume()
        payload["main"][0]["items"].append({"type": "paragraph", "text": '<script>test</script> & <img src="https://example.com/">'})
        text = PdfReader(io.BytesIO(render_resume_pdf(payload))).pages[0].extract_text()
        self.assertIn("<script>test</script>", text)
        self.assertIn('src="https://example.com/"', text)

    def test_long_titles_metadata_and_contacts_wrap_without_text_loss(self):
        payload = sample_resume()
        payload["name"] = "用于核对换行的较长姓名"
        payload["role"] = "AI 应用开发与企业知识库检索系统工程师 · 实习岗位"
        payload["contacts"] += ["portfolio.example.com/projects/" + "long-project-name/" * 8]
        payload["main"][0]["items"][0]["text"] = "示例人工智能应用研发与技术咨询服务有限公司"
        payload["main"][0]["items"].insert(2, {
            "type": "meta", "text": "企业知识库与自动化业务部门 · AI 应用开发工程师 · 北京及远程协作"
        })
        result = PdfReader(io.BytesIO(render_resume_pdf(payload)))
        self.assertEqual(len(result.pages), 1)
        compact = "".join(result.pages[0].extract_text().split())
        expected = [payload["name"], payload["role"], *payload["contacts"]]
        expected += [item["text"] for section in payload["main"] for item in section["items"]]
        for text in expected:
            with self.subTest(text=text):
                self.assertIn("".join(text.split()), compact)

    def test_invalid_and_empty_requests(self):
        for payload in (None, [], {}, {"name": 3}, {"main": "bad"}, {"main": [{"items": [{"type": "html", "text": "bad"}]}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                render_resume_pdf(payload)

    def test_download_endpoint_and_origin_restriction(self):
        from ai_server import Handler

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("ai_server.API_KEY", ""), patch("ai_server.urlopen", side_effect=AssertionError("PDF must stay local")):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
                connection.request("POST", "/api/resume/pdf", json.dumps(sample_resume()), {"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "application/pdf")
                self.assertIn("attachment", response.getheader("Content-Disposition"))
                self.assertEqual(len(PdfReader(io.BytesIO(response.read())).pages), 1)
                connection.close()
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("POST", "/api/resume/pdf", "{}", {"Origin": "https://example.com"})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
