from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hook import install_adapter_patch, install_registry_patch  # noqa: E402


class FakeStore:
    def __init__(self):
        self.added = []
        self.context = ""

    def add(self, chat_id, data):
        self.added.append((chat_id, data))
        return True

    def render(self, chat_id):
        return self.context


def make_adapter_class(*, group_allowed=True, addressed=False):
    store = FakeStore()

    class Adapter:
        def __init__(self):
            self.original_calls = []

        def _is_group_allowed(self, chat_id, sender_id=""):
            return group_allowed

        def _should_process_message(self, data):
            return bool(data.get("addressed", addressed))

        async def _build_message_event(self, data):
            self.original_calls.append(data)
            return SimpleNamespace(channel_context=None)

    install_adapter_patch(Adapter, lambda _adapter: store)
    return Adapter, store


class RegistryHookTests(unittest.TestCase):
    def make_registry_class(self):
        store = FakeStore()

        class Adapter:
            def __init__(self):
                self.original_calls = []

            def _is_group_allowed(self, chat_id, sender_id=""):
                return True

            def _should_process_message(self, data):
                return bool(data.get("addressed", False))

            async def _build_message_event(self, data):
                self.original_calls.append(data)
                return SimpleNamespace(channel_context=None)

        class OtherAdapter(Adapter):
            pass

        class Registry:
            def create_adapter(self, name, config):
                return Adapter() if name == "whatsapp" else OtherAdapter()

        return Registry, Adapter, OtherAdapter, store

    def test_whatsapp_adapter_is_patched_at_creation(self):
        Registry, Adapter, OtherAdapter, store = self.make_registry_class()
        self.assertTrue(install_registry_patch(Registry, lambda _adapter: store))
        registry = Registry()
        adapter = registry.create_adapter("whatsapp", {})
        event = asyncio.run(
            adapter._build_message_event(
                {"isGroup": True, "chatId": "group@g.us", "body": "chatter"}
            )
        )
        self.assertIsNone(event)
        self.assertEqual(len(store.added), 1)

    def test_other_platforms_are_not_patched(self):
        Registry, Adapter, OtherAdapter, store = self.make_registry_class()
        self.assertTrue(install_registry_patch(Registry, lambda _adapter: store))
        registry = Registry()
        adapter = registry.create_adapter("telegram", {})
        event = asyncio.run(adapter._build_message_event({"isGroup": True, "chatId": "x"}))
        self.assertIsNotNone(event)
        self.assertFalse(getattr(OtherAdapter, "_hermes_whatsapp_observed_context_patched", False))

    def test_registry_patch_is_idempotent(self):
        Registry, _Adapter, _Other, store = self.make_registry_class()
        self.assertTrue(install_registry_patch(Registry, lambda _adapter: store))
        self.assertTrue(install_registry_patch(Registry, lambda _adapter: store))


class HookTests(unittest.TestCase):
    def test_unmentioned_group_message_is_buffered_not_dispatched(self):
        Adapter, store = make_adapter_class(addressed=False)
        adapter = Adapter()
        event = asyncio.run(
            adapter._build_message_event(
                {"isGroup": True, "chatId": "group@g.us", "body": "chatter"}
            )
        )
        self.assertIsNone(event)
        self.assertEqual(len(store.added), 1)
        self.assertEqual(adapter.original_calls, [])

    def test_mention_gets_context_and_dispatches(self):
        Adapter, store = make_adapter_class(addressed=True)
        store.context = "[Observed context]"
        adapter = Adapter()
        event = asyncio.run(
            adapter._build_message_event(
                {"isGroup": True, "chatId": "group@g.us", "addressed": True, "body": "@bot hi"}
            )
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.channel_context, "[Observed context]")
        self.assertEqual(len(adapter.original_calls), 1)
        self.assertEqual(store.added, [])

    def test_disallowed_group_is_not_buffered(self):
        Adapter, store = make_adapter_class(group_allowed=False)
        adapter = Adapter()
        event = asyncio.run(
            adapter._build_message_event(
                {"isGroup": True, "chatId": "other@g.us", "body": "chatter"}
            )
        )
        self.assertIsNotNone(event)
        self.assertEqual(store.added, [])
        self.assertEqual(len(adapter.original_calls), 1)

    def test_dm_is_untouched(self):
        Adapter, store = make_adapter_class()
        adapter = Adapter()
        event = asyncio.run(
            adapter._build_message_event({"isGroup": False, "chatId": "dm", "body": "hi"})
        )
        self.assertIsNotNone(event)
        self.assertEqual(store.added, [])
        self.assertEqual(len(adapter.original_calls), 1)


if __name__ == "__main__":
    unittest.main()
