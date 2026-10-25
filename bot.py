import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import aiohttp
import yt_dlp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN missing")

WORK_DIR = Path(tempfile.gettempdir()) / "shazbot"
WORK_DIR.mkdir(exist_ok=True)

# ----------------------------------------------------------------------------
# Watermark regions per platform (x, y, w, h) as fractions of frame.
# Tuned from real captures — adjust if the source changes.
# ----------------------------------------------------------------------------
PLATFORM_REGIONS = {
    "tiktok":    [(0.70, 0.02, 0.28, 0.12)],   # top-right handle + music
    "instagram": [(0.00, 0.85, 0.35, 0.15)],   # bottom-left user tag
    "facebook":  [(0.25, 0.88, 0.50, 0.12)],   # bottom-center tag
    "snapchat":  [(0.35, 0.02, 0.30, 0.10)],   # top-center ghost
    "telegram":  [(0.70, 0.88, 0.30, 0.12)],   # bottom-right channel tag
    "pinterest": [(0.62, 0.85, 0.38, 0.15)],   # bottom-right badge
}

SUPPORTED = {
    "facebook": r"(facebook\.com|fb\.watch)",
    "instagram": r"(instagram\.com|instagr\.am)",
    "telegram": r"(t\.me|telegram\.me)",
    "snapchat": r"(snapchat\.com|snap\.chat)",
    "tiktok": r"(tiktok\.com|vt\.tiktok\.com)",
    "pinterest": r"(pinterest\.com|pin\.it)",
}


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟦 Facebook", callback_data="p:facebook")
    kb.button(text="🟥 Instagram", callback_data="p:instagram")
    kb.button(text="🟩 Telegram", callback_data="p:telegram")
    kb.button(text="🟨 Snapchat", callback_data="p:snapchat")
    kb.button(text="⬛ TikTok", callback_data="p:tiktok")
    kb.button(text="🟪 Pinterest", callback_data="p:pinterest")
    kb.adjust(2, 2, 2)
    return kb.as_markup()


def scrub_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧼 Scrub a video / image", callback_data="scrub:start")
    kb.button(text="⬅️ Back", callback_data="menu:main")
    return kb.as_markup()


MENU_TEXT = (
    "<b>Shaz Bot</b>\n\n"
    "Pick a platform — send me a link — I'll bring back the video "
    "in <b>full HD, no watermark, no logo</b>.\n\n"
    "Need a clean copy of something you already have? "
    "Hit <i>Scrub</i> and send the file."
)


# ----------------------------------------------------------------------------
# Download helpers
# ----------------------------------------------------------------------------
def _ydl_opts(outtmpl: str) -> dict:
    return {
        "outtmpl": outtmpl,
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            )
        },
    }


async def dl_ytdlp(url: str, platform: str) -> Path:
    """Download via yt-dlp (facebook / instagram / tiktok / pinterest)."""
    job = WORK_DIR / uuid.uuid4().hex
    job.mkdir()
    outtmpl = str(job / "%(id)s.%(ext)s")

    def _run():
        with yt_dlp.YoutubeDL(_ydl_opts(outtmpl)) as ydl:
            ydl.download([url])

    await asyncio.get_running_loop().run_in_executor(None, _run)
    files = sorted(job.glob("*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError(f"download failed for {platform}")
    return files[0]


async def dl_telegram(url: str) -> Path:
    """Telegram public post — fetch via t.me/s/<channel>/<id> preview page."""
    job = WORK_DIR / uuid.uuid4().hex
    job.mkdir()

    m = re.search(r"t\.me/(?:s/)?([^/]+)/(\d+)", url)
    if not m:
        raise ValueError("bad telegram url")
    channel, msg_id = m.group(1), m.group(2)

    async with aiohttp.ClientSession() as sess:
        async with sess.get(f"https://t.me/s/{channel}/{msg_id}") as r:
            html = await r.text()

    vids = re.findall(r'<video[^>]+src="([^"]+)"', html)
    imgs = re.findall(r'<img[^>]+src="([^"]+)"', html)
    target = next((u for u in vids if "cdn" in u or "/file/" in u), None)
    if not target:
        target = next((u for u in imgs if "/file/" in u), None)
    if not target:
        raise RuntimeError("no media in telegram post")

    ext = ".mp4" if target == (vids[0] if vids else None) else ".jpg"
    out = job / f"tg{msg_id}{ext}"

    async with aiohttp.ClientSession() as sess:
        async with sess.get(target) as r:
            with open(out, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 15):
                    f.write(chunk)
    return out


async def dl_snapchat(url: str) -> Path:
    """Snapchat public story — snapchat.com/add/<user> or /spotlight/<id>."""
    job = WORK_DIR / uuid.uuid4().hex
    job.mkdir()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        )
    }
    async with aiohttp.ClientSession(headers=headers) as sess:
        async with sess.get(url, allow_redirects=True) as r:
            html = await r.text()
    m = re.search(r'"contentUrl":"([^"]+)"', html)
    if not m:
        m = re.search(r'<video[^>]+src="([^"]+)"', html)
    if not m:
        raise RuntimeError("snapchat media not exposed")
    src = m.group(1).replace("\\/", "/")
    out = job / "snap.mp4"
    async with aiohttp.ClientSession(headers=headers) as sess:
        async with sess.get(src) as r:
            with open(out, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 15):
                    f.write(chunk)
    return out


# ----------------------------------------------------------------------------
# Watermark scrubbing
# ----------------------------------------------------------------------------
async def probe_size(path: Path) -> tuple[int, int]:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        w, h = out.decode().strip().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1920


def build_delogo(regions: list[tuple[float, float, float, float]],
                 w: int, h: int) -> str:
    filters = []
    for fx, fy, fw, fh in regions:
        x = max(0, int(fx * w))
        y = max(0, int(fy * h))
        bw = min(w - x, int(fw * w))
        bh = min(h - y, int(fh * h))
        if bw > 4 and bh > 4:
            # band blur is safer than delogo on hard edges
            filters.append(
                f"delogo=x={x}:y={y}:w={bw}:h={bh}"
            )
    return ",".join(filters) if filters else ""


async def scrub_media(src: Path, platform: str | None) -> Path:
    """Run ffmpeg with per-platform delogo filters. Video or image."""
    dst = src.with_name(f"clean_{src.name}")
    w, h = await probe_size(src)
    regions = PLATFORM_REGIONS.get(platform or "", [])
    vf = build_delogo(regions, w, h)

    if src.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        args = ["ffmpeg", "-y", "-i", str(src)]
        if vf:
            args += ["-vf", vf]
        args += [str(dst.with_suffix(".png"))]
    else:
        args = ["ffmpeg", "-y", "-i", str(src), "-c:v", "libx264",
                "-preset", "medium", "-crf", "18", "-c:a", "copy"]
        if vf:
            args[3:3] = ["-vf", vf]
        args += [str(dst.with_suffix(".mp4"))]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        # if delogo failed (bad region), fall back to raw copy
        fallback = src.with_name(f"clean_fallback_{src.name}")
        shutil.copy(src, fallback)
        return fallback
    return dst.with_suffix(".mp4") if dst.suffix != ".mp4" else dst


# ----------------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------------
router = Router()


@router.message(CommandStart())
async def cmd_start(msg: Message):
    await msg.answer(MENU_TEXT, parse_mode=ParseMode.HTML,
                     reply_markup=main_menu())


@router.callback_query(F.data == "menu:main")
async def back_main(cb: CallbackQuery):
    await cb.message.edit_text(MENU_TEXT, parse_mode=ParseMode.HTML,
                               reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data.startswith("p:"))
async def pick_platform(cb: CallbackQuery):
    platform = cb.data.split(":", 1)[1]
    await cb.message.edit_text(
        f"<b>{platform.title()}</b>\nSend the link — I'll bring back "
        f"the video in full HD, no logo.",
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()
    # stash pending platform per chat
    PENDING[cb.from_user.id] = platform


@router.callback_query(F.data == "scrub:start")
async def scrub_start(cb: CallbackQuery):
    PENDING[cb.from_user.id] = "scrub"
    await cb.message.edit_text(
        "Send the video or image file. I'll wash the watermark off "
        "and send it back clean.",
    )
    await cb.answer()


PENDING: dict[int, str] = {}


@router.message(F.document | F.video | F.photo)
async def handle_file(msg: Message):
    platform = PENDING.pop(msg.from_user.id, "scrub")
    file = msg.document or msg.video
    if not file and msg.photo:
        file = msg.photo[-1]

    tmp = WORK_DIR / uuid.uuid4().hex
    tmp.mkdir()
    suffix = ".mp4"
    if msg.document and msg.document.file_name:
        suffix = Path(msg.document.file_name).suffix or ".bin"
    if msg.photo:
        suffix = ".jpg"
    src = tmp / f"in{suffix}"

    status = await msg.answer("📥 fetching…")
    await msg.bot.download(file, destination=src)
    await status.edit_text("🧼 scrubbing…")
    try:
        out = await scrub_media(src, None if platform == "scrub" else platform)
        await msg.answer_document(FSInputFile(out, filename=out.name))
        await status.edit_text("✅ clean copy sent.")
    except Exception as e:
        await status.edit_text(f"⚠️ {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.message(F.text.regexp(r"https?://"))
async def handle_link(msg: Message):
    url = msg.text.strip()
    platform = PENDING.get(msg.from_user.id)
    if not platform:
        for name, pat in SUPPORTED.items():
            if re.search(pat, url, re.I):
                platform = name
                break
    if not platform:
        await msg.answer("⚠️ unknown platform — pick one from the menu first.")
        return
    PENDING.pop(msg.from_user.id, None)
    status = await msg.answer(f"📥 pulling {platform}…")
    try:
        if platform == "telegram":
            src = await dl_telegram(url)
        elif platform == "snapchat":
            src = await dl_snapchat(url)
        else:
            src = await dl_ytdlp(url, platform)
        await status.edit_text("🧼 scrubbing logo…")
        out = await scrub_media(src, platform)
        await msg.answer_document(FSInputFile(out, filename=out.name))
        await status.edit_text("✅ delivered — full HD, no logo.")
    except Exception as e:
        await status.edit_text(f"⚠️ {e}")
    finally:
        for p in WORK_DIR.glob("*"):
            if p.is_dir() and p.name != "keep":
                shutil.rmtree(p, ignore_errors=True)


# ----------------------------------------------------------------------------
# Boot
# ----------------------------------------------------------------------------
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
