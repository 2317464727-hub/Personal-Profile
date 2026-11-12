import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import ai_server
from agent_checkpoints import CheckpointStore
from file_tools import is_sensitive_name


class AgentLimitTests(unittest.TestCase):
    def test_model_request_uses_configured_reasoning_and_actor_header(self):
        payload = ai_server.build_payload([{"role": "user", "content": "测试"}], "", False)
        self.assertEqual(payload["model"], ai_server.MODEL)
        self.assertEqual(payload["reasoning"], {"effort": ai_server.REASONING_EFFORT})
        self.assertFalse(payload["store"])
        with patch.object(ai_server, "API_KEY", "test-key"), \
             patch.object(ai_server, "ACTOR_AUTHORIZATION", "local-image-extension"), \
             patch.object(ai_server, "urlopen", return_value=object()) as opener:
            ai_server.open_upstream(payload)
        request = opener.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-openai-actor-authorization"], "local-image-extension")
        self.assertEqual(headers["authorization"], "Bearer test-key")

    def test_browser_modes_only_expose_authorized_tools(self):
        message = [{"role": "user", "content": "查看网页"}]
        granted = {"records": True, "editor": True, "files": True}
        read = ai_server.build_payload(message, "PrivateRecord", True, "read", granted, "PrivateEditor")
        control = ai_server.build_payload(message, "PrivateRecord", True, "control", granted, "PrivateEditor")
        self.assertNotIn("PrivateRecord", read["instructions"])
        self.assertNotIn("PrivateEditor", read["instructions"])
        read_tools = {item.get("name") for item in read["tools"]}
        control_tools = {item.get("name") for item in control["tools"]}
        self.assertIn("browser_read", read_tools)
        self.assertIn("browser_open", read_tools)
        self.assertNotIn("browser_click", read_tools)
        self.assertNotIn("read_file", read_tools)
        self.assertIn("browser_click", control_tools)
        self.assertIn("browser_fill", control_tools)
        self.assertNotIn("read_file", control_tools)

    def test_local_material_requires_individual_permission(self):
        message = [{"role": "user", "content": "问题", "images": ["data:image/png;base64,AAA"]}]
        with patch("file_tools.activity_snapshot", side_effect=AssertionError("desktop snapshot must not run")):
            plain = ai_server.build_payload(message, "PrivateRecord", True, editor_context="PrivateEditor")
            records = ai_server.build_payload(message, "PrivateRecord", True, local_access={"records": True}, editor_context="PrivateEditor")
            editor = ai_server.build_payload(message, "PrivateRecord", True, local_access={"editor": True}, editor_context="PrivateEditor")
            files = ai_server.build_payload(message, "PrivateRecord", True, local_access={"files": True}, editor_context="PrivateEditor")
        self.assertNotIn("PrivateRecord", plain["instructions"])
        self.assertNotIn("PrivateEditor", plain["instructions"])
        self.assertEqual(plain["input"][0]["content"], "问题")
        self.assertNotIn("read_file", {tool.get("name") for tool in plain["tools"]})
        self.assertIn("PrivateRecord", records["instructions"])
        self.assertNotIn("PrivateEditor", records["instructions"])
        self.assertNotIn("PrivateRecord", editor["instructions"])
        self.assertIn("PrivateEditor", editor["instructions"])
        self.assertEqual(editor["input"][0]["content"][1]["type"], "input_image")
        self.assertNotIn("PrivateRecord", files["instructions"])
        self.assertNotIn("PrivateEditor", files["instructions"])
        self.assertIn("read_file", {tool.get("name") for tool in files["tools"]})

    def test_long_term_terms_are_bounded_and_do_not_grant_file_access(self):
        payload = ai_server.build_payload([{"role": "user", "content": "问题"}], "", True,
                                          memory_terms=["库存", "password123", "sk-secret", "12345678901", "项目"])
        self.assertIn("库存、项目", payload["instructions"])
        self.assertNotIn("password123", payload["instructions"])
        self.assertNotIn("sk-secret", payload["instructions"])
        self.assertNotIn("read_file", {tool.get("name") for tool in payload["tools"]})
        self.assertTrue(is_sensitive_name(".agent-checkpoints.json"))

    def test_ungranted_file_tool_is_not_executed(self):
        payload = {"input": [], "_file_access": False}
        call = {"name": "read_file", "arguments": '{"path":"private"}', "call_id": "one"}
        with patch.object(ai_server, "run_tool", side_effect=AssertionError("must not read")):
            ai_server.append_tool_results(payload, [call])
        self.assertEqual(payload["input"][-1]["output"], "本次未授权此工具")

    def test_project_tools_require_separate_grant(self):
        message = [{"role": "user", "content": "修复项目"}]
        plain = ai_server.build_payload(message, "", True, local_access={"files": True})
        project = ai_server.build_payload(message, "", True, local_access={"project": True})
        browser = ai_server.build_payload(message, "", True, "read", {"project": True})
        self.assertNotIn("project_replace", {tool.get("name") for tool in plain["tools"]})
        self.assertIn("project_replace", {tool.get("name") for tool in project["tools"]})
        self.assertIn("read_file", {tool.get("name") for tool in project["tools"]})
        self.assertEqual(project["_file_scope"], "project")
        self.assertNotIn("project_replace", {tool.get("name") for tool in browser["tools"]})
        call = {"name": "project_replace", "arguments": "{}", "call_id": "project"}
        with patch.object(ai_server, "run_project_tool", side_effect=AssertionError("must not edit")):
            ai_server.append_tool_results({"input": [], "_project_access": False}, [call])
        self.assertEqual(call["_result"], "本次未授权此工具")

    def test_project_changes_and_checks_stream_to_page(self):
        turns = 0

        def consume(_payload, calls):
            nonlocal turns
            if turns == 0:
                calls.extend([
                    {"name": "project_replace", "arguments": '{"path":"personal/demo.py"}', "call_id": "edit"},
                    {"name": "project_run_check", "arguments": '{"check":"personal_python"}', "call_id": "check"},
                ])
            turns += 1
            return iter(())

        reports = [
            {"output": "已修改 personal/demo.py", "change": {"path": "personal/demo.py", "diff": "-old\n+new"}},
            {"output": "测试通过：personal_python", "check": {"name": "personal_python", "passed": True, "output": "OK"}},
        ]
        with patch.object(ai_server, "build_payload", return_value={"input": [], "_project_access": True}), \
             patch.object(ai_server, "consume_round", side_effect=consume), \
             patch.object(ai_server, "run_project_tool", side_effect=reports):
            events = list(ai_server.translate([{"role": "user", "content": "修复"}], ""))
        self.assertEqual([name for name, _ in events].count("change"), 1)
        self.assertEqual([name for name, _ in events].count("check"), 1)
        self.assertEqual(events[-1][0], "done")

    def test_preview_syncs_once_and_preserves_browser_navigation(self):
        with patch.object(ai_server, "PREVIEW_OPEN", True), \
             patch.object(ai_server, "PREVIEW_URL", "https://example.com/"), \
             patch.object(ai_server, "PREVIEW_GENERATION", 42), \
             patch.object(ai_server, "LAST_BROWSER_PREVIEW_GENERATION", -1), \
             patch.object(ai_server, "LAST_BROWSER_SYNC_URL", ""), \
             patch.object(ai_server, "browser_command", side_effect=[{"connected": False}, {}, {"connected": True}]) as command:
            ai_server.sync_preview_browser()
            ai_server.sync_preview_browser()
        self.assertEqual(command.call_args_list[1].args, ("open", {"url": "https://example.com/"}))
        self.assertEqual(command.call_count, 3)

    def test_explicit_preview_url_survives_server_state_loss(self):
        with patch.object(ai_server, "PREVIEW_OPEN", False), \
             patch.object(ai_server, "PREVIEW_URL", ""), \
             patch.object(ai_server, "LAST_BROWSER_SYNC_URL", ""), \
             patch.object(ai_server, "browser_command", side_effect=[{"connected": False}, {}]) as command:
            ai_server.sync_preview_browser("https://example.com/")
        self.assertEqual(command.call_args_list[1].args, ("open", {"url": "https://example.com/"}))

    def run_rounds(self, rounds):
        seen = []
        executed = []

        def consume(_payload, calls):
            index = len(seen)
            seen.append(index)
            calls.extend(rounds[index])
            return iter(())

        def execute(_payload, calls, _access):
            executed.append([call["name"] for call in calls])

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            with patch.object(ai_server, "CHECKPOINTS", CheckpointStore(Path(folder) / "checkpoints.json")), \
                 patch.object(ai_server, "build_payload", return_value={"input": []}), \
                 patch.object(ai_server, "consume_round", side_effect=consume), \
                 patch.object(ai_server, "append_tool_results", side_effect=execute):
                events = list(ai_server.translate([{"role": "user", "content": "test"}], ""))
        return seen, executed, events

    def test_stops_after_five_tool_rounds(self):
        rounds = [[{"name": "read_file", "arguments": '{"path":"%s"}' % index, "call_id": str(index)}]
                  for index in range(5)]
        seen, executed, events = self.run_rounds(rounds)
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(executed), 5)
        self.assertEqual(events[-2][0], "checkpoint")
        self.assertTrue(events[-1][1]["paused"])

    def test_fourth_consecutive_identical_call_is_not_executed(self):
        rounds = [[{"name": "read_file", "arguments": '{"path":"same","offset":0}' if index % 2 else '{"offset":0,"path":"same"}', "call_id": "read-%s" % index},
                   {"name": "search_files", "arguments": '{"query":"%s"}' % index, "call_id": "search-%s" % index}]
                  for index in range(4)]
        seen, executed, events = self.run_rounds(rounds)
        self.assertEqual(len(seen), 4)
        self.assertEqual(len(executed), 3)
        self.assertIn("3 轮", events[-2][1]["delta"])
        self.assertIn("连续 3 轮", events[-1][1]["note"])

    def test_nonconsecutive_call_resets_repeat_count(self):
        rounds = [[{"name": "read_file", "arguments": '{"path":"%s"}' % path, "call_id": str(index)}]
                  for index, path in enumerate(("same", "same", "other", "same", "same"))]
        seen, executed, events = self.run_rounds(rounds)
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(executed), 5)
        self.assertTrue(events[-1][1]["paused"])

    def test_checkpoint_resumes_after_store_restart_with_same_scope(self):
        rounds = []

        def consume(payload, calls):
            rounds.append(len(payload["input"]))
            if len(rounds) <= 5:
                calls.append({"name": "read_file", "arguments": '{"path":"%s"}' % len(rounds), "call_id": str(len(rounds))})
                return iter(())
            return iter([("text", {"delta": "最终回答"})])

        def execute(payload, calls, _access):
            payload["input"].append({"type": "function_call_output", "output": "第 %s 轮结果" % len(rounds)})

        scope = ai_server.access_scope("none", {"project": True})
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / "checkpoints.json"
            with patch.object(ai_server, "CHECKPOINTS", CheckpointStore(path)), \
                 patch.object(ai_server, "build_payload", return_value={"input": []}), \
                 patch.object(ai_server, "consume_round", side_effect=consume), \
                 patch.object(ai_server, "append_tool_results", side_effect=execute):
                first = list(ai_server.translate([{"role": "user", "content": "任务"}], "", local_access={"project": True}))
            checkpoint_id = next((data["id"] for name, data in first if name == "checkpoint"), None)
            self.assertIsNotNone(checkpoint_id, first)
            restarted = CheckpointStore(path)
            self.assertEqual(len(restarted.load(checkpoint_id, scope)["payload"]["input"]), 5)
            restarted.claim(checkpoint_id, scope)
            with self.assertRaisesRegex(ValueError, "正在另一个页面"):
                restarted.claim(checkpoint_id, scope)
            self.assertFalse(restarted.delete(checkpoint_id))
            restarted.release(checkpoint_id)
            with patch.object(ai_server, "CHECKPOINTS", restarted), \
                 patch.object(ai_server, "build_payload", side_effect=AssertionError("must resume saved payload")), \
                 patch.object(ai_server, "consume_round", side_effect=consume):
                denied = list(ai_server.translate([], "", checkpoint_id=checkpoint_id, local_access={"files": True}))
                resumed = list(ai_server.translate([], "", checkpoint_id=checkpoint_id, local_access={"project": True}))
            self.assertEqual(denied[0][0], "error")
            self.assertIn("权限", denied[0][1]["error"])
            self.assertEqual(rounds[-1], 5)
            self.assertIn(("text", {"delta": "最终回答"}), resumed)
            self.assertEqual(resumed[-1], ("done", {"model": ai_server.MODEL}))
            with self.assertRaises(ValueError):
                restarted.load(checkpoint_id, scope)

    def test_progress_checkpoint_survives_interrupted_second_round(self):
        rounds = []

        def consume(payload, calls):
            rounds.append(len(payload["input"]))
            if len(rounds) == 1:
                calls.append({"name": "read_file", "arguments": '{}', "call_id": "first"})
                return iter(())
            raise RuntimeError("连接中断")

        def execute(payload, calls, _access):
            payload["input"].append({"type": "function_call_output", "output": "第一轮结果"})

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / "checkpoints.json"
            store = CheckpointStore(path)
            with patch.object(ai_server, "CHECKPOINTS", store), \
                 patch.object(ai_server, "build_payload", return_value={"input": []}), \
                 patch.object(ai_server, "consume_round", side_effect=consume), \
                 patch.object(ai_server, "append_tool_results", side_effect=execute):
                events = []
                with self.assertRaisesRegex(RuntimeError, "连接中断"):
                    for event in ai_server.translate([{"role": "user", "content": "任务"}], ""):
                        events.append(event)
            identifier = next(data["id"] for name, data in events if name == "progress_checkpoint")
            restarted = CheckpointStore(path)
            item = restarted.load(identifier, ai_server.access_scope("none", None))
            self.assertEqual(item["payload"]["input"][-1]["output"], "第一轮结果")
            self.assertFalse(store.is_active(identifier))


if __name__ == "__main__":
    unittest.main()
