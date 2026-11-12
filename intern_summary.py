"""Local, opt-in biweekly internship summary scheduling."""

import json
import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


BEIJING = timezone(timedelta(hours=8))
WORKSPACES = {"agent", "inventory", "video", "skills", "listmonk", "personal"}


def now_beijing():
    return datetime.now(BEIJING)


def default_state():
    return {
        "enabled": False,
        "first_run": "",
        "next_run": "",
        "last_run": "",
        "last_error": "",
        "retry_after": "",
        "logs": [],
        "summaries": [],
    }


def atomic_text(path, content):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


class SummaryManager:
    def __init__(self, root, generate):
        self.root = Path(root)
        self.state_path = self.root / ".intern-summary-state.json"
        self.public_path = self.root / "intern_summaries.js"
        self.generate = generate
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.running = False
        self.worker = None

    def _read(self):
        if not self.state_path.exists():
            return default_state()
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("双周总结配置不是对象")
        return {**default_state(), **data}

    def _write(self, state):
        atomic_text(self.state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        public = "window.internBiweeklySummaries = " + json.dumps(state["summaries"], ensure_ascii=False, separators=(",", ":")) + ";\n"
        atomic_text(self.public_path, public)

    def status(self):
        with self.lock:
            state = self._read()
            return {
                "enabled": state["enabled"],
                "first_run": state["first_run"],
                "next_run": state["next_run"],
                "last_run": state["last_run"],
                "last_error": state["last_error"],
                "retry_after": state["retry_after"],
                "running": self.running,
                "generation_mode": "local",
                "log_count": len(state["logs"]),
                "summaries": state["summaries"],
            }

    def configure(self, body):
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("启用状态无效")
        day = str(body.get("date") or "")
        clock = str(body.get("time") or "")
        try:
            first = datetime.strptime(day + " " + clock, "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING)
        except ValueError as exc:
            raise ValueError("请选择有效的首次日期和时间") from exc
        with self.lock:
            state = self._read()
            anchor = first.strftime("%Y-%m-%dT%H:%M")
            if enabled and (not state["enabled"] or state["first_run"] != anchor):
                if first <= now_beijing():
                    raise ValueError("首次运行时间必须晚于现在")
                state["next_run"] = anchor
                state["retry_after"] = ""
                state["last_error"] = ""
            state["enabled"] = enabled
            state["first_run"] = anchor
            if not state["next_run"]:
                state["next_run"] = anchor
            self._write(state)
            self.wake.set()
        return self.status()

    def sync_logs(self, entries):
        if not isinstance(entries, list) or len(entries) > 700:
            raise ValueError("周历记录数量超出限制")
        cleaned = {}
        for item in entries:
            if not isinstance(item, dict):
                continue
            try:
                day = date.fromisoformat(str(item.get("date") or ""))
            except ValueError:
                continue
            workspace = str(item.get("workspace") or "")
            if workspace not in WORKSPACES:
                continue
            title = str(item.get("title") or "").strip()[:160]
            if not title:
                continue
            key = str(item.get("id") or (str(day) + ":" + title))[:160]
            cleaned[key] = {
                "id": key,
                "date": str(day),
                "workspace": workspace,
                "title": title,
                "body": str(item.get("body") or "").strip()[:2000],
            }
        with self.lock:
            state = self._read()
            state["logs"] = list(cleaned.values())
            self._write(state)
        return {"log_count": len(cleaned)}

    def run_due(self):
        with self.lock:
            state = self._read()
            if self.running or not state["enabled"] or not state["next_run"]:
                return False
            due = datetime.fromisoformat(state["next_run"]).replace(tzinfo=BEIJING)
            if due > now_beijing():
                return False
            retry = state.get("retry_after")
            if retry and datetime.fromisoformat(retry).replace(tzinfo=BEIJING) > now_beijing():
                return False
            self.running = True
            scheduled = state["next_run"]
            period_end = due.date()
            period_start = period_end - timedelta(days=13)
            logs = [item for item in state["logs"] if str(period_start) <= item["date"] <= str(period_end)]
        try:
            result = self.generate(str(period_start), str(period_end), logs)
            if not isinstance(result, dict):
                raise ValueError("总结生成器没有返回有效结果")
            title = str(result.get("title") or "").strip()[:80]
            highlights = [str(line).strip()[:300] for line in (result.get("highlights") or []) if str(line).strip()][:5]
            if not title or not highlights:
                raise ValueError("生成的总结缺少标题或工作内容")
            summary = {
                "company": "sifang",
                "from": str(period_start),
                "to": str(period_end),
                "title": title,
                "highlights": highlights,
                "next": str(result.get("next") or "").strip()[:400],
            }
            with self.lock:
                state = self._read()
                if not state["enabled"] or state["next_run"] != scheduled:
                    return False
                state["summaries"] = [item for item in state["summaries"] if not (
                    item.get("company") == "sifang" and item.get("from") == summary["from"] and item.get("to") == summary["to"]
                )] + [summary]
                state["summaries"].sort(key=lambda item: item["to"], reverse=True)
                state["next_run"] = (due + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M")
                state["last_run"] = now_beijing().strftime("%Y-%m-%dT%H:%M")
                state["last_error"] = ""
                state["retry_after"] = ""
                self._write(state)
            return True
        except Exception as exc:
            with self.lock:
                state = self._read()
                if state["enabled"] and state["next_run"] == scheduled:
                    state["last_error"] = str(exc)[:300]
                    state["retry_after"] = (now_beijing() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
                    self._write(state)
            return False
        finally:
            with self.lock:
                self.running = False

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._loop, name="intern-summary-scheduler", daemon=True)
        self.worker.start()

    def _loop(self):
        while True:
            try:
                self.run_due()
            except Exception as exc:
                print("[intern-summary]", exc)
            self.wake.wait(30)
            self.wake.clear()
