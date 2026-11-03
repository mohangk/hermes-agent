"""Hermes general plugin: observed WhatsApp group context.

Enable with ``WHATSAPP_OBSERVE_UNMENTIONED_GROUP_MESSAGES=true`` and
``plugins.enabled: [whatsapp-observed-context]``. Unmentioned messages in an
allowlisted group are buffered; the next @mention/reply/command gets the
buffered lines via ``MessageEvent.channel_context``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from .hook import install_adapter_patch
from .store import ObservedContextStore

logger = logging.getLogger("plugins.whatsapp_observed_context")

_TRUTHY = {"1", "true", "yes", "on"}
_PLUGIN_ID = "whatsapp-observed-context"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _profile_home(adapter: Any) -> Path:
    value = getattr(adapter, "_profile_home", None)
    if value:
        return Path(value)
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def _db_path(adapter: Any) -> Path:
    configured = str(os.environ.get("WHATSAPP_OBSERVE_DB_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return _profile_home(adapter) / "whatsapp" / "group-context.sqlite3"


def _store_factory(adapter: Any) -> ObservedContextStore:
    store = getattr(adapter, "_hermes_observed_context_store", None)
    if store is None:
        store = ObservedContextStore(
            _db_path(adapter),
            max_messages=_env_int("WHATSAPP_OBSERVE_MAX_MESSAGES", 100),
            max_chars=_env_int("WHATSAPP_OBSERVE_MAX_CHARS", 12_000),
            ttl_hours=_env_float("WHATSAPP_OBSERVE_TTL_HOURS", 24.0),
            timezone_name=str(os.environ.get("WHATSAPP_OBSERVE_TZ") or "Asia/Singapore"),
        )
        setattr(adapter, "_hermes_observed_context_store", store)
    return store


def _on_session_start(**_payload: Any) -> None:
    # Registering a valid hook gives the plugin a normal loadable extension and
    # keeps ``hermes plugins validate`` happy without exposing model tools.
    return None


def _install_registry_hook() -> bool:
    """Patch the actual adapter class when the gateway creates the WhatsApp adapter.

    The bundled platform plugin is loaded through the synthetic
    ``hermes_plugins.platforms__whatsapp`` namespace, which is a different module
    object from ``plugins.platforms.whatsapp``. Patching the import by dotted path
    can therefore miss the class the gateway actually instantiates. Wrapping the
    platform registry hook is alias-safe.
    """
    try:
        from gateway.platform_registry import PlatformRegistry
    except Exception:
        logger.exception("whatsapp-observed-context: cannot import platform registry")
        return False

    if getattr(PlatformRegistry, "_hermes_whatsapp_observed_registry_hook", False):
        return True

    original_create_adapter = PlatformRegistry.create_adapter

    def create_adapter(self, name, config):
        adapter = original_create_adapter(self, name, config)
        if str(name).strip().lower() == "whatsapp" and adapter is not None:
            install_adapter_patch(type(adapter), _store_factory, log=logger)
        return adapter

    PlatformRegistry.create_adapter = create_adapter
    PlatformRegistry._hermes_whatsapp_observed_registry_hook = True
    logger.info("whatsapp-observed-context: registry hook installed; adapter will be patched on creation")
    return True


def register(ctx: Any) -> None:
    """Hermes plugin entry point."""
    try:
        ctx.register_hook("on_session_start", _on_session_start)
    except Exception:
        logger.debug("whatsapp-observed-context: on_session_start hook not registered", exc_info=True)

    if not _env_bool("WHATSAPP_OBSERVE_UNMENTIONED_GROUP_MESSAGES"):
        logger.info(
            "whatsapp-observed-context: disabled "
            "(set WHATSAPP_OBSERVE_UNMENTIONED_GROUP_MESSAGES=true to enable)"
        )
        return

    installed = _install_registry_hook()
    if installed:
        logger.info(
            "whatsapp-observed-context: buffering unmentioned group messages "
            "(max=%s, chars=%s, ttl=%sh)",
            _env_int("WHATSAPP_OBSERVE_MAX_MESSAGES", 100),
            _env_int("WHATSAPP_OBSERVE_MAX_CHARS", 12_000),
            _env_float("WHATSAPP_OBSERVE_TTL_HOURS", 24.0),
        )
