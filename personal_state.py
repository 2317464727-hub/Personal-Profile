"""Local personal data with optimistic concurrency and reversible restores.

Only explicitly listed browser data is stored. Access grants and credentials are
deliberately not part of this store or its portable backups.
"""

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


OBJECT_KEYS = {
    "whq-personal-profile-v1", "whq-personal-resume-v1",
    "whq-resume-advice-review-v1", "whq-week-pending-v1",
}
ARRAY_KEYS = {
    "whq-personal-logs-v1", "whq-resume-work-additions-v1",
    "whq-resume-reviewed-sources-v1", "whq-resume-pending-draft-v1",
    "whq-personal-ai-runs-v1", "whq-personal-ai-keywords-v1",
    "whq-personal-ai-keywords-scoped-v1", "whq-home-hidden-logs-v1",
}
FLAG_KEYS = {"whq-resume-legacy-ai-migrated-v1", "whq-recent-work-2026-10-27-v1"}
PHOTO_KEY = "whq-personal-resume-photo-v1"
ALLOWED_KEYS = OBJECT_KEYS | ARRAY_KEYS | FLAG_KEYS | {PHOTO_KEY}
MAX_BYTES = 12 * 1024 * 1024
BACKUP_FORMAT = "whq-personal-backup"
BACKUP_SCOPE = "个人资料、周历文字、简历及照片、简历草稿、AI 对话和关键词；不包含周历附件文件、画布附件、定时任务、访问权限或密钥。"


class StateConflict(ValueError):
    def __init__(self, snapshot):
        super().__init__("资料已在其他页面更新，请先核对两个版本。")
        self.snapshot = snapshot


def _invalid_json_constant(_constant):
    raise ValueError("非标准 JSON 数值")


def validate_data(data):
    if not isinstance(data, dict) or set(data) - ALLOWED_KEYS:
        raise ValueError("备份包含不支持的资料字段或权限设置。")
    result = {}
    for key, value in data.items():
        if not isinstance(value, str) or len(value.encode("utf-8")) > 5 * 1024 * 1024:
            raise ValueError("资料字段无效或超过 5 MB。")
        if key in OBJECT_KEYS | ARRAY_KEYS:
            try:
                decoded = json.loads(value, parse_constant=_invalid_json_constant)
            except (ValueError, TypeError, RecursionError) as exc:
                raise ValueError("资料不是有效的 JSON。") from exc
            if key in OBJECT_KEYS and not isinstance(decoded, dict):
                raise ValueError("个人资料或简历的结构无效。")
            if key in ARRAY_KEYS and not isinstance(decoded, list):
                raise ValueError("记录或草稿的结构无效。")
        elif key in FLAG_KEYS and value != "1":
            raise ValueError("迁移状态无效。")
        elif key == PHOTO_KEY and value and not re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\r\n]+", value):
            raise ValueError("简历照片需为 PNG、JPEG 或 WebP 图片。")
        result[key] = value
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise ValueError("个人资料超过 12 MB，请先精简对话历史或照片。")
    return result


class PersonalStateStore:
    def __init__(self, path):
        self.path = Path(path)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS personal_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    revision INTEGER NOT NULL, data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO personal_state VALUES (1,0,'{}','');
                CREATE TABLE IF NOT EXISTS personal_restore_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL, revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL, restored_at TEXT NOT NULL
                );
            """)

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

    @staticmethod
    def _snapshot(db):
        row = db.execute("SELECT revision,data,updated_at FROM personal_state WHERE singleton=1").fetchone()
        return {"revision": row["revision"], "data": json.loads(row["data"]), "updated_at": row["updated_at"]}

    def snapshot(self):
        with self._connection() as db:
            return self._snapshot(db)

    @staticmethod
    def _revision(body):
        revision = body.get("base_revision") if isinstance(body, dict) else None
        if type(revision) is not int or revision < 0:
            raise ValueError("缺少有效的资料版本，请刷新后重试。")
        return revision

    def _save(self, body, restoring=False):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.save_in_transaction(db, body, restoring=restoring)

    def save_in_transaction(self, db, body, restoring=False):
        """Use an existing BEGIN IMMEDIATE transaction; caller owns commit.

        This lets a confirmed draft and its undo receipt commit atomically with
        the changed resume. The connection must use sqlite3.Row.
        """
        revision = self._revision(body)
        data = validate_data(body.get("data"))
        current = self._snapshot(db)
        if current["revision"] != revision:
            raise StateConflict(current)
        now = datetime.now(timezone.utc).isoformat()
        if restoring:
            db.execute("INSERT INTO personal_restore_history (data,revision,updated_at,restored_at) VALUES (?,?,?,?)",
                       (json.dumps(current["data"], ensure_ascii=False), current["revision"], current["updated_at"], now))
            db.execute("DELETE FROM personal_restore_history WHERE id NOT IN (SELECT id FROM personal_restore_history ORDER BY id DESC LIMIT 5)")
        if data != current["data"]:
            db.execute("UPDATE personal_state SET revision=revision+1,data=?,updated_at=? WHERE singleton=1",
                       (json.dumps(data, ensure_ascii=False), now))
        return self._snapshot(db)

    def save(self, body):
        return self._save(body)

    @staticmethod
    def _backup(snapshot):
        return {"format": BACKUP_FORMAT, "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "scope": BACKUP_SCOPE, **snapshot}

    def backup(self):
        return self._backup(self.snapshot())

    def previous_backup(self):
        with self._connection() as db:
            row = db.execute("SELECT data,revision,updated_at FROM personal_restore_history ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                raise ValueError("还没有恢复前的备份。")
            return self._backup({"data": json.loads(row["data"]), "revision": row["revision"], "updated_at": row["updated_at"]})

    def restore(self, body):
        if not isinstance(body, dict) or body.get("confirm") is not True:
            raise ValueError("请核对备份并确认恢复。")
        backup = body.get("backup")
        if not isinstance(backup, dict) or backup.get("format") != BACKUP_FORMAT or backup.get("version") != 1:
            raise ValueError("请选择本平台导出的资料备份。")
        return self._save({"base_revision": self._revision(body), "data": backup.get("data")}, restoring=True)
