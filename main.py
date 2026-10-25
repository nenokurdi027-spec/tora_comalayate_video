import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from config import BOT_TOKEN
from handlers.start import start, panel_router
from handlers.user_lookup import user_lookup
from handlers.channel_lookup import channel_lookup
from handlers.ip_lookup import ip_lookup

logging.basicConfig(level=logging.INFO)

def build() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(panel_router, pattern=r"^panel:"))

    # route by simple heuristic: @/id → user, t.me → channel, ip → geo
    async def router(update, ctx):
        text = update.message.text.strip()
        import ipaddress
        if text.startswith("t.me/") or text.startswith("https://t.me/"):
            await channel_lookup(update, ctx)
            return
        try:
            ipaddress.ip_address(text)
            await ip_lookup(update, ctx)
            return
        except ValueError:
            pass
        await user_lookup(update, ctx)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router))
    return app

if __name__ == "__main__":
    build().run_polling()
