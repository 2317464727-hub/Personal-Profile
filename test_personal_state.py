import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from personal_state import PersonalStateStore, StateConflict


PROFILE = "whq-personal-profile-v1"
LOGS = "whq-personal-logs-v1"


class PersonalStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / ".personal-state.sqlite3"
        self.store = PersonalStateStore(self.path)

    def test_first_import_survives_restart_and_repeat_save_is_idempotent(self):
        data = {PROFILE: json.dumps({"name": "测试用户"}), LOGS: '[{"id":"log-1","title":"已核对"}]'}
        saved = self.store.save({"base_revision": 0, "data": data})
        self.assertEqual(saved["revision"], 1)
        reopened = PersonalStateStore(self.path)
        self.assertEqual(reopened.snapshot(), saved)
        self.assertEqual(reopened.save({"base_revision": 1, "data": data}), saved)

    def test_stale_writer_cannot_overwrite_newer_resume(self):
        first = self.store.save({"base_revision": 0, "data": {PROFILE: '{"name":"新版"}'}})
        with self.assertRaises(StateConflict) as raised:
            self.store.save({"base_revision": 0, "data": {PROFILE: '{"name":"旧版"}'}})
        self.assertEqual(raised.exception.snapshot, first)
        self.assertEqual(self.store.snapshot(), first)

    def test_competing_writers_only_one_succeeds(self):
        outcomes = []
        barrier = threading.Barrier(2)

        def write(name):
            store = PersonalStateStore(self.path)
            barrier.wait()
            try:
                store.save({"base_revision": 0, "data": {PROFILE: json.dumps({"name": name})}})
                outcomes.append("saved")
            except StateConflict:
                outcomes.append("conflict")

        threads = [threading.Thread(target=write, args=(str(number),)) for number in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["saved", "conflict"])

    def test_restore_keeps_previous_version_and_can_be_reversed(self):
        original = {PROFILE: '{"name":"原资料"}'}
        self.store.save({"base_revision": 0, "data": original})
        backup = self.store.backup()
        self.store.save({"base_revision": 1, "data": {PROFILE: '{"name":"当前资料"}'}})
        restored = self.store.restore({"base_revision": 2, "backup": backup, "confirm": True})
        self.assertEqual(restored["data"], original)
        previous = self.store.previous_backup()
        self.assertEqual(json.loads(previous["data"][PROFILE])["name"], "当前资料")
        undone = self.store.restore({"base_revision": 3, "backup": previous, "confirm": True})
        self.assertEqual(undone["data"], previous["data"])

    def test_restore_requires_confirmation_and_valid_format(self):
        for body in ({"base_revision": 0, "backup": self.store.backup()},
                     {"base_revision": 0, "confirm": True, "backup": {"data": {}}}):
            with self.assertRaises(ValueError):
                self.store.restore(body)
        self.assertEqual(self.store.snapshot()["revision"], 0)

    def test_rejects_permissions_malformed_and_oversized_data(self):
        bad_data = [
            {"whq-personal-ai-access-v1": '{"local":"all"}'},
            {PROFILE: "[]"}, {LOGS: "{}"}, {PROFILE: "not-json"},
            {PROFILE: '{"x":"' + 'a' * (5 * 1024 * 1024) + '"}'},
            {"whq-personal-resume-photo-v1": "javascript:alert(1)"},
        ]
        for data in bad_data:
            with self.subTest(data=list(data)):
                with self.assertRaises(ValueError):
                    self.store.save({"base_revision": 0, "data": data})
        self.assertEqual(self.store.snapshot()["data"], {})

    def test_atomic_draft_receipt_rollback_preserves_both_state_and_receipt(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE receipt (id TEXT)")
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        self.store.save_in_transaction(db, {"base_revision": 0, "data": {PROFILE: '{"name":"草稿"}'}})
        db.execute("INSERT INTO receipt VALUES ('draft-1')")
        db.rollback()
        self.assertEqual(self.store.snapshot()["revision"], 0)
        self.assertEqual(db.execute("SELECT count(*) FROM receipt").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
