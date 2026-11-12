"""Durable review receipts for scheduled drafts; models never call this writer."""

import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from desktop_edits import digest
from resume_advisor import RESUME_FIELDS


RESUME_KEY = "whq-personal-resume-v1"


class TaskDraftManager:
    def __init__(self, path, tasks, state, desktop):
        self.path = Path(path)
        if self.path.resolve() != state.path.resolve():
            raise ValueError("草稿收据与个人资料必须使用同一数据库")
        self.tasks, self.state, self.desktop = tasks, state, desktop
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS draft_reviews (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL,
                draft_id TEXT NOT NULL, draft TEXT NOT NULL, expires REAL NOT NULL,
                state TEXT NOT NULL, change_id TEXT NOT NULL, desktop_id TEXT,
                before_text TEXT NOT NULL, after_text TEXT NOT NULL,
                UNIQUE(task_id,run_id,draft_id))""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _draft(self, task_id, run_id, draft_id):
        task = self.tasks.get_task(task_id)
        if task["state"] == "cancelled":
            raise ValueError("任务已取消，请重新建立任务并授权后再修改。")
        run = self.tasks.get_run(task_id, run_id)
        draft = next((item for item in run.get("drafts", []) if item.get("id") == draft_id), None)
        if not draft:
            raise ValueError("找不到这份任务草稿。")
        grants = task.get("grants") or {}
        if grants.get("consent") is not True:
            raise ValueError("这项任务的资料授权已撤回。")
        if draft.get("kind") == "resume":
            if not grants.get("resume") or draft.get("target") not in RESUME_FIELDS:
                raise ValueError("这项任务没有授权修改该简历栏目。")
        elif draft.get("kind") == "file":
            target = self.desktop.target(draft.get("path"))
            if target not in [Path(value).resolve() for value in grants.get("files", [])]:
                raise ValueError("此文件不在任务授权范围中。")
        else:
            raise ValueError("暂不支持这种草稿。")
        return draft

    def _resume(self):
        snapshot = self.state.snapshot()
        resume = json.loads(snapshot["data"].get(RESUME_KEY, "{}"))
        if not isinstance(resume, dict):
            raise ValueError("保存的简历格式无效。")
        return snapshot, resume

    def preview(self, body):
        task_id, run_id, draft_id = (body.get(key) for key in ("task_id", "run_id", "draft_id"))
        draft = self._draft(task_id, run_id, draft_id)
        if draft.get("state") in ("applied", "undone"):
            raise ValueError("这份草稿已处理，请查看任务中的修改记录。")
        if draft["kind"] == "resume":
            _, resume = self._resume()
            before, after = resume.get(draft["target"], ""), draft["text"]
            if before != draft["base_text"]:
                raise ValueError("简历在起草后已变化，请重新分析，避免覆盖新内容。")
            label = "简历 · " + draft["target"]
        else:
            target = self.desktop.target(draft["path"])
            if digest(target.read_bytes()) != draft["original_hash"]:
                raise ValueError("文件在起草后已变化，请重新分析。")
            # Also validate Word run boundaries and exact single-occurrence replacement.
            self.desktop.preview(draft)
            before, after = draft["old_text"], draft["new_text"]
            label = target.name
        if not isinstance(before, str) or not isinstance(after, str) or before == after:
            raise ValueError("草稿没有有效的文字修改。")
        identifier = secrets.token_urlsafe(24)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT state FROM draft_reviews WHERE task_id=? AND run_id=? AND draft_id=?",
                             (task_id, run_id, draft_id)).fetchone()
            if old and old["state"] != "preview":
                raise ValueError("此草稿已经应用或正在恢复，请勿重复写入。")
            db.execute("DELETE FROM draft_reviews WHERE task_id=? AND run_id=? AND draft_id=?", (task_id, run_id, draft_id))
            db.execute("INSERT INTO draft_reviews (id,task_id,run_id,draft_id,draft,expires,state,change_id,desktop_id,before_text,after_text) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (identifier, task_id, run_id, draft_id, json.dumps(draft, ensure_ascii=False),
                        time.time() + 1200, "preview", secrets.token_urlsafe(24), None, before, after))
        return {"preview_id": identifier, "kind": draft["kind"], "label": label, "before": before, "after": after}

    def _mark(self, row, state):
        self.tasks.mark_draft(row["task_id"], row["run_id"], row["draft_id"], state, {"change_id": row["change_id"]})

    def apply(self, body):
        if body.get("confirm") is not True:
            raise ValueError("请先预览差异并确认写入。")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM draft_reviews WHERE id=?", (body.get("preview_id"),)).fetchone()
            if not row:
                raise ValueError("找不到预览，请重新预览。")
            draft = self._draft(row["task_id"], row["run_id"], row["draft_id"])
            if row["state"] == "applying" and draft["kind"] == "file":
                meta = self.desktop.store / (row["desktop_id"] + ".json")
                if meta.is_file():
                    record = json.loads(meta.read_text(encoding="utf-8"))
                    if digest(self.desktop.target(draft["path"]).read_bytes()) == record["after"]:
                        db.execute("UPDATE draft_reviews SET state='applied' WHERE id=?", (row["id"],))
                        db.commit()
                        self._mark(row, "applied")
                        return {"kind": "file", "change_id": row["change_id"]}
                raise ValueError("上次写入中断，请在桌面文件的修改历史中核对备份并撤销。")
            if row["state"] == "applied":
                self._mark(row, "applied")
                return {"kind": draft["kind"], "change_id": row["change_id"]}
            if row["state"] != "preview" or row["expires"] < time.time():
                raise ValueError("预览已过期或已撤销，请重新核对。")
            snapshot = None
            if draft["kind"] == "resume":
                snapshot, resume = self._resume()
                current = resume.get(draft["target"], "")
                if current != row["before_text"]:
                    raise ValueError("简历在预览后发生变化，请重新分析。")
                resume[draft["target"]] = row["after_text"]
                data = dict(snapshot["data"])
                data[RESUME_KEY] = json.dumps(resume, ensure_ascii=False)
                snapshot = self.state.save_in_transaction(db, {"base_revision": snapshot["revision"], "data": data})
            else:
                target = self.desktop.target(draft["path"])
                if digest(target.read_bytes()) != draft["original_hash"]:
                    raise ValueError("文件在预览后发生变化，请重新分析。")
                preview = self.desktop.preview(draft)
                edit_id = uuid.uuid4().hex
                db.execute("UPDATE draft_reviews SET state='applying',desktop_id=? WHERE id=?", (edit_id, row["id"]))
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                try:
                    self.desktop.commit(preview["stage_id"], edit_id=edit_id)
                except Exception:
                    # Keep the durable receipt if a file write may already have happened.
                    if not (self.desktop.store / (edit_id + ".json")).exists():
                        db.execute("UPDATE draft_reviews SET state='preview',desktop_id=NULL WHERE id=?", (row["id"],))
                        db.commit()
                    raise
            db.execute("UPDATE draft_reviews SET state='applied' WHERE id=?", (row["id"],))
            db.commit()
            self._mark(row, "applied")
            return {"kind": draft["kind"], "change_id": row["change_id"], "state": snapshot}

    def undo(self, body):
        if body.get("confirm") is not True:
            raise ValueError("请确认撤销此次修改。")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM draft_reviews WHERE change_id=?", (body.get("change_id"),)).fetchone()
            if not row or row["state"] not in ("applied", "applying", "undoing", "undone"):
                raise ValueError("找不到可撤销的修改。")
            draft = json.loads(row["draft"])
            snapshot = None
            if row["state"] == "undone":
                self._mark(row, "undone")
                return {"kind": draft["kind"], "change_id": row["change_id"]}
            if draft["kind"] == "resume":
                snapshot, resume = self._resume()
                current = resume.get(draft["target"], "")
                if current == row["after_text"]:
                    resume[draft["target"]] = row["before_text"]
                    data = dict(snapshot["data"])
                    data[RESUME_KEY] = json.dumps(resume, ensure_ascii=False)
                    snapshot = self.state.save_in_transaction(db, {"base_revision": snapshot["revision"], "data": data})
                elif current != row["before_text"] or row["state"] not in ("undoing", "applying"):
                    raise ValueError("简历在写入后又发生变化，不能自动撤销。")
            else:
                db.execute("UPDATE draft_reviews SET state='undoing' WHERE id=?", (row["id"],))
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                meta = self.desktop.store / (row["desktop_id"] + ".json")
                record = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
                if not (record.get("status") == "undone" and
                        digest(self.desktop.target(draft["path"]).read_bytes()) == record.get("before")):
                    self.desktop.undo(row["desktop_id"])
            db.execute("UPDATE draft_reviews SET state='undone' WHERE id=?", (row["id"],))
            db.commit()
            self._mark(row, "undone")
            return {"kind": draft["kind"], "change_id": row["change_id"], "state": snapshot}
