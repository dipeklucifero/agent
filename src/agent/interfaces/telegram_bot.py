"""Telegram interface - owner-only DM bot.

Accepts messages ONLY from TELEGRAM_OWNER_ID. Everyone else is silently
ignored (logged at debug). Includes a few owner utility commands:

    /start              - hello
    /help               - list available skills
    /disable <family>   - kill switch
    /enable  <family>   - undo kill switch
    /status             - config & recent audit rows
    /reset              - clear working memory for this chat

Everything else is piped into the HermesAgent.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import get_settings, load_policies, save_yaml
from ..llm import HermesAgent
from ..memory import EpisodicMemory, WorkingMemory

log = logging.getLogger(__name__)


def _policies_path():
    return get_settings().config_dir / "policies.yaml"


def build_application(agent: HermesAgent, working: WorkingMemory) -> Application:
    token = get_settings().telegram_bot_token
    app = Application.builder().token(token).build()
    app.bot_data["agent"] = agent
    app.bot_data["working"] = working

    owner_filter = filters.User(user_id=get_settings().telegram_owner_id)

    app.add_handler(CommandHandler("start", _cmd_start, filters=owner_filter))
    app.add_handler(CommandHandler("help", _cmd_help, filters=owner_filter))
    app.add_handler(CommandHandler("status", _cmd_status, filters=owner_filter))
    app.add_handler(CommandHandler("disable", _cmd_disable, filters=owner_filter))
    app.add_handler(CommandHandler("enable", _cmd_enable, filters=owner_filter))
    app.add_handler(CommandHandler("reset", _cmd_reset, filters=owner_filter))
    app.add_handler(
        MessageHandler(owner_filter & filters.TEXT & ~filters.COMMAND, _on_message)
    )
    app.add_handler(MessageHandler(~owner_filter, _deny))
    return app


async def _cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hermes online. Send me a task, or /help for commands."
    )


async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    agent: HermesAgent = context.application.bot_data["agent"]
    lines = ["Skills available:"]
    # Pull directly from registry via a back-reference
    for spec in agent.registry.tool_specs():
        fn = spec["function"]
        lines.append(f"  - {fn['name']}: {fn['description'][:80]}")
    lines.append("")
    lines.append("Commands: /status /disable <family> /enable <family> /reset")
    await update.message.reply_text("\n".join(lines))


async def _cmd_status(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    pol = load_policies()
    ep = EpisodicMemory().recent(limit=5)
    lines = [
        f"disabled families: {pol.disabled_skill_families or '(none)'}",
        f"simulate_by_default: {pol.simulate_by_default}",
        f"max_tx_usd: ${pol.tx_limits.max_tx_usd} (hard ${pol.tx_limits.hard_max_tx_usd})",
        "",
        "recent audit:",
    ]
    for r in ep:
        lines.append(f"  [{r.ts}] {r.status} {r.skill} - {r.notes or ''}")
    await update.message.reply_text("\n".join(lines) or "clean slate")


async def _cmd_disable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("usage: /disable <family>")
        return
    family = context.args[0]
    _toggle_family(family, add=True)
    await update.message.reply_text(f"disabled: {family}")


async def _cmd_enable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("usage: /enable <family>")
        return
    family = context.args[0]
    _toggle_family(family, add=False)
    await update.message.reply_text(f"enabled: {family}")


def _toggle_family(family: str, *, add: bool) -> None:
    cfg = load_policies().model_dump()
    cur = set(cfg.get("disabled_skill_families") or [])
    if add:
        cur.add(family)
    else:
        cur.discard(family)
    cfg["disabled_skill_families"] = sorted(cur)
    save_yaml(_policies_path(), cfg)


async def _cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    working: WorkingMemory = context.application.bot_data["working"]
    working.clear(update.effective_chat.id)
    await update.message.reply_text("working memory cleared")


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    agent: HermesAgent = context.application.bot_data["agent"]
    text = update.message.text or ""
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        reply = await agent.handle(chat_id=chat_id, user_text=text)
    except Exception as e:  # noqa: BLE001
        log.exception("agent crashed")
        reply = f"internal error: {e!r}"
    # Telegram messages cap at ~4096 chars.
    for chunk in _split(reply, 3500):
        await update.message.reply_text(chunk)


async def _deny(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    log.debug("ignoring message from non-owner %s", update.effective_user.id)


def _split(text: str, n: int) -> list[str]:
    return [text[i : i + n] for i in range(0, max(len(text), 1), n)]


# -----------------------------------------------------------------------
# Audit sink factory
# -----------------------------------------------------------------------


def make_audit_sink(app: Application):
    chat_id_raw = get_settings().telegram_audit_chat_id
    if not chat_id_raw:
        return None

    async def sink(msg: str) -> None:
        try:
            await app.bot.send_message(chat_id=chat_id_raw, text=msg)
        except Exception:  # noqa: BLE001
            log.debug("audit sink failed", exc_info=True)

    return sink
