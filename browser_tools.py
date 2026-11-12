"""Dedicated local browser bridge for the personal agent."""
import atexit
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_worker = None
_lock = threading.RLock()
_next_id = 0

BROWSER_READ_TOOLS = [
    {"type": "function", "name": "browser_open", "description": "在 AI 专用浏览器窗口打开 http/https 网址，并读取当前页面。不会接管用户原有的浏览器标签页。", "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "完整网址"}}, "required": ["url"]}},
    {"type": "function", "name": "browser_read", "description": "读取 AI 专用浏览器当前页面的标题、正文和可操作元素编号。用户可能手动改变了页面，操作前先重新读取。", "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "browser_back", "description": "让 AI 专用浏览器返回上一页，并读取页面。", "parameters": {"type": "object", "properties": {}}},
]
BROWSER_ACTION_TOOLS = [
    {"type": "function", "name": "browser_click", "description": "点击 browser_read 返回的页面元素编号。仅在用户开启本次提问的页面交互后可用。", "parameters": {"type": "object", "properties": {"id": {"type": "string", "description": "页面元素编号"}}, "required": ["id"]}},
    {"type": "function", "name": "browser_fill", "description": "填写 browser_read 返回的普通文本框编号；密码和文件输入不可填写。仅在用户开启本次提问的页面交互后可用。", "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}}, "required": ["id", "text"]}},
]
BROWSER_LABELS = {"browser_open": "打开网页", "browser_read": "读取网页", "browser_back": "返回网页", "browser_click": "点击页面", "browser_fill": "填写页面"}


def _stop_worker():
    global _worker
    if _worker and _worker.poll() is None:
        _worker.terminate()
    _worker = None


atexit.register(_stop_worker)


def _ensure_worker():
    global _worker
    if _worker and _worker.poll() is None:
        return _worker
    node = os.environ.get("PERSONAL_NODE_BIN") or shutil.which("node")
    if not node:
        raise RuntimeError("没有找到 Node.js")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _worker = subprocess.Popen(
        [node, str(ROOT / "browser_bridge.js")], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", bufsize=1, creationflags=flags,
    )
    return _worker


def browser_command(name, args=None):
    global _next_id
    with _lock:
        if name == "status" and (_worker is None or _worker.poll() is not None):
            return {"connected": False, "title": "", "url": ""}
        if name == "close" and (_worker is None or _worker.poll() is not None):
            return {"connected": False, "title": "", "url": ""}
        worker = _ensure_worker()
        _next_id += 1
        worker.stdin.write(json.dumps({"id": _next_id, "name": name, "args": args or {}}, ensure_ascii=False) + "\n")
        worker.stdin.flush()
        response = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: response.put(worker.stdout.readline()), daemon=True).start()
        try:
            line = response.get(timeout=40)
        except queue.Empty as exc:
            _stop_worker()
            raise RuntimeError("浏览器响应超时") from exc
        if not line:
            _stop_worker()
            raise RuntimeError("浏览器进程已退出，请检查 Edge 和 playwright-core")
        packet = json.loads(line)
        if packet.get("id") != _next_id:
            raise RuntimeError("浏览器响应编号不匹配")
        if not packet.get("ok"):
            raise RuntimeError(packet.get("error") or "浏览器操作失败")
        return packet.get("result") or {}


def run_browser_tool(name, arguments, access="none"):
    if access not in ("read", "control"):
        return "本次提问未允许读取浏览器页面。"
    if name in {"browser_click", "browser_fill"} and access != "control":
        return "本次提问未允许点击与输入。"
    try:
        args = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
        result = browser_command(name.removeprefix("browser_"), args)
        return json.dumps(result, ensure_ascii=False)
    except (ValueError, RuntimeError, OSError) as exc:
        return "浏览器操作失败：" + str(exc)
