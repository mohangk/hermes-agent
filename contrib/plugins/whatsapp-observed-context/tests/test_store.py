from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import ObservedContextStore  # noqa: E402

GROUP = "120363000000000000@g.us"


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 2_000.0
        self.db_path = Path(self.tmp.name) / "context.sqlite3"
        self.store = ObservedContextStore(
            self.db_path,
            max_messages=100,
            max_chars=12_000,
            ttl_hours=24,
            timezone_name="UTC",
            now_fn=lambda: self.now,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def add(self, ts: float, body: str, message_id: str | None = None, **extra):
        return self.store.add(
            GROUP,
            {
                "messageId": message_id or f"m{ts}",
                "timestamp": ts,
                "senderName": extra.pop("senderName", "Alice"),
                "senderId": "15551234567@s.whatsapp.net",
                "body": body,
                **extra,
            },
        )

    def test_render_advances_cursor(self):
        self.add(1_000.0, "one")
        self.add(1_001.0, "two")
        first = self.store.render(GROUP)
        self.assertIn("Alice: one", first)
        self.assertIn("Alice: two", first)
        self.assertEqual(self.store.render(GROUP), "")

        self.add(1_002.0, "three")
        second = self.store.render(GROUP)
        self.assertIn("Alice: three", second)
        self.assertNotIn("Alice: one", second)

    def test_persistence_across_store_reopen(self):
        self.add(1_000.0, "one")
        self.add(1_001.0, "two")
        first = self.store.render(GROUP)
        self.assertIn("Alice: one", first)
        self.store.close()

        self.store = ObservedContextStore(
            self.db_path,
            max_messages=100,
            max_chars=12_000,
            ttl_hours=24,
            timezone_name="UTC",
            now_fn=lambda: self.now,
        )
        self.add(1_002.0, "three")
        text = self.store.render(GROUP)
        self.assertIn("Alice: three", text)
        self.assertNotIn("Alice: one", text)
        self.assertNotIn("Alice: two", text)

    def test_max_messages_keeps_newest(self):
        for i in range(5):
            self.add(1_000.0 + i, f"m{i}")
        self.store.max_messages = 2
        text = self.store.render(GROUP)
        self.assertNotIn("m0", text)
        self.assertNotIn("m1", text)
        self.assertNotIn("m2", text)
        self.assertIn("m3", text)
        self.assertIn("m4", text)

    def test_max_chars_bounds_context(self):
        self.store.max_chars = 500
        for i in range(10):
            self.add(1_000.0 + i, "x" * 100)
        text = self.store.render(GROUP)
        self.assertLessEqual(len(text), 500)
        self.assertIn("[Observed WhatsApp group context", text)
        self.assertIn("[End observed context]", text)

    def test_ttl_excludes_old_messages(self):
        self.add(1_000.0, "old")
        self.now = 1_000.0 + 25 * 3600
        self.add(self.now, "new")
        text = self.store.render(GROUP)
        self.assertIn("new", text)
        self.assertNotIn("old", text)

    def test_media_placeholder(self):
        self.add(1_000.0, "", hasMedia=True, mediaType="image")
        text = self.store.render(GROUP)
        self.assertIn("[image received]", text)

    def test_deduplicates_message_id(self):
        self.add(1_000.0, "hello", message_id="same")
        self.add(1_001.0, "hello", message_id="same")
        self.assertEqual(self.store.stats(GROUP)["count"], 1)

    def test_disallowed_group_has_no_rows(self):
        self.store.add("other@g.us", {"messageId": "x", "timestamp": 1_000, "body": "x"})
        self.assertEqual(self.store.render(GROUP), "")


if __name__ == "__main__":
    unittest.main()
