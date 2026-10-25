from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

START_TEXT = (
    "rabindra bot — recon panel\n\n"
    "١ — full account lookup (username or id)\n"
    "٢ — channel info (username or link)\n"
    "٣ — IP geolocation + map link\n\n"
    "send your target, or tap a button below."
)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("١ · user lookup", callback_data="panel:user")],
        [InlineKeyboardButton("٢ · channel info", callback_data="panel:channel")],
        [InlineKeyboardButton("٣ · ip lookup", callback_data="panel:ip")],
    ])
    await update.message.reply_text(START_TEXT, reply_markup=kb)

async def panel_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    choice = q.data.split(":", 1)[1]
    if choice == "user":
        await q.message.reply_text("send @username or numeric id.")
    elif choice == "channel":
        await q.message.reply_text("send @channel or t.me link.")
    elif choice == "ip":
        await q.message.reply_text("send an ip address.")
