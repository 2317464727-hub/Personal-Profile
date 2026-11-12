"""Explicitly authorized edits and fixed test commands for this repository."""
import difflib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from threading import Lock
from pathlib import Path

from file_tools import FILE_TOOLS, is_sensitive_name, redact_text, run_tool


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EDIT_SUFFIXES = {".css", ".html", ".js", ".json", ".jsx", ".md", ".py", ".toml", ".ts", ".tsx", ".txt", ".vue", ".yaml", ".yml"}
BLOCKED_PARTS = {".agents", ".aws", ".codex", ".git", ".local-data", "__pycache__", "build", "dist", "node_modules", "temp", "tmp", "venv", ".venv"}
MAX_FILE_BYTES = 1_000_000
MAX_EDIT_CHARS = 40_000
EDIT_LOCK = Lock()

PROJECT_TOOLS = [
    {
        "type": "function",
        "name": "project_replace",
        "description": "在当前仓库精确替换一段文本；old_text 为空时仅能在已有目录新建文本文件。修改会展示给用户。不要改仓库外文件、密钥或依赖目录。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "当前仓库内的相对路径或绝对路径"},
                "old_text": {"type": "string", "description": "必须在现有文件中恰好出现一次的原文；新建文件时传空字符串"},
                "new_text": {"type": "string", "description": "替换后的文本；新建文件时传完整内容"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "type": "function",
        "name": "project_run_check",
        "description": "运行当前仓库预设的测试，不接受自定义命令。可选 check: repo_node, personal_python, personal_browser。",
        "parameters": {
            "type": "object",
            "properties": {"check": {"type": "string", "enum": ["repo_node", "personal_python", "personal_browser"]}},
            "required": ["check"],
        },
    },
]

PROJECT_LABELS = {"project_replace": "修改项目文件", "project_run_check": "运行项目测试"}
PROJECT_READ_DESCRIPTIONS = {"list_dir": "列出当前仓库内的一层目录。", "search_files": "只在当前仓库内搜索文件名或正文。", "read_file": "只读取当前仓库内的普通文本文件。"}
PROJECT_READ_TOOLS = [dict(tool, description=PROJECT_READ_DESCRIPTIONS[tool["name"]]) for tool in FILE_TOOLS]


def project_read_path(raw):
    if raw in (None, ""):
        return PROJECT_ROOT.resolve()
    if not isinstance(raw, str) or len(raw) > 400 or "\x00" in raw:
        raise ValueError("项目路径无效")
    candidate = Path(raw)
    if ".." in candidate.parts:
        raise ValueError("不允许路径回退")
    root = PROJECT_ROOT.resolve()
    lexical = candidate if candidate.is_absolute() else root / candidate
    try:
        lexical.relative_to(root)
        relative = lexical.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("只能读取当前仓库") from exc
    if any(part.lower() in BLOCKED_PARTS or part.startswith(".") or is_sensitive_name(part) for part in relative.parts):
        raise ValueError("此路径不可读取")
    if is_sensitive_name(lexical.name):
        raise ValueError("敏感文件不读取")
    current = lexical
    while current != root:
        if current.is_symlink():
            raise ValueError("不读取符号链接")
        current = current.parent
    return lexical.resolve(strict=False)


def run_project_read_tool(name, arguments):
    try:
        args = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("工具参数无效")
        args["path"] = str(project_read_path(args.get("path")))
        return run_tool(name, args)
    except (ValueError, OSError) as exc:
        return "读取失败：" + str(exc)


def project_path(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 400 or "\x00" in raw:
        raise ValueError("项目路径无效")
    candidate = Path(raw)
    if ".." in candidate.parts:
        raise ValueError("不允许路径回退")
    root = PROJECT_ROOT.resolve()
    lexical = candidate if candidate.is_absolute() else root / candidate
    try:
        lexical.relative_to(root)
    except ValueError as exc:
        raise ValueError("只能修改当前仓库") from exc
    target = lexical.resolve(strict=False)
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("只能修改当前仓库") from exc
    if not relative.parts or any(part.lower() in BLOCKED_PARTS or part.startswith(".") or is_sensitive_name(part) for part in relative.parts):
        raise ValueError("此路径不可修改")
    if is_sensitive_name(target.name) or target.suffix.lower() not in EDIT_SUFFIXES:
        raise ValueError("只允许普通文本源文件")
    current = lexical
    while current != root:
        if current.is_symlink():
            raise ValueError("不修改符号链接")
        current = current.parent
    return target, relative.as_posix()


def replace_text(path, old_text, new_text):
    with EDIT_LOCK:
        return _replace_text(path, old_text, new_text)


def _replace_text(path, old_text, new_text):
    target, relative = project_path(path)
    if not isinstance(old_text, str) or not isinstance(new_text, str):
        raise ValueError("修改内容必须是文本")
    if len(old_text) > MAX_EDIT_CHARS or len(new_text) > MAX_EDIT_CHARS:
        raise ValueError("单次修改过大")
    if not target.parent.is_dir():
        raise ValueError("目标目录不存在")
    exists = target.exists()
    if exists and not target.is_file():
        raise ValueError("目标不是普通文件")
    if exists and not old_text:
        raise ValueError("文件已存在；请给出要替换的原文")
    if not exists and (old_text or not new_text):
        raise ValueError("新建文件需要空原文和非空内容")
    raw = target.read_bytes() if exists else b""
    if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
        raise ValueError("只允许小型 UTF-8 文本文件")
    before = raw.decode("utf-8")
    if "\r\n" in before and "\n" in before.replace("\r\n", ""):
        raise ValueError("文件混用换行符，暂不自动修改")
    newline = "\r\n" if "\r\n" in before else "\n"
    normalized = before.replace("\r\n", "\n")
    old = old_text.replace("\r\n", "\n")
    new = new_text.replace("\r\n", "\n")
    if exists and normalized.count(old) != 1:
        raise ValueError("原文没有唯一匹配；文件可能已变化")
    after = normalized.replace(old, new, 1) if exists else new
    if after == normalized:
        return {"output": "文件没有变化：" + relative}
    encoded = after.replace("\n", newline).encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("修改后的文件过大")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".project-edit-", dir=target.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(encoded)
        if exists:
            temp_path.chmod(stat.S_IMODE(target.stat().st_mode))
        if (exists and target.read_bytes() != raw) or (not exists and target.exists()):
            raise ValueError("文件在修改过程中发生变化")
        os.replace(temp_path, target)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    diff = "\n".join(difflib.unified_diff(
        normalized.splitlines(), after.splitlines(), fromfile="a/" + relative,
        tofile="b/" + relative, lineterm="", n=2,
    ))[:16_000]
    return {
        "output": ("已修改 " if exists else "已新建 ") + relative,
        "change": {"path": relative, "diff": diff, "created": not exists},
    }


def check_commands(name):
    if not isinstance(name, str):
        raise ValueError("没有这个预设测试")
    node = shutil.which("node")
    checks = {
        "repo_node": [[node, "--test"]] if node else None,
        "personal_python": [[sys.executable, "-m", "unittest", "discover", "-s", "personal", "-p", "test_*.py"]],
        "personal_browser": [[node, "personal/test_ai_browser_access.js"], [node, "personal/test_ai_memory.js"]] if node else None,
    }
    if name not in checks:
        raise ValueError("没有这个预设测试")
    if checks[name] is None:
        raise ValueError("本机未找到 Node.js")
    return checks[name]


def run_check(name):
    commands = check_commands(name)
    allowed_env = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "LANG"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed_env}
    env["PYTHONIOENCODING"] = "utf-8"
    outputs = []
    success = True
    for command in commands:
        try:
            result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, shell=False,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            outputs.append("测试超时（90 秒）")
            success = False
            break
        outputs.append("退出码 %s\n%s" % (result.returncode, redact_text((result.stdout or "") + (result.stderr or ""))[:6000]))
        if result.returncode:
            success = False
            break
    output = "\n\n".join(outputs)[:9000]
    return {
        "output": ("测试通过：" if success else "测试失败：") + name + "\n" + output,
        "failed": not success,
        "check": {"name": name, "passed": success, "output": output},
    }


def run_project_tool(name, arguments):
    try:
        args = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("工具参数无效")
        if name == "project_replace":
            return replace_text(args.get("path"), args.get("old_text"), args.get("new_text"))
        if name == "project_run_check":
            return run_check(args.get("check"))
        raise ValueError("没有这个项目工具")
    except (ValueError, OSError, UnicodeError) as exc:
        return {"output": "项目操作失败：" + str(exc), "failed": True}
