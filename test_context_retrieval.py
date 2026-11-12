import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import context_retrieval
from ai_server import build_payload


class ContextRetrievalTests(unittest.TestCase):
    def test_file_search_returns_relevant_safe_excerpt(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            (root / "inventory-note.md").write_text("库存风险诊断：只读核查高库存，补货仍为模拟。", encoding="utf-8")
            (root / "other-note.md").write_text("视频脚本整理。", encoding="utf-8")
            (root / ".env").write_text("库存风险诊断 SECRET_MARKER", encoding="utf-8")
            with patch.object(context_retrieval, "ROOTS", [root]):
                found = context_retrieval.retrieve_files("库存风险诊断", "files")
            self.assertEqual(len(found), 1)
            self.assertEqual(Path(found[0]["source"]).name, "inventory-note.md")
            self.assertIn("补货仍为模拟", found[0]["excerpt"])
            self.assertNotIn("SECRET_MARKER", str(found))
            self.assertEqual(context_retrieval.retrieve_files("库存风险诊断", "none"), [])

    def test_unapproved_material_never_enters_model_payload(self):
        messages = [{"role": "user", "content": "库存风险诊断"}]
        marker = "PRIVATE_FILE_EXCERPT"
        denied = build_payload(messages, "PRIVATE_LOG", True, local_access={}, file_context=marker)
        self.assertNotIn(marker, denied["instructions"])
        self.assertNotIn("PRIVATE_LOG", denied["instructions"])
        approved = build_payload(messages, "[周历:old] 库存风险诊断", True,
                                 local_access={"records": True, "files": True}, file_context=marker)
        self.assertIn(marker, approved["instructions"])
        self.assertIn("[周历:old]", approved["instructions"])


if __name__ == "__main__":
    unittest.main()
