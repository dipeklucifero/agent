"""Telegram-ops skills - used for *other* groups (not the owner-only bot).

Since a bot cannot join groups it wasn't invited to, these use the Telethon
*userbot* session configured via TELEGRAM_API_ID / TELEGRAM_API_HASH.

ROADMAP:
  - telegram_ops.join_group(invite_link_or_username) -> ok
  - telegram_ops.leave_group(username) -> ok
  - telegram_ops.react(chat, message_id, emoji) -> ok
  - telegram_ops.send_dm(username, text) -> ok
  - telegram_ops.list_my_groups() -> [...]

Implementation notes:
  - Initialise a single Telethon client at boot and stash on AgentDeps.
  - Social=True to get rate limit jitter from policies.social_pacing.telegram.
  - First run requires interactive phone+code login. Do it once on the VPS:
    ``docker compose run --rm agent python -m agent.tools.telethon_login``
"""
