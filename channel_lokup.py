from telegram import Update
from telegram.ext import ContextTypes
from services.telegram_api import TelegramRecon
from services.storage import append

async def channel_lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    handle = raw.replace("https://t.me/", "").replace("t.me/", "").lstrip("@")
    recon = TelegramRecon(ctx.bot)
    chat, kind = await recon.resolve_target(handle)

    if chat is None:
        await update.message.reply_text(f"not found. {kind}")
        return

    admins = await recon.get_chat_admins(chat.id)
    record = {
        "type": "channel",
        "id": chat.id,
        "title": getattr(chat, "title", None),
        "username": getattr(chat, "username", None),
        "description": getattr(chat, "description", None),
        "member_count": getattr(chat, "member_count", None),
        "admins": admins,
    }
    append(update.effective_user.id, record)

    admin_lines = "\n".join(
        f"  · {a['name']} (@{a['username']}) — {a['status']}" if a['username']
        else f"  · {a['name']} (id:{a['id']}) — {a['status']}"
        for a in admins
    ) or "  · none visible"

    await update.message.reply_text(
        f"channel: {record['title']}\n"
        f"username: @{record['username'] or '—'}\n"
        f"members: {record['member_count'] or '—'}\n"
        f"admins:\n{admin_lines}"
    )
