# thin wrapper around Telegram client — all public-data calls live here
from telegram import Bot
from telegram.error import TelegramError

class TelegramRecon:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def resolve_target(self, handle: str):
        """
        Accept @username, bare username, or numeric ID.
        Returns (user_or_chat, kind) where kind is 'user' or 'chat'.
        """
        handle = handle.strip()
        if handle.startswith("@"):
            handle = handle[1:]
        try:
            if handle.isdigit():
                return await self.bot.get_chat(int(handle)), "chat"
            chat = await self.bot.get_chat(f"@{handle}")
            return chat, "user" if chat.type == "private" else "chat"
        except TelegramError as e:
            return None, f"err:{e}"

    async def get_user_full(self, user_id: int):
        try:
            user = await self.bot.get_chat(user_id)
        except TelegramError:
            return None
        return {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "bio": getattr(user, "bio", None),
            "is_bot": user.is_bot,
        }

    async def get_chat_admins(self, chat_id: int):
        try:
            admins = await self.bot.get_chat_administrators(chat_id)
        except TelegramError:
            return []
        out = []
        for a in admins:
            u = a.user
            out.append({
                "id": u.id,
                "username": u.username,
                "name": f"{u.first_name or ''} {u.last_name or ''}".strip(),
                "status": a.status,
            })
        return out
