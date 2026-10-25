import ipaddress
from telegram import Update
from telegram.ext import ContextTypes
from services.ip_service import lookup_ip
from services.storage import append

async def ip_lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        await update.message.reply_text("not a valid ip.")
        return

    data = await lookup_ip(raw)
    if "error" in data:
        await update.message.reply_text(f"lookup failed: {data['error']}")
        return

    append(update.effective_user.id, {"type": "ip", **data})

    msg = (
        f"ip: {data['ip']}\n"
        f"city: {data['city']}\n"
        f"region: {data['region']}\n"
        f"country: {data['country']}\n"
        f"org: {data['org']}\n"
    )
    if data["maps_link"]:
        msg += f"\nmap: {data['maps_link']}"
    await update.message.reply_text(msg)
