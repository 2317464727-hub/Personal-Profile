"""Preview and explicitly confirm edits to one selected desktop file."""

import base64
import difflib
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from file_tools import SKIP_DIRS, is_sensitive_name


TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".html", ".css", ".js", ".py"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_SUFFIXES = TEXT_SUFFIXES | IMAGE_SUFFIXES | {".docx", ".pdf"}
MAX_BYTES = 8_000_000
MAX_REPLACEMENT = 40_000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic_write(target, raw, mode=None):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".desktop-edit-", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class DesktopEditManager:
    def __init__(self, desktop=None, store=None):
        self.desktop = Path(desktop or Path.home() / "Desktop").resolve()
        self.store = Path(store or Path(__file__).resolve().parent / ".desktop-edit-backups")
        self.stages = {}
        self.lock = RLock()

    def target(self, raw):
        if not isinstance(raw, str) or not raw or len(raw) > 600 or "\x00" in raw:
            raise ValueError("请指定一个桌面文件的完整路径")
        candidate = Path(raw)
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("只能使用桌面文件的完整路径")
        root = self.desktop
        try:
            relative = candidate.relative_to(root)
            target = candidate.resolve(strict=True)
            target.relative_to(root)
        except (ValueError, OSError) as exc:
            raise ValueError("只能修改桌面内指定的文件") from exc
        if not relative.parts or any(part.lower() in SKIP_DIRS or part.startswith(".") or is_sensitive_name(part) for part in relative.parts):
            raise ValueError("此文件不可修改")
        current = candidate
        while current != root:
            if current.is_symlink():
                raise ValueError("不修改符号链接")
            current = current.parent
        if not target.is_file() or target.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError("此类型暂不支持修改")
        if target.stat().st_size > MAX_BYTES:
            raise ValueError("文件超过 8 MB")
        return target

    def list_files(self):
        if not self.desktop.is_dir():
            return []
        return [str(item) for item in sorted(self.desktop.iterdir(), key=lambda path: path.name.lower())
                if item.is_file() and not item.is_symlink() and item.suffix.lower() in ALLOWED_SUFFIXES
                and not item.name.startswith(".") and not is_sensitive_name(item.name)][:100]

    def inspect(self, raw):
        target = self.target(raw)
        suffix = target.suffix.lower()
        source = target.read_bytes()
        result = {"path": str(target), "size": len(source)}
        if suffix in TEXT_SUFFIXES:
            try:
                content = source.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("文本文件必须是 UTF-8") from exc
            result.update(kind="text", content=content[:30000], content_truncated=len(content) > 30000)
        elif suffix == ".docx":
            from docx import Document
            try:
                document = Document(io.BytesIO(source))
            except Exception as exc:
                raise ValueError("Word 文件无法打开") from exc
            parts = [paragraph.text for paragraph in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells:
                        parts.extend(paragraph.text for paragraph in cell.paragraphs)
            content = "\n".join(parts)
            result.update(kind="word", content=content[:30000], content_truncated=len(content) > 30000)
        elif suffix == ".pdf":
            from pypdf import PdfReader
            try:
                reader = PdfReader(io.BytesIO(source))
                if reader.is_encrypted:
                    raise ValueError("PDF 已加密")
                result.update(kind="pdf", pages=len(reader.pages))
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError("PDF 文件无法打开") from exc
        else:
            from PIL import Image
            try:
                with Image.open(io.BytesIO(source)) as picture:
                    result.update(kind="image", width=picture.width, height=picture.height)
            except Exception as exc:
                raise ValueError("图片无法打开") from exc
        return result

    def preview(self, body):
        if not isinstance(body, dict):
            raise ValueError("修改请求格式无效")
        target = self.target(body.get("path"))
        before = target.read_bytes()
        kind = "text" if target.suffix.lower() in TEXT_SUFFIXES else "word" if target.suffix.lower() == ".docx" else "pdf" if target.suffix.lower() == ".pdf" else "image"
        if kind == "text":
            after, view = self._text_change(before, body)
        elif kind == "word":
            after, view = self._word_change(before, body)
        elif kind == "pdf":
            after, view = self._pdf_change(before, body)
        else:
            after, view = self._image_change(before, body, target.suffix.lower())
        if before == after:
            raise ValueError("文件没有变化")
        if len(after) > MAX_BYTES:
            raise ValueError("修改结果超过 8 MB")
        identifier = uuid.uuid4().hex
        with self.lock:
            self.stages = {key: value for key, value in self.stages.items() if value["expires"] > time.monotonic()}
            if len(self.stages) >= 8:
                oldest = min(self.stages, key=lambda key: self.stages[key]["expires"])
                self.stages.pop(oldest)
            self.stages[identifier] = {"path": target, "before": digest(before), "after": after,
                                       "expires": time.monotonic() + 1200}
        return {"stage_id": identifier, "path": str(target), "kind": kind, **view}

    @staticmethod
    def _diff(before, after, name):
        return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(),
                         fromfile="修改前/" + name, tofile="修改后/" + name, lineterm="", n=3))[:20000]

    def _text_change(self, raw, body):
        if b"\x00" in raw:
            raise ValueError("文件不是普通文本")
        bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
        try:
            before = raw[len(bom):].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("文本文件必须是 UTF-8") from exc
        old, new = body.get("old_text"), body.get("new_text")
        if not isinstance(old, str) or not isinstance(new, str) or not old or len(old) > MAX_REPLACEMENT or len(new) > MAX_REPLACEMENT:
            raise ValueError("请填写要替换的原文和新内容")
        newline = "\r\n" if "\r\n" in before else "\n"
        normalized = before.replace("\r\n", "\n")
        old = old.replace("\r\n", "\n")
        new = new.replace("\r\n", "\n")
        if normalized.count(old) != 1:
            raise ValueError("原文必须在文件中恰好出现一次")
        after = normalized.replace(old, new, 1)
        return bom + after.replace("\n", newline).encode("utf-8"), {"diff": self._diff(normalized, after, "文本文件")}

    def _word_change(self, raw, body):
        from docx import Document
        old, new = body.get("old_text"), body.get("new_text")
        if not isinstance(old, str) or not isinstance(new, str) or not old or len(old) > MAX_REPLACEMENT or len(new) > MAX_REPLACEMENT:
            raise ValueError("请填写要替换的原文和新内容")
        try:
            document = Document(io.BytesIO(raw))
        except Exception as exc:
            raise ValueError("Word 文件无法打开") from exc
        paragraphs = list(document.paragraphs)
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    paragraphs.extend(cell.paragraphs)
        matches = [(paragraph, run) for paragraph in paragraphs for run in paragraph.runs if old in run.text]
        if sum(paragraph.text.count(old) for paragraph in paragraphs) != 1 or len(matches) != 1:
            raise ValueError("Word 原文需在单个文字片段中恰好出现一次，以保留原格式")
        paragraph, run = matches[0]
        before = paragraph.text
        run.text = run.text.replace(old, new, 1)
        output = io.BytesIO()
        document.save(output)
        return output.getvalue(), {"diff": self._diff(before, paragraph.text, "Word 段落")}

    def _pdf_change(self, raw, body):
        from pypdf import PdfReader, PdfWriter
        if body.get("operation") != "rotate":
            raise ValueError("PDF 当前只支持旋转指定页面")
        try:
            page = int(body.get("page"))
            angle = int(body.get("angle"))
        except (TypeError, ValueError) as exc:
            raise ValueError("请填写页码和旋转角度") from exc
        if angle not in (90, 180, 270):
            raise ValueError("旋转角度只能是 90、180 或 270")
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or not 1 <= page <= len(reader.pages):
                raise ValueError("PDF 已加密或页码无效")
            writer = PdfWriter()
            writer.append_pages_from_reader(reader)
            old_rotation = int(reader.pages[page - 1].get("/Rotate", 0))
            writer.pages[page - 1].rotate(angle)
            output = io.BytesIO()
            writer.write(output)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("PDF 文件无法处理") from exc
        return output.getvalue(), {"diff": f"第 {page} / {len(reader.pages)} 页：旋转 {old_rotation}° → {(old_rotation + angle) % 360}°"}

    @staticmethod
    def _thumbnail(raw):
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as picture:
            picture.thumbnail((320, 240))
            output = io.BytesIO()
            picture.convert("RGB").save(output, format="JPEG", quality=72)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")

    def _image_change(self, raw, body, suffix):
        from PIL import Image
        if body.get("operation") != "resize":
            raise ValueError("图片当前只支持调整尺寸")
        try:
            width, height = int(body.get("width")), int(body.get("height"))
        except (TypeError, ValueError) as exc:
            raise ValueError("请填写目标宽度和高度") from exc
        if not 16 <= width <= 6000 or not 16 <= height <= 6000 or width * height > 24_000_000:
            raise ValueError("图片尺寸超出支持范围")
        try:
            with Image.open(io.BytesIO(raw)) as picture:
                old_size = picture.size
                changed = picture.resize((width, height), Image.Resampling.LANCZOS)
                if suffix in (".jpg", ".jpeg") and changed.mode not in ("RGB", "L"):
                    changed = changed.convert("RGB")
                output = io.BytesIO()
                changed.save(output, format=picture.format, quality=92)
                after = output.getvalue()
        except Exception as exc:
            raise ValueError("图片无法处理") from exc
        return after, {"diff": f"尺寸：{old_size[0]} × {old_size[1]} → {width} × {height}",
                       "before_preview": self._thumbnail(raw), "after_preview": self._thumbnail(after)}

    def commit(self, identifier, edit_id=None):
        with self.lock:
            stage = self.stages.get(identifier)
            if not stage or stage["expires"] <= time.monotonic():
                raise ValueError("预览已过期，请重新检查差异")
            target = self.target(str(stage["path"]))
            before = target.read_bytes()
            if digest(before) != stage["before"]:
                raise ValueError("文件在预览后发生变化，请重新预览")
            edit_id = edit_id or uuid.uuid4().hex
            if not isinstance(edit_id, str) or not re.fullmatch(r"[a-f0-9]{32}", edit_id):
                raise ValueError("修改编号无效")
            self.store.mkdir(parents=True, exist_ok=True)
            backup = self.store / (edit_id + ".bak")
            meta = self.store / (edit_id + ".json")
            if meta.exists() or backup.exists():
                raise ValueError("此修改编号已经使用，请检查修改历史")
            atomic_write(backup, before)
            record = {"id": edit_id, "path": str(target), "before": stage["before"],
                      "after": digest(stage["after"]), "status": "prepared",
                      "at": datetime.now(timezone.utc).isoformat()}
            atomic_write(meta, json.dumps(record, ensure_ascii=False).encode("utf-8"))
            if digest(target.read_bytes()) != stage["before"]:
                raise ValueError("文件在保存前发生变化，请重新预览")
            atomic_write(target, stage["after"], stat.S_IMODE(target.stat().st_mode))
            record["status"] = "applied"
            atomic_write(meta, json.dumps(record, ensure_ascii=False).encode("utf-8"))
            self.stages.pop(identifier, None)
            return {"id": edit_id, "path": str(target), "backup": str(backup), "status": "applied"}

    def undo(self, edit_id):
        if not isinstance(edit_id, str) or not re.fullmatch(r"[a-f0-9]{32}", edit_id):
            raise ValueError("撤销编号无效")
        with self.lock:
            meta = self.store / (edit_id + ".json")
            backup = self.store / (edit_id + ".bak")
            if not meta.is_file() or not backup.is_file():
                raise ValueError("找不到此修改的备份")
            record = json.loads(meta.read_text(encoding="utf-8"))
            if record.get("status") not in ("applied", "prepared"):
                raise ValueError("此修改已经撤销")
            target = self.target(record["path"])
            if digest(target.read_bytes()) != record["after"]:
                raise ValueError("文件在写入后又发生变化，不能自动撤销")
            original = backup.read_bytes()
            if digest(original) != record["before"]:
                raise ValueError("备份校验失败")
            atomic_write(target, original, stat.S_IMODE(target.stat().st_mode))
            record["status"] = "undone"
            atomic_write(meta, json.dumps(record, ensure_ascii=False).encode("utf-8"))
            return {"id": edit_id, "path": str(target), "status": "undone"}

    def history(self):
        if not self.store.is_dir():
            return []
        records = []
        for meta in sorted(self.store.glob("*.json"), key=lambda file: file.stat().st_mtime, reverse=True)[:20]:
            try:
                record = json.loads(meta.read_text(encoding="utf-8"))
                records.append({key: record[key] for key in ("id", "path", "status", "at")})
            except (OSError, ValueError, KeyError):
                continue
        return records
