"""Persistent, single-user scheduled tasks with cross-process claims."""

import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


BEIJING = timezone(timedelta(hours=8))
REPEAT_DAYS = {"daily": 1, "weekly": 7}


def normalize_grants(value, kind="analysis"):
    """A scheduled task never inherits the chat's ambient permissions."""
    empty = {"logs": False, "resume": False, "files": [], "consent": False}
    if kind == "reminder":
        return empty
    if value is None:
        return empty
    if not isinstance(value, dict) or set(value) - set(empty):
        raise ValueError("任务资料授权格式无效")
    if any(key in value and not isinstance(value[key], bool) for key in ("logs", "resume", "consent")):
        raise ValueError("请明确选择任务资料授权")
    files = value.get("files", [])
    if not isinstance(files, list) or len(files) > 3 or any(
            not isinstance(item, str) or not item or len(item) > 600 or "\x00" in item
            or not Path(item).is_absolute() or ".." in Path(item).parts for item in files):
        raise ValueError("最多选择三个文件，需使用完整路径")
    grants = {**empty, **value, "files": list(dict.fromkeys(files))}
    if (grants["logs"] or grants["resume"] or grants["files"]) and not grants["consent"]:
        raise ValueError("请确认允许该任务每次运行时将所选资料发送给模型")
    return grants


def local_time(timestamp):
    return datetime.fromtimestamp(timestamp, BEIJING).strftime("%Y-%m-%dT%H:%M") if timestamp is not None else ""


class TaskManager:
    def __init__(self, path, runner, clock=None, lease_seconds=240, poll_seconds=10):
        self.path = Path(path)
        self.runner = runner
        self.clock = clock or (lambda: datetime.now(BEIJING))
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.wake = threading.Event()
        self.worker = None
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL,
                    kind TEXT NOT NULL, repeat TEXT NOT NULL, next_run REAL,
                    state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    lease_token TEXT, lease_until REAL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, scheduled_for REAL NOT NULL,
                    started_at REAL NOT NULL, finished_at REAL, status TEXT NOT NULL,
                    output TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                    progress TEXT NOT NULL DEFAULT '', attempt INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(task_id, scheduled_for)
                );
                CREATE INDEX IF NOT EXISTS runs_task_id ON runs(task_id, started_at DESC);
            """)
            # Additive migration keeps existing reminders and results intact.
            db.execute("BEGIN IMMEDIATE")
            for table, column, default in (("tasks", "grants", "{}"), ("runs", "sources", "[]"), ("runs", "drafts", "[]")):
                columns = {row[1] for row in db.execute("PRAGMA table_info(%s)" % table)}
                if column not in columns:
                    db.execute("ALTER TABLE %s ADD COLUMN %s TEXT NOT NULL DEFAULT '%s'" % (table, column, default))

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _now(self):
        return self.clock().timestamp()

    @staticmethod
    def _run_view(row):
        result = {key: row[key] for key in ("id", "status", "output", "error", "progress", "attempt")}
        result.update(started_at=local_time(row["started_at"]), finished_at=local_time(row["finished_at"]),
                      scheduled_for=local_time(row["scheduled_for"]),
                      sources=json.loads(row["sources"]), drafts=json.loads(row["drafts"]))
        return result

    def _draft_history(self, db, identifier, latest):
        rows = db.execute(
            "SELECT * FROM runs WHERE task_id=? AND id<>? AND drafts<>'[]' "
            "ORDER BY started_at DESC LIMIT 10", (identifier, latest["id"] if latest else "")
        ).fetchall()
        return [self._run_view(row) for row in rows]

    def _task(self, row, latest=None):
        task = {key: row[key] for key in ("id", "title", "prompt", "kind", "repeat", "state")}
        task["grants"] = normalize_grants(json.loads(row["grants"]), row["kind"])
        task.update(next_run=local_time(row["next_run"]), created_at=local_time(row["created_at"]),
                    running=bool(row["lease_token"] and row["lease_until"] and row["lease_until"] > self._now()))
        task["last_run"] = self._run_view(latest) if latest else None
        return task

    def _with_runs(self, db, row):
        latest = db.execute("SELECT * FROM runs WHERE task_id=? ORDER BY started_at DESC LIMIT 1", (row["id"],)).fetchone()
        return {**self._task(row, latest), "draft_history": self._draft_history(db, row["id"], latest)}

    def list(self):
        with self._connection() as db:
            rows = db.execute("SELECT * FROM tasks ORDER BY CASE state WHEN 'needs_decision' THEN 0 WHEN 'active' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END, updated_at DESC LIMIT 100").fetchall()
            return [self._with_runs(db, row) for row in rows]

    def get_task(self, identifier):
        with self._connection() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise ValueError("任务不存在")
            return self._with_runs(db, row)

    def _details(self, body):
        if not isinstance(body, dict):
            raise ValueError("任务格式无效")
        title = body.get("title")
        prompt = body.get("prompt")
        kind = body.get("kind")
        repeat = body.get("repeat")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 80:
            raise ValueError("请填写 80 字以内的任务名称")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.strip()) > 2000:
            raise ValueError("请填写 2000 字以内的任务内容")
        if kind not in ("reminder", "analysis") or repeat not in ("once", "daily", "weekly"):
            raise ValueError("请选择有效的任务类型和重复频率")
        raw = body.get("run_at")
        try:
            scheduled = datetime.strptime(raw, "%Y-%m-%dT%H:%M").replace(tzinfo=BEIJING).timestamp()
        except (TypeError, ValueError) as exc:
            raise ValueError("请选择有效的运行时间") from exc
        now = self._now()
        if scheduled <= now or scheduled > now + 366 * 86400:
            raise ValueError("运行时间需晚于现在，且在一年以内")
        return title.strip(), prompt.strip(), kind, repeat, scheduled

    def create(self, body):
        title, prompt, kind, repeat, scheduled = self._details(body)
        grants = normalize_grants(body.get("grants"), kind)
        now = self._now()
        identifier = secrets.token_urlsafe(18)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM tasks WHERE state IN ('active','paused','needs_decision')").fetchone()[0]
            if count >= 50:
                raise ValueError("任务已达 50 条上限，请先取消旧任务")
            db.execute("INSERT INTO tasks (id,title,prompt,kind,repeat,next_run,state,created_at,updated_at,grants) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (identifier, title, prompt, kind, repeat, scheduled, "active", now, now, json.dumps(grants, ensure_ascii=False)))
        self.wake.set()
        return next(item for item in self.list() if item["id"] == identifier)

    def update(self, body):
        title, prompt, kind, repeat, scheduled = self._details(body)
        grants = normalize_grants(body.get("grants"), kind)
        identifier = body.get("id")
        now = self._now()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,lease_token FROM tasks WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise ValueError("任务不存在")
            if row["state"] not in ("active", "paused") or row["lease_token"]:
                raise ValueError("当前任务需先处理或等待运行结束")
            db.execute("UPDATE tasks SET title=?,prompt=?,kind=?,repeat=?,next_run=?,updated_at=?,grants=? WHERE id=?",
                       (title, prompt, kind, repeat, scheduled, now, json.dumps(grants, ensure_ascii=False), identifier))
        self.wake.set()
        return next(item for item in self.list() if item["id"] == identifier)

    def _advance(self, scheduled, repeat, now):
        if repeat == "once":
            return None, "done"
        following = scheduled
        interval = REPEAT_DAYS[repeat] * 86400
        while following <= now:
            following += interval
        return following, "active"

    def action(self, identifier, action):
        if action not in ("pause", "resume", "run_now", "retry", "complete", "snooze", "cancel"):
            raise ValueError("任务操作无效")
        now = self._now()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise ValueError("任务不存在")
            state, next_run = row["state"], row["next_run"]
            if action == "pause" and state in ("active", "needs_decision"):
                state = "paused"
            elif action == "resume" and state == "paused":
                current_run = db.execute("SELECT status FROM runs WHERE task_id=? AND scheduled_for=?", (identifier, next_run)).fetchone()
                state = "needs_decision" if current_run and current_run["status"] == "needs_decision" else "active"
            elif action == "run_now" and state in ("active", "paused") and not row["lease_token"]:
                next_run, state = now, "active"
            elif action == "retry" and state == "needs_decision":
                current_run = db.execute("SELECT drafts FROM runs WHERE task_id=? AND scheduled_for=?", (identifier, next_run)).fetchone()
                if current_run and any(item.get("state") == "applied" for item in json.loads(current_run["drafts"])):
                    raise ValueError("本次已有已应用的草稿，请先标记本次已处理，再运行下一次任务；原草稿可在历史中撤销")
                state = "active"
            elif action == "complete" and state == "needs_decision":
                latest = db.execute("SELECT id FROM runs WHERE task_id=? ORDER BY started_at DESC LIMIT 1", (identifier,)).fetchone()
                if latest:
                    db.execute("UPDATE runs SET status='resolved' WHERE id=?", (latest["id"],))
                next_run, state = self._advance(next_run, row["repeat"], now)
            elif action == "snooze" and state == "needs_decision" and row["kind"] == "reminder":
                latest = db.execute("SELECT id FROM runs WHERE task_id=? ORDER BY started_at DESC LIMIT 1", (identifier,)).fetchone()
                if latest:
                    db.execute("UPDATE runs SET status='deferred' WHERE id=?", (latest["id"],))
                next_run, state = now + 3600, "active"
            elif action == "cancel" and state != "cancelled":
                state = "cancelled"
            else:
                raise ValueError("当前状态不支持这个操作")
            db.execute("UPDATE tasks SET state=?,next_run=?,updated_at=? WHERE id=?", (state, next_run, now, identifier))
        self.wake.set()
        return next(item for item in self.list() if item["id"] == identifier)

    def _claim(self):
        now = self._now()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE state='active' AND next_run<=? AND (lease_until IS NULL OR lease_until<=?) ORDER BY next_run LIMIT 1", (now, now)).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(18)
            run = db.execute("SELECT * FROM runs WHERE task_id=? AND scheduled_for=?", (row["id"], row["next_run"])).fetchone()
            if run:
                if any(item.get("state") == "applied" for item in json.loads(run["drafts"])):
                    db.execute("UPDATE tasks SET state='needs_decision',lease_token=NULL,lease_until=NULL WHERE id=?", (row["id"],))
                    return None
                run_id = run["id"]
                db.execute("UPDATE runs SET status='running',started_at=?,finished_at=NULL,error='',output='',sources='[]',drafts='[]',progress='重新运行',attempt=attempt+1 WHERE id=?", (now, run_id))
            else:
                run_id = secrets.token_urlsafe(18)
                db.execute("INSERT INTO runs (id,task_id,scheduled_for,started_at,status) VALUES (?,?,?,?,?)",
                           (run_id, row["id"], row["next_run"], now, "running"))
            db.execute("UPDATE tasks SET lease_token=?,lease_until=?,updated_at=? WHERE id=?",
                       (token, now + self.lease_seconds, now, row["id"]))
            return {"id": row["id"], "title": row["title"], "prompt": row["prompt"], "kind": row["kind"],
                    "repeat": row["repeat"], "scheduled_for": row["next_run"], "run_id": run_id, "token": token,
                    "grants": normalize_grants(json.loads(row["grants"]), row["kind"])}

    def _progress(self, job, message):
        now = self._now()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT state,lease_token FROM tasks WHERE id=?", (job["id"],)).fetchone()
            if not current or current["lease_token"] != job["token"] or current["state"] != "active":
                raise RuntimeError("任务已暂停、取消或由其他执行器接管，停止继续读取资料")
            db.execute("UPDATE runs SET progress=? WHERE id=?", (str(message)[:300], job["run_id"]))
            db.execute("UPDATE tasks SET lease_until=? WHERE id=? AND lease_token=?",
                       (now + self.lease_seconds, job["id"], job["token"]))

    def run_due(self):
        job = self._claim()
        if not job:
            return False
        try:
            result = self.runner(job, lambda message: self._progress(job, message))
            if not isinstance(result, dict) or result.get("status") not in ("completed", "needs_decision"):
                raise ValueError("任务执行器没有返回有效结果")
            status = result["status"]
            output = str(result.get("output") or "")[:20000]
            sources = result.get("sources", [])
            drafts = result.get("drafts", [])
            if not isinstance(sources, list) or not isinstance(drafts, list) or len(sources) > 50 or len(drafts) > 8:
                raise ValueError("任务来源或草稿数量无效")
            sources_json, drafts_json = json.dumps(sources, ensure_ascii=False), json.dumps(drafts, ensure_ascii=False)
            if len(sources_json) + len(drafts_json) > 240000:
                raise ValueError("任务草稿过大")
            if drafts:
                status = "needs_decision"
            error = ""
        except Exception as exc:
            status, output, error = "needs_decision", "", str(exc)[:500]
            sources_json, drafts_json = "[]", "[]"
        now = self._now()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (job["id"],)).fetchone()
            if not row or row["lease_token"] != job["token"]:
                return False
            db.execute("UPDATE runs SET status=?,output=?,error=?,progress='',finished_at=?,sources=?,drafts=? WHERE id=?",
                       (status, output, error, now, sources_json, drafts_json, job["run_id"]))
            if row["state"] == "cancelled":
                next_run, state = None, "cancelled"
            elif status == "needs_decision":
                next_run, state = row["next_run"], "paused" if row["state"] == "paused" else "needs_decision"
            else:
                next_run, state = self._advance(job["scheduled_for"], row["repeat"], now)
                if row["state"] == "paused" and state == "active":
                    state = "paused"
            db.execute("UPDATE tasks SET state=?,next_run=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?",
                       (state, next_run, now, job["id"]))
        return True

    def get_run(self, task_id, run_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM runs WHERE task_id=? AND id=?", (task_id, run_id)).fetchone()
            if not row:
                raise ValueError("任务结果不存在")
            result = dict(row)
            result.update(sources=json.loads(row["sources"]), drafts=json.loads(row["drafts"]))
            task = db.execute("SELECT grants,kind,state FROM tasks WHERE id=?", (task_id,)).fetchone()
            result["grants"] = normalize_grants(json.loads(task["grants"]), task["kind"])
            result["task_state"] = task["state"]
            return result

    def mark_draft(self, task_id, run_id, draft_id, status, metadata=None):
        if status not in ("pending", "applied", "undone", "dismissed"):
            raise ValueError("草稿状态无效")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT drafts,status FROM runs WHERE task_id=? AND id=?", (task_id, run_id)).fetchone()
            if not row or row["status"] == "running":
                raise ValueError("任务结果不可修改")
            drafts = json.loads(row["drafts"])
            draft = next((item for item in drafts if item.get("id") == draft_id), None)
            if not draft:
                raise ValueError("草稿不存在")
            draft["state"] = status
            if metadata is not None:
                if not isinstance(metadata, dict) or len(json.dumps(metadata)) > 50000:
                    raise ValueError("草稿应用记录无效")
                draft["application"] = metadata
                if "change_id" in metadata:
                    draft["change_id"] = metadata["change_id"]
            db.execute("UPDATE runs SET drafts=? WHERE id=?", (json.dumps(drafts, ensure_ascii=False), run_id))
            return draft

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._loop, name="agent-task-scheduler", daemon=True)
        self.worker.start()

    def _loop(self):
        while True:
            try:
                while self.run_due():
                    pass
            except Exception as exc:
                print("[agent-tasks]", exc)
            self.wake.wait(self.poll_seconds)
            self.wake.clear()
