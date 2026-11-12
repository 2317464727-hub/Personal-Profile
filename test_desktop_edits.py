import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_server
from desktop_edits import DesktopEditManager
from file_tools import allowed


class DesktopEditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.desktop = root / "Desktop"
        self.desktop.mkdir()
        self.manager = DesktopEditManager(self.desktop, root / "backups")

    def test_preview_commit_backup_and_undo(self):
        target = self.desktop / "notes.txt"
        target.write_bytes(b"first\r\nsecond\r\n")
        preview = self.manager.preview({"path": str(target), "old_text": "second", "new_text": "changed"})
        self.assertIn("second", self.manager.inspect(str(target))["content"])
        self.assertEqual(target.read_bytes(), b"first\r\nsecond\r\n")
        self.assertIn("+changed", preview["diff"])
        committed = self.manager.commit(preview["stage_id"])
        self.assertEqual(target.read_bytes(), b"first\r\nchanged\r\n")
        self.assertEqual(Path(committed["backup"]).read_bytes(), b"first\r\nsecond\r\n")
        self.manager.undo(committed["id"])
        self.assertEqual(target.read_bytes(), b"first\r\nsecond\r\n")
        self.assertEqual(self.manager.history()[0]["status"], "undone")

    def test_rejects_changed_file_before_commit_or_undo(self):
        target = self.desktop / "notes.md"
        target.write_text("first", encoding="utf-8")
        preview = self.manager.preview({"path": str(target), "old_text": "first", "new_text": "second"})
        target.write_text("external", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "发生变化"):
            self.manager.commit(preview["stage_id"])
        self.assertEqual(target.read_text(encoding="utf-8"), "external")
        fresh = self.manager.preview({"path": str(target), "old_text": "external", "new_text": "second"})
        committed = self.manager.commit(fresh["stage_id"])
        target.write_text("later", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "发生变化"):
            self.manager.undo(committed["id"])
        self.assertEqual(target.read_text(encoding="utf-8"), "later")

    def test_rejects_outside_sensitive_and_ambiguous_paths(self):
        outside = self.desktop.parent / "outside.txt"
        outside.write_text("text", encoding="utf-8")
        secret = self.desktop / "密码.txt"
        secret.write_text("text", encoding="utf-8")
        inside = self.desktop / "notes.txt"
        inside.write_text("same same", encoding="utf-8")
        for path in (str(outside), str(secret), str(self.desktop / ".." / "outside.txt"), "notes.txt"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.manager.preview({"path": path, "old_text": "text", "new_text": "edited"})
        with self.assertRaisesRegex(ValueError, "恰好出现一次"):
            self.manager.preview({"path": str(inside), "old_text": "same", "new_text": "edited"})
        with self.assertRaises(ValueError):
            allowed(str(Path(__file__).resolve().parent / ".desktop-edit-backups" / "sample.bak"))
        link = self.desktop / "link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaises(ValueError):
                self.manager.preview({"path": str(link), "old_text": "text", "new_text": "edited"})

    def test_word_image_and_pdf_previews_do_not_write(self):
        from docx import Document
        from PIL import Image
        from pypdf import PdfWriter

        word = self.desktop / "resume.docx"
        doc = Document()
        doc.add_paragraph("Original line")
        doc.save(word)
        image = self.desktop / "photo.png"
        Image.new("RGB", (80, 100), "red").save(image)
        pdf = self.desktop / "page.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        with pdf.open("wb") as stream:
            writer.write(stream)
        for target, options in (
            (word, {"old_text": "Original", "new_text": "Updated"}),
            (image, {"operation": "resize", "width": 40, "height": 50}),
            (pdf, {"operation": "rotate", "page": 1, "angle": 90}),
        ):
            with self.subTest(target=target):
                before = target.read_bytes()
                preview = self.manager.preview({"path": str(target), **options})
                self.assertEqual(self.manager.inspect(str(target))["kind"], preview["kind"])
                self.assertTrue(preview["diff"])
                self.assertEqual(target.read_bytes(), before)
                applied = self.manager.commit(preview["stage_id"])
                self.assertNotEqual(target.read_bytes(), before)
                self.manager.undo(applied["id"])
                self.assertEqual(target.read_bytes(), before)

    def test_ai_draft_requires_single_use_consent_and_only_stages(self):
        target = self.desktop / "notes.txt"
        target.write_text("first", encoding="utf-8")
        answer = {"output": [{"type": "message", "content": [{"text": json.dumps({"old_text": "first", "new_text": "second"})}]}]}
        with patch.object(ai_server, "DESKTOP_EDITS", self.manager), \
             patch.object(ai_server, "API_KEY", "test-key"), \
             patch.object(ai_server, "open_upstream", return_value=io.BytesIO(json.dumps(answer).encode("utf-8"))) as upstream:
            with self.assertRaisesRegex(ValueError, "允许"):
                ai_server.draft_desktop_edit({"path": str(target), "instruction": "修改"})
            upstream.assert_not_called()
            result = ai_server.draft_desktop_edit({"path": str(target), "instruction": "修改", "allow_model": True})
        self.assertEqual(result["new_text"], "second")
        self.assertIn("+second", result["diff"])
        self.assertEqual(target.read_text(encoding="utf-8"), "first")


if __name__ == "__main__":
    unittest.main()
