import io
import json
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from resume_advisor import build_advice_payload, parse_advice_response, prepare_advice_request


def sample_request(consent=True):
    return {
        "consent": consent,
        "goal": "根据近 30 天工作优化第一份简历",
        "resume": {"summary": "参与平台接入与测试", "experience": "示例科技有限公司｜实习生\n2026.09 — 至今｜北京\n核对授权流程", "name": "不应发送的姓名", "phone": "12345678901"},
        "logs": [{"id": "work-1", "date": "2026-10-28", "workspace": "agent", "title": "核对授权范围", "body": "发现回调差异；发布尚未测试"}],
    }


def model_response(source="work-1"):
    advice = {
        "analysis": [{"text": "把尚未测试的限制写清楚", "source_ids": [source]}],
        "suggestions": [{"target": "experience", "text": "示例科技有限公司｜实习生\n2026.09 — 至今｜北京\n授权接入\n- 核对授权范围并记录回调差异；发布能力尚未测试。", "source_ids": [source]}],
    }
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(advice, ensure_ascii=False)}]}]}


class ResumeAdvisorTests(unittest.TestCase):
    def test_explicit_consent_and_limited_material(self):
        with self.assertRaisesRegex(ValueError, "允许"):
            prepare_advice_request(sample_request(False))
        material = prepare_advice_request(sample_request())
        payload = build_advice_payload(material, "test-model", "high")
        sent = json.dumps(payload, ensure_ascii=False)
        self.assertIn("work-1", sent)
        self.assertNotIn("不应发送的姓名", sent)
        self.assertNotIn("12345678901", sent)
        self.assertFalse(payload["store"])

    def test_source_ids_are_validated_and_drafts_start_unchecked(self):
        material = prepare_advice_request(sample_request())
        result = parse_advice_response(model_response(), material)
        self.assertEqual(result["suggestions"][0]["source_ids"], ["work-1"])
        self.assertFalse(result["suggestions"][0]["checked"])
        with self.assertRaisesRegex(ValueError, "可核对"):
            parse_advice_response(model_response("invented"), material)

    def test_fragment_and_invented_employer_are_not_accepted_as_complete_experience(self):
        material = prepare_advice_request(sample_request())
        fragment = model_response()
        fragment["output"][0]["content"][0]["text"] = json.dumps({
            "analysis": [], "suggestions": [{"target": "experience", "text": "核对授权范围并记录回调差异。", "source_ids": ["work-1"]}]
        }, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "可核对"):
            parse_advice_response(fragment, material)
        invented = model_response()
        invented["output"][0]["content"][0]["text"] = json.dumps({
            "analysis": [], "suggestions": [{"target": "experience", "text": "虚构公司｜实习生\n2026.09 — 至今｜北京\n- 完成发布测试", "source_ids": ["work-1"]}]
        }, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "可核对"):
            parse_advice_response(invented, material)

    def test_resume_section_source_is_limited_to_known_fields(self):
        material = prepare_advice_request(sample_request())
        response = model_response()
        data = json.loads(response["output"][0]["content"][0]["text"])
        data["analysis"][0]["resume_section"] = "experience"
        response["output"][0]["content"][0]["text"] = json.dumps(data, ensure_ascii=False)
        self.assertEqual(parse_advice_response(response, material)["analysis"][0]["resume_section"], "experience")
        data["analysis"][0]["resume_section"] = "private_notes"
        response["output"][0]["content"][0]["text"] = json.dumps(data, ensure_ascii=False)
        self.assertEqual(parse_advice_response(response, material)["analysis"][0]["resume_section"], "")

    def test_endpoint_never_calls_model_without_consent(self):
        from ai_server import Handler

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("ai_server.API_KEY", "test-key"), patch("ai_server.open_upstream") as upstream:
                def post(body):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    connection.request("POST", "/api/resume/advise", json.dumps(body, ensure_ascii=False).encode("utf-8"), {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    result = response.status, json.loads(response.read())
                    connection.close()
                    return result

                status, _ = post(sample_request(False))
                self.assertEqual(status, 400)
                upstream.assert_not_called()
                upstream.return_value = io.BytesIO(json.dumps(model_response(), ensure_ascii=False).encode("utf-8"))
                status, result = post(sample_request())
                self.assertEqual(status, 200)
                self.assertEqual(result["suggestions"][0]["source_ids"], ["work-1"])
                upstream.assert_called_once()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
