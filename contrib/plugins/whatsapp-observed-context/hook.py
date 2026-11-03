"""Adapter patch for the WhatsApp observed-context plugin.

Kept separate from plugin registration so it can be unit-tested with a fake
adapter and without importing the Hermes gateway.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("plugins.whatsapp_observed_context.hook")

_PATCH_MARKER = "_hermes_whatsapp_observed_context_patched"


def install_adapter_patch(
    adapter_cls: type,
    store_factory: Callable[[Any], Any],
    *,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Install the observed-context wrapper on ``adapter_cls``.

    Returns True when the patch is installed (or was already installed).
    The wrapper is deliberately defensive: if Hermes changes the adapter
    internals, it logs and falls back to the original method.
    """
    log = log or logger
    if getattr(adapter_cls, _PATCH_MARKER, False):
        return True

    original = getattr(adapter_cls, "_build_message_event", None)
    if original is None or not callable(original):
        log.warning(
            "whatsapp-observed-context: adapter has no _build_message_event; "
            "observed group context is disabled"
        )
        return False

    async def patched_build_message_event(self, data: dict[str, Any]):
        if not data.get("isGroup"):
            return await original(self, data)

        chat_id = str(data.get("chatId") or "").strip()
        if not chat_id:
            return await original(self, data)

        try:
            try:
                allowed = self._is_group_allowed(chat_id, str(data.get("senderId") or ""))
            except TypeError:
                allowed = self._is_group_allowed(chat_id)
        except Exception as exc:
            log.debug("whatsapp-observed-context: group allowlist check failed: %s", exc)
            return await original(self, data)
        if not allowed:
            return await original(self, data)

        try:
            addressed = self._should_process_message(data)
        except Exception as exc:
            log.debug("whatsapp-observed-context: mention check failed: %s", exc)
            return await original(self, data)

        if not addressed:
            try:
                store_factory(self).add(chat_id, data)
            except Exception:
                log.exception("whatsapp-observed-context: failed to buffer group message")
            # Do not dispatch an unmentioned group message.
            return None

        event = await original(self, data)
        if event is None:
            return None
        try:
            context = store_factory(self).render(chat_id)
        except Exception:
            log.exception("whatsapp-observed-context: failed to render group context")
            return event
        if context:
            existing = getattr(event, "channel_context", None)
            event.channel_context = f"{existing}\n\n{context}" if existing else context
            log.info(
                "whatsapp-observed-context: attached %d chars of group context for %s",
                len(context),
                chat_id,
            )
        return event

    setattr(adapter_cls, "_build_message_event", patched_build_message_event)
    setattr(adapter_cls, _PATCH_MARKER, True)
    log.info("whatsapp-observed-context: adapter patch installed")
    return True
