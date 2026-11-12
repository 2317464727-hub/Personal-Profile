import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import project_tools


class ProjectToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name) / "repository"
        self.root.mkdir()
        self.addCleanup(self.temp.cleanup)
        self.root_patch = patch.object(project_tools, "PROJECT_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_exact_replacement_and_new_file(self):
        target = self.root / "src.py"
        target.write_bytes(b"first\r\nsecond\r\n")
        result = project_tools.replace_text("src.py", "second", "changed")
        self.assertEqual(target.read_bytes(), b"first\r\nchanged\r\n")
        self.assertIn("+changed", result["change"]["diff"])
        created = project_tools.replace_text("new.js", "", "export const ready = true;\n")
        self.assertTrue(created["change"]["created"])
        self.assertEqual((self.root / "new.js").read_text(encoding="utf-8"), "export const ready = true;\n")

    def test_rejects_outside_sensitive_and_ambiguous_edits(self):
        (self.root / "main.py").write_text("same\nsame\n", encoding="utf-8")
        for path in ("../outside.py", str(self.root.parent / "outside.py"), ".env", ".git/config.py", "密钥/demo.py", "image.png"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                project_tools.replace_text(path, "", "content")
        with self.assertRaisesRegex(ValueError, "唯一匹配"):
            project_tools.replace_text("main.py", "same", "changed")
        self.assertEqual((self.root / "main.py").read_text(encoding="utf-8"), "same\nsame\n")
        with self.assertRaisesRegex(ValueError, "文件已存在"):
            project_tools.replace_text("main.py", "", "overwrite")

    def test_project_read_is_confined_to_repository(self):
        with patch.object(project_tools, "run_tool", return_value="ok") as reader:
            self.assertEqual(project_tools.run_project_read_tool("list_dir", '{"path":""}'), "ok")
            self.assertEqual(reader.call_args.args[1]["path"], str(self.root.resolve()))
            self.assertIn("路径回退", project_tools.run_project_read_tool("read_file", '{"path":"../outside.py"}'))
            self.assertIn("此路径不可读取", project_tools.run_project_read_tool("read_file", '{"path":".local-data/private.py"}'))
            self.assertEqual(reader.call_count, 1)

    def test_only_fixed_test_commands_run_without_secrets_or_shell(self):
        with self.assertRaises(ValueError):
            project_tools.check_commands("powershell -Command anything")
        fake = subprocess.CompletedProcess(["python"], 0, "OK\n", "")
        with patch.object(project_tools.subprocess, "run", return_value=fake) as runner, \
             patch.dict(os.environ, {"SUB2API_API_KEY": "private-test-key"}):
            result = project_tools.run_check("personal_python")
        self.assertTrue(result["check"]["passed"])
        self.assertFalse(runner.call_args.kwargs["shell"])
        self.assertNotIn("SUB2API_API_KEY", runner.call_args.kwargs["env"])
        self.assertEqual(runner.call_args.kwargs["cwd"], self.root)


if __name__ == "__main__":
    unittest.main()
