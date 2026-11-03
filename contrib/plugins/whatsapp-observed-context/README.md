# WhatsApp Observed Group Context

A general Hermes plugin that makes the WhatsApp bot read the group without
replying to every message.

- Unmentioned messages in an allowlisted group are stored as context.
- The bot still replies only to @mentions, replies to its own messages, and
  `/commands`.
- When it is addressed, the recent unmentioned messages are attached to that
  turn as `MessageEvent.channel_context`.
- Storage is SQLite, so the buffer and per-group cursor survive gateway
  restarts and reboots.

This is a **user plugin**, not a bundled platform adapter. It patches the
bundled WhatsApp adapter at load time and fails closed if that adapter's
private API changes.

## Install

Copy this directory into the Hermes profile:

```bash
install -d -m 0755 ~/.hermes/plugins
cp -a whatsapp-observed-context ~/.hermes/plugins/whatsapp-observed-context
```

Enable it in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - whatsapp-observed-context
```

Or use the CLI:

```bash
hermes plugins enable whatsapp-observed-context
```

Add the settings to `~/.hermes/.env`:

```bash
WHATSAPP_OBSERVE_UNMENTIONED_GROUP_MESSAGES=true
WHATSAPP_OBSERVE_MAX_MESSAGES=100
WHATSAPP_OBSERVE_MAX_CHARS=12000
WHATSAPP_OBSERVE_TTL_HOURS=24
# optional:
# WHATSAPP_OBSERVE_TZ=Asia/Singapore
# WHATSAPP_OBSERVE_DB_PATH=/home/hermes/.hermes/whatsapp/group-context.sqlite3
```

Keep the normal mention and group settings:

```bash
WHATSAPP_GROUP_POLICY=allowlist
WHATSAPP_GROUP_ALLOWED_USERS=<group-jid>@g.us
WHATSAPP_REQUIRE_MENTION=true
```

Restart the gateway:

```bash
sudo systemctl restart hermes-gateway-7944f2ae.service
```

## What the limits mean

| Setting | Scope |
|---|---|
| `WHATSAPP_OBSERVE_MAX_MESSAGES` | Per group. The store keeps at most this many recent messages; older rows are purged. It is also the maximum number of messages selected for one mention. |
| `WHATSAPP_OBSERVE_MAX_CHARS` | Per injected mention. Oldest lines are dropped until the header, body, and footer fit. |
| `WHATSAPP_OBSERVE_TTL_HOURS` | Per group. Messages older than this are purged and never injected. |

These are **context-size controls**, not WhatsApp retention controls. A busy
group will rotate through the newest messages within the TTL.

The store keeps a per-group cursor. After a mention, the next mention receives
only messages that arrived after the previous mention; history is not
re-injected on every reply.

## Restart behavior

- The SQLite database and cursor persist across gateway restarts and reboots.
- A restart does **not** lose the buffered group history within the configured
  TTL/message limit.
- If the plugin is disabled or the database is deleted, the buffer is gone; the
  normal session transcript still contains previous addressed turns only.

Default database:

```text
~/.hermes/whatsapp/group-context.sqlite3
```

It is created with mode `0600`; the parent directory is `0700`.

## Behavior details

- Only messages belonging to an allowlisted group JID are buffered.
- DMs, non-allowlisted groups, and broadcast pseudo-chats are untouched.
- Media captions are stored; uncaptioned media becomes a placeholder such as
  `[image received]`. Media files are not retained.
- Duplicate bridge message IDs are ignored.
- If the adapter API is unavailable, the plugin logs a warning and the stock
  WhatsApp behavior continues.
- The plugin does not decide “relevance” on its own. Mention/reply/command is
  still the trigger; this only supplies the context for that turn.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Uninstall / rollback

```bash
hermes plugins disable whatsapp-observed-context
sudo systemctl restart hermes-gateway-7944f2ae.service
```

The bundled WhatsApp adapter is not shadowed, so disabling the plugin restores
normal mention-only behavior. The SQLite file remains unless deleted.
