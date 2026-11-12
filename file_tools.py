# -*- coding: utf-8 -*-
"""Read-only access for the personal agent. No writes, no shell, no secrets."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

ROOTS = [
    Path(r"D:\工作文件文件夹"),
    Path(r"D:\工作软件文件夹"),
    Path.home() / "Desktop",
]
SKIP_DIRS = {".git", ".codex", ".agents", ".aws", ".local-data", ".desktop-edit-backups", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "tmp", "temp", "logs", "cache", "preview"}
SECRET_NAMES = {".env", "credentials.json", "id_rsa", "id_ed25519", ".agent-checkpoints.json", ".agent-checkpoints.json.tmp"}
SECRET_SUFFIX = {".pem", ".key", ".p12", ".pfx"}
TEXT_SUFFIX = {
    ".md", ".txt", ".py", ".js", ".ts", ".json", ".html", ".css", ".yml", ".yaml",
    ".toml", ".xml", ".csv", ".log", ".vue", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".sql", ".env.example", ".gitignore", ".ps1", ".bat", ".sh",
}

FILE_TOOLS = [
    {
        "type": "function",
        "name": "list_dir",
        "description": "列出允许目录的一层内容。用于工作文件夹、软件文件夹和桌面。",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "绝对路径"}},
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "search_files",
        "description": "在允许目录里按文件名或文本搜索。先搜索再决定读哪个文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "从哪个目录开始"},
                "query": {"type": "string", "description": "文件名或正文关键词"},
            },
            "required": ["path", "query"],
        },
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "读取允许目录里的文本文件。不能读 .env、密钥和密码文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
]
LABELS = {"list_dir": "查看目录", "search_files": "搜索文件", "read_file": "读取文件"}


def tool_title(name):
    return LABELS.get(name or "", "读取文件")


SENSITIVE_NAME = re.compile(r"(1password|emergency\s*kit|密码|密钥|id_rsa|credential|身份证|\d{17}[\dXx])", re.I)
RECENT_SUFFIX = TEXT_SUFFIX | {".docx", ".pdf", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp", ".md"}


def is_sensitive_name(name):
    low = str(name or "").lower()
    if low in SECRET_NAMES or low.startswith((".env", ".agent-tasks.sqlite3", ".personal-state.sqlite3", ".task-drafts.sqlite3")) or Path(low).suffix.lower() in SECRET_SUFFIX:
        return True
    return bool(SENSITIVE_NAME.search(str(name or "")))


def allowed(raw):
    text = str(raw or "").strip().strip('"')
    if not text:
        raise ValueError("没有路径")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path(r"D:\工作文件文件夹") / path
    resolved = path.resolve()
    roots = [root.resolve() for root in ROOTS if root.exists()]
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ValueError("只能看工作文件夹、软件文件夹和桌面")
    if any(part.lower() in SKIP_DIRS for part in resolved.parts):
        raise ValueError("依赖目录不读")
    if any(is_sensitive_name(part) for part in resolved.parts):
        raise ValueError("敏感文件不读取")
    return resolved


def redact_text(text):
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)
    text = re.sub(r"(?i)(password|passwd|api[_-]?key|secret|token|bearer|密码)\s*[:=]\s*\S+", r"\1=***", text)
    return text


def list_dir(path):
    folder = allowed(path)
    if not folder.exists():
        return "没有这个路径"
    if not folder.is_dir():
        return "这是文件，用 read_file"
    rows = []
    for child in sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.name.lower() in SKIP_DIRS or is_sensitive_name(child.name):
            continue
        kind = "目录" if child.is_dir() else "文件"
        rows.append(kind + "  " + child.name)
        if len(rows) >= 80:
            rows.append("…还有更多，换更具体的目录")
            break
    return folder.as_posix() + "\n" + ("\n".join(rows) if rows else "空目录")


def read_file(path, max_chars=8000):
    target = allowed(path)
    if not target.is_file():
        return "不是文件"
    if target.suffix.lower() == ".docx":
        return read_docx(target, max_chars)
    if target.stat().st_size > 2_000_000:
        return "文件太大，只给路径：" + str(target)
    raw = target.read_bytes()
    if b"\x00" in raw[:800]:
        return "二进制文件，未读取：" + target.name
    text = redact_text(raw.decode("utf-8", "replace"))
    limit = max(500, min(int(max_chars or 8000), 12000))
    if len(text) > limit:
        return text[:limit] + "\n…已截断"
    return text


def read_docx(path, max_chars):
    import zipfile
    import xml.etree.ElementTree as ET
    paras = []
    with zipfile.ZipFile(path) as book:
        root = ET.fromstring(book.read("word/document.xml"))
    for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        line = "".join(node.text or "" for node in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")).strip()
        if line:
            paras.append(line)
    text = redact_text("\n".join(paras))
    limit = max(500, min(int(max_chars or 8000), 12000))
    if len(text) > limit:
        return text[:limit] + "\n…已截断"
    return text or "文档是空的"


def search_files(path, query):
    folder = allowed(path)
    needle = str(query or "").strip()
    if len(needle) < 2:
        return "关键词至少 2 个字"
    if folder.is_file():
        folder = folder.parent
    hits = []
    seen = 0
    for current, dirs, files in os_walk(folder):
        dirs[:] = [name for name in dirs if name.lower() not in SKIP_DIRS and not is_sensitive_name(name)]
        for name in files:
            if is_sensitive_name(name):
                continue
            seen += 1
            if seen > 2500:
                hits.append("…搜索提前停了")
                return "\n".join(hits)
            file_path = current / name
            if needle.lower() in name.lower():
                hits.append("文件名  " + str(file_path))
            elif file_path.suffix.lower() in TEXT_SUFFIX and file_path.stat().st_size < 800_000:
                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if needle.lower() in text.lower():
                    hits.append("正文  " + str(file_path))
            if len(hits) >= 15:
                return "\n".join(hits)
    return "\n".join(hits) if hits else "没有匹配"


def os_walk(folder):
    import os
    for dirpath, dirnames, filenames in os.walk(folder):
        yield Path(dirpath), dirnames, filenames


def activity_snapshot():
    lines = ["本机快照。问桌面有什么、最近做了什么，直接用这里，不要说看不到。需要正文再读文件。"]
    desk = Path.home() / "Desktop"
    lines.append("桌面：")
    if not desk.exists():
        lines.append("桌面路径不存在")
    else:
        shown = 0
        hidden = 0
        for child in sorted(desk.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if is_sensitive_name(child.name):
                hidden += 1
                continue
            kind = "目录" if child.is_dir() else "文件"
            stamp = datetime.fromtimestamp(child.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(stamp + "  " + kind + "  " + child.name)
            shown += 1
            if shown >= 18:
                break
        if hidden:
            lines.append("另有 " + str(hidden) + " 个敏感文件已隐藏，不列出也不读取。")
        if not shown:
            lines.append("桌面没有可展示的文件")
    lines.append("近 14 天改过的文件：")
    cutoff = time.time() - 14 * 86400
    recent = []
    for root in ROOTS:
        if not root.exists():
            continue
        seen = 0
        for current, dirs, files in os_walk(root):
            dirs[:] = [name for name in dirs if name.lower() not in SKIP_DIRS and not name.lower().startswith(".env")]
            for name in files:
                seen += 1
                if seen > 4000:
                    break
                if is_sensitive_name(name):
                    continue
                path = current / name
                suffix = path.suffix.lower()
                if suffix not in RECENT_SUFFIX or suffix == ".log" or name.startswith("_"):
                    continue
                if any(part.lower() in SKIP_DIRS for part in path.parts):
                    continue
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if modified < cutoff:
                    continue
                recent.append((modified, path))
            if seen > 4000:
                break
    recent.sort(reverse=True)
    if not recent:
        lines.append("近 14 天没有可展示的新文件")
    else:
        for modified, path in recent[:20]:
            stamp = datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M")
            lines.append(stamp + "  " + str(path))
    return "\n".join(lines)


def run_tool(name, arguments):
    try:
        args = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    try:
        if name == "list_dir":
            return list_dir(args.get("path"))
        if name == "search_files":
            return search_files(args.get("path"), args.get("query"))
        if name == "read_file":
            return read_file(args.get("path"), args.get("max_chars") or 8000)
        return "没有这个工具"
    except Exception as exc:
        return "读取失败：" + str(exc)
