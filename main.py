import os
import logging
import ipaddress
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import TelegramError

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "")

logging.basicConfig(level=logging.INFO)

# ================= STORAGE =================
user_sessions = {}

def add_to_list(user_id, data):
    if user_id not in user_sessions:
        user_sessions[user_id] = []
    user_sessions[user_id].append(data)

def get_list(user_id):
    return user_sessions.get(user_id, [])

# ================= IP SERVICE =================
async def lookup_ip(ip: str) -> dict:
    url = f"https://ipinfo.io/{ip}/json"
    if IPINFO_TOKEN:
        url += f"?token={IPINFO_TOKEN}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=10) as r:
            if r.status != 200:
                return {"error": f"http {r.status}"}
            data = await r.json()
    loc = data.get("loc", "")
    maps = f"https://www.google.com/maps?q={loc}" if loc else None
    return {
        "ip": ip, 
        "city": data.get("city"), 
        "region": data.get("region"),
        "country": data.get("country"), 
        "org": data.get("org"), 
        "maps_link": maps,
    }

# ================= START & MENU =================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("١ · دۆزینەوەی یوزەر", callback_data="panel:user")],
        [InlineKeyboardButton("٢ · زانیاری چەناڵ", callback_data="panel:channel")],
        [InlineKeyboardButton("٣ · دۆزینەوەی ئایپی", callback_data="panel:ip")],
    ])
    text = (
        "سڵاو، بەخێربێی بۆ بۆتی راویندرا.\n\n"
        "تکایە یەکێک لەم بژاردەیانە هەڵبژێرە:\n"
        "١. دۆزینەوەی زانیاری یوزەر\n"
        "٢. دۆزینەوەی زانیاری چەناڵ\n"
        "٣. دۆزینەوەی شوێنی ئایپی"
    )
    await update.message.reply_text(text, reply_markup=kb)

async def panel_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    choice = q.data.split(":", 1)[1]
    if choice == "user":
        await q.message.reply_text("تکایە یوزەرنەیم (@username) یان ئایدی (ID) بنێرە.")
    elif choice == "channel":
        await q.message.reply_text("تکایە لینکی چەناڵ یان @username بنێرە.")
    elif choice == "ip":
        await q.message.reply_text("تکایە ئایپییەک (IP Address) بنێرە.")

# ================= USER LOOKUP =================
async def user_lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE, handle: str):
    handle = handle.strip().lstrip("@")
    try:
        if handle.isdigit():
            target = await ctx.bot.get_chat(int(handle))
        else:
            target = await ctx.bot.get_chat(f"@{handle}")
    except TelegramError as e:
        await update.message.reply_text(f"نەدۆزرایەوە. هەڵە: {e}")
        return

    record = {
        "type": "user" if target.type == "private" else "chat",
        "id": target.id,
        "username": getattr(target, "username", None),
        "first_name": getattr(target, "first_name", None),
        "last_name": getattr(target, "last_name", None),
        "bio": getattr(target, "bio", None),
    }

    # Check if reachable (not blocked)
    try:
        await ctx.bot.send_chat_action(chat_id=target.id, action="typing")
        online = "بەڵێ (لە خەتە)"
    except Exception:
        online = "نەخێر (قوفڵی کردووە یان پرایڤەتە)"

    add_to_list(update.effective_user.id, record)
    
    name = f"{record['first_name'] or ''} {record['last_name'] or ''}".strip()
    preview = (
        f"✅ زانیاری دۆزرایەوە:\n\n"
        f"👤 ناو: {name}\n"
        f"🆔 ئایدی: {record['id']}\n"
        f"📧 یوزەرنەیم: @{record['username'] or 'نییە'}\n"
        f"📝 بایۆ: {record['bio'] or 'نییە'}\n"
        f"📶 لە خەتە: {online}\n\n"
        f"📊 کۆی گشتی زانیارییەکان لە لیستەکەت: {len(get_list(update.effective_user.id))}"
    )
    await update.message.reply_text(preview)

# ================= CHANNEL LOOKUP =================
async def channel_lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE, raw: str):
    handle = raw.replace("https://t.me/", "").replace("t.me/", "").lstrip("@")
    try:
        chat = await ctx.bot.get_chat(f"@{handle}")
    except TelegramError as e:
        await update.message.reply_text(f"نەدۆزرایەوە. هەڵە: {e}")
        return

    try:
        admins_list = await ctx.bot.get_chat_administrators(chat.id)
    except TelegramError:
        admins_list = []

    admins = []
    for a in admins_list:
        u = a.user
        admins.append({
            "id": u.id, 
            "username": u.username, 
            "name": f"{u.first_name or ''} {u.last_name or ''}".strip(), 
            "status": a.status
        })

    record = {
        "type": "channel", 
        "id": chat.id, 
        "title": getattr(chat, "title", None),
        "username": getattr(chat, "username", None), 
        "member_count": getattr(chat, "member_count", None),
        "admins": admins,
    }
    add_to_list(update.effective_user.id, record)

    admin_lines = "\n".join(
        f"  · {a['name']} (@{a['username']}) — {a['status']}" if a['username'] else f"  · {a['name']} (ID: {a['id']}) — {a['status']}"
        for a in admins
    ) or "  · هیچ ئەدمینێک نەبینرا"

    await update.message.reply_text(
        f"📢 زانیاری چەناڵ:\n\n"
        f"ناو: {record['title']}\n"
        f"یوزەرنەیم: @{record['username'] or 'نییە'}\n"
        f"ئەندامان: {record['member_count'] or 'نەزانراو'}\n\n"
        f"👑 ئەدمینەکان:\n{admin_lines}"
    )

# ================= IP LOOKUP =================
async def ip_lookup_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE, raw: str):
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        await update.message.reply_text("ئەمە ئایپییەکی دروست نییە. تکایە ئایپییەکی ڕاست بنێرە.")
        return

    data = await lookup_ip(raw)
    if "error" in data:
        await update.message.reply_text(f"هەڵە لە دۆزینەوەدا: {data['error']}")
        return

    add_to_list(update.effective_user.id, {"type": "ip", **data})

    msg = (
        f"🌐 زانیاری ئایپی:\n\n"
        f"IP: {data['ip']}\n"
        f"شار: {data['city'] or 'نەزانراو'}\n"
        f"هەرێم: {data['region'] or 'نەزانراو'}\n"
        f"وڵات: {data['country'] or 'نەزانراو'}\n"
        f"کۆمپانیا: {data['org'] or 'نەزانراو'}\n"
    )
    if data["maps_link"]:
        msg += f"\n📍 لینکی نەخشە بۆ شوێنەکە:\n{data['maps_link']}"
    
    await update.message.reply_text(msg)

# ================= ROUTER =================
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("t.me/") or text.startswith("https://t.me/"):
        await channel_lookup(update, ctx, text)
        return
    try:
        ipaddress.ip_address(text)
        await ip_lookup_handler(update, ctx, text)
        return
    except ValueError:
        pass
    await user_lookup(update, ctx, text)

# ================= MAIN =================
def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is missing!")
        return
        
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(panel_router, pattern=r"^panel:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
