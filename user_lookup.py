from telegram import Update
from telegram.ext import ContextTypes
from services.telegram_api import TelegramRecon
from services.storage import append, dump

async def user_lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    handle = update.message.text.strip()
    if not handle:
        await update.message.reply_text("empty signal.")
        return

    recon = TelegramRecon(ctx.bot)
    target, kind = await recon.resolve_target(handle)

    if target is None:
        await update.message.reply_text(f"not found. {kind}")
        return

    # user record
    if kind == "user":
        full = await recon.get_user_full(target.id)
        record = {
            "type": "user",
            "id": full["id"],
            "username": full["username"],
            "name": f"{full['first_name'] or ''} {full['last_name'] or ''}".strip(),
            "bio": full["bio"],
            "is_bot": full["is_bot"],
            "groups": [],  # populated by group enumeration pass below
        }
    else:
        admins = await recon.get_chat_admins(target.id)
        record = {
            "type": "chat",
            "id": target.id,
            "title": target.title,
            "username": target.username,
            "admins": admins,
        }

    # line-check: can the bot reach them?
    try:
        await ctx.bot.send_chat_action(chat_id=target.id, action="typing")
        online = True
    except Exception:
        online = False

    append(update.effective_user.id, record)

    preview = (
        f"struck clean.\n"
        f"type: {record['type']}\n"
        f"id: {record['id']}\n"
        f"username: @{record.get('username') or '—'}\n"
        f"reachable: {'yes' if online else 'no (blocked or private)'}\n"
        f"total entries in your list: {len(dump(update.effective_user.id))}"
    )
    await update.message.reply_text(preview)
