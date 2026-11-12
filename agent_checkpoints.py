"""Local, bounded checkpoints for manually continuing an agent task."""

import copy
import json
import os
import re
import secrets
import time
from pathlib import Path
from threading import Lock


class CheckpointStore:
    def __init__(self, path, ttl_seconds=7 * 24 * 3600, max_entries=8):
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.lock = Lock()
        self.active = set()

    def _read(self):
        if not self.path.exists():
            return {}
        if self.path.stat().st_size > 32_000_000:
            raise ValueError("检查点文件过大")
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("检查点文件格式无效")
        return value

    def _write(self, entries):
        data = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, self.path)

    def save(self, payload, scope, model, repeat_counts):
        state = {"payload": payload, "scope": scope, "model": model, "repeat_counts": repeat_counts}
        if len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > 8_000_000:
            raise ValueError("任务上下文过大，无法保存检查点")
        identifier = secrets.token_urlsafe(24)
        now = time.time()
        with self.lock:
            entries = self._read()
            entries = {key: item for key, item in entries.items()
                       if isinstance(item, dict) and now - item.get("saved_at", 0) < self.ttl_seconds}
            entries[identifier] = dict(state, saved_at=now)
            newest = sorted(entries.items(), key=lambda pair: pair[1]["saved_at"], reverse=True)
            self._write(dict(newest[:self.max_entries]))
        return identifier

    def save_progress(self, identifier, payload, scope, model, repeat_counts):
        state = {"payload": payload, "scope": scope, "model": model, "repeat_counts": repeat_counts}
        if len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > 8_000_000:
            raise ValueError("任务上下文过大，无法保存检查点")
        now = time.time()
        with self.lock:
            entries = self._read()
            if identifier:
                if identifier not in entries:
                    raise ValueError("检查点不存在或已过期")
            else:
                identifier = secrets.token_urlsafe(24)
            entries = {key: item for key, item in entries.items()
                       if key == identifier or isinstance(item, dict) and now - item.get("saved_at", 0) < self.ttl_seconds}
            entries[identifier] = dict(state, saved_at=now)
            if len(entries) > self.max_entries:
                removable = sorted((key for key in entries if key not in self.active and key != identifier),
                                   key=lambda key: entries[key]["saved_at"])
                while len(entries) > self.max_entries and removable:
                    entries.pop(removable.pop(0))
            if len(entries) > self.max_entries:
                raise ValueError("同时运行的任务过多，请稍后继续")
            self._write(entries)
            self.active.add(identifier)
        return identifier

    def load(self, identifier, scope):
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", identifier):
            raise ValueError("检查点编号无效")
        with self.lock:
            item = self._read().get(identifier)
        if not isinstance(item, dict) or time.time() - item.get("saved_at", 0) >= self.ttl_seconds:
            raise ValueError("检查点不存在或已过期")
        if item.get("scope") != scope:
            raise PermissionError("请恢复任务原来的访问权限后再继续")
        return copy.deepcopy(item)

    def claim(self, identifier, scope):
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", identifier):
            raise ValueError("检查点编号无效")
        with self.lock:
            if identifier in self.active:
                raise ValueError("这条任务正在另一个页面续做")
            item = self._read().get(identifier)
            if not isinstance(item, dict) or time.time() - item.get("saved_at", 0) >= self.ttl_seconds:
                raise ValueError("检查点不存在或已过期")
            if item.get("scope") != scope:
                raise PermissionError("请恢复任务原来的访问权限后再继续")
            self.active.add(identifier)
            return copy.deepcopy(item)

    def release(self, identifier):
        with self.lock:
            self.active.discard(identifier)

    def is_active(self, identifier):
        with self.lock:
            return identifier in self.active

    def delete(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", identifier):
            return False
        with self.lock:
            if identifier in self.active:
                return False
            entries = self._read()
            if identifier not in entries:
                return False
            del entries[identifier]
            self._write(entries)
        return True

    def complete(self, identifier):
        with self.lock:
            self.active.discard(identifier)
            entries = self._read()
            if identifier not in entries:
                return False
            del entries[identifier]
            self._write(entries)
        return True
