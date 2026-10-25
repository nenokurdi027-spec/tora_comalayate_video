import asyncio
import os
import re
import shutil
import tempfile
import time
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
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN missing")

WORK_DIR = Path(tempfile.gettempdir()) / "shazbot"
WORK_DIR.mkdir(exist_ok=True)

# دۆخی بەکارهێنەر
PENDING: dict[int, str] = {}
START_TIMES: dict[int, float] = {}

PLATFORM_REGIONS = {
    "tiktok":    [(0.70, 0.02, 0.28, 0.12)],
    "instagram": [(0.00, 0.85, 0.35, 0.15)],
    "facebook":  [(0.25, 0.88, 0.50, 0.12)],
    "snapchat":  [(0.35, 0.02, 0.30, 0.10)],
    "telegram":  [(0.70, 0.88, 0.30, 0.12)],
    "pinterest": [(0.62, 0.85, 0.38, 0.15)],
}

SUPPORTED = {
    "facebook": r"(facebook\.com|fb\.watch)",
    "instagram": r"(instagram\.com|instagr\.am)",
    "telegram": r"(t\.me|telegram\.me)",
    "snapchat": r"(snapchat\.com|snap\.chat)",
    "tiktok": r"(tiktok\.com|vt\.tiktok\.com)",
    "pinterest": r"(pinterest\.com|pin\.it)",
}

# ---------------------------------------------------------
# مێنیوکان
# ---------------------------------------------------------
def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧼 لا بردنی نوسین و لۆگۆ", callback_data="menu:clean")
    kb.button(text="📥 دابەزاندنی سۆشیال میدیا", callback_data="menu:social")
    kb.adjust(1)
    return kb.as_markup()

def social_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟨 سناپچات", callback_data="p:snapchat")
    kb.button(text="🟦 فەیسبوک", callback_data="p:facebook")
    kb.button(text="⬛ تیکتۆک", callback_data="p:tiktok")
    kb.button(text="🟩 تیلیگرام", callback_data="p:telegram")
    kb.button(text="🟪 پێنتەرێست", callback_data="p:pinterest")
    kb.button(text="🟥 ئینستاگرام", callback_data="p:instagram")
    kb.button(text="⬅️ گەڕانەوە", callback_data="menu:main")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()

MENU_TEXT = (
    "<b>بەخێربێیت بۆ Shaz Bot</b> 🦅\n\n"
    "تکایە یەکێک لەم دوو بەشە هەڵبژێرە:\n\n"
    "١. <b>لا بردنی نوسین و لۆگۆ</b> — ڤیدیۆ یان وێنە بنێرە، بە خاوێنی بۆت دەگەڕێنمەوە.\n"
    "٢. <b>دابەزاندنی سۆشیال میدیا</b> — لینکی ڤیدیۆ بنێرە، بە کوالیتی بەرز و بێ لۆگۆ دایدەگرم."
)

# ---------------------------------------------------------
# داگرتنەکان
# ---------------------------------------------------------
def _ydl_opts(outtmpl: str) -> dict:
    return {
        "outtmpl": outtmpl, "format": "bv*+ba/b", "merge_output_format": "mp4",
        "quiet": True, "noprogress": True, "no_warnings": True, "noplaylist": True,
        "socket_timeout": 20, "retries": 2,
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"},
    }

async def dl_tiktok(url: str) -> Path:
    job = WORK_DIR / uuid.uuid4().hex
    job.mkdir()
    api = "https://www.tikwm.com/api/"
    params = {"url": url, "hd": "1"}
    headers = {"User-Agent": "Mozilla/5.0"}
    
    async with aiohttp.ClientSession(headers=headers) as sess:
        async with sess.get(api, params=params, timeout=20) as r:
            data = await r.json()
            
    if data.get("code") != 0 or "data" not in data:
        raise RuntimeError("هەڵە لە داگرتنی تیکتۆک. تکایە دواتر هەوڵ بدەرەوە.")
        
    play_url = data["data"].get("hdplay") or data["data"].get("play")
    if not play_url:
        raise RuntimeError("لینکی ڤیدیۆ نەدۆزرایەوە.")
        
    if play_url.startswith("/"):
        play_url = "https://www.tikwm.com" + play_url
        
    out = job / "tiktok.mp4"
    async with aiohttp.ClientSession() as sess:
        async with sess.get(play_url) as r:
            if r.status != 200:
                raise RuntimeError("هەڵە لە داگرتنی فایلی ڤیدیۆ.")
            with open(out, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 15):
                    f.write(chunk)
    return out

async def dl_ytdlp(url: str, platform: str) -> Path:
    job = WORK_DIR / uuid.uuid4().hex
    job.mkdir()
    outtmpl = str(job / "%(id)s.%(ext)s")

    def _run():
        with yt_dlp.YoutubeDL(_ydl_opts(outtmpl)) as ydl:
            ydl.download([url])

    await asyncio.get_running_loop().run_in_executor(None, _run)
    files = sorted(job.glob("*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError(f"هەڵە لە داگرتنی {platform}")
    return files[0]

async def dl_telegram(url: str) -> Path:
    job = WORK_DIR / uuid.uuid4().hex
    job.mkdir()
    m = re.search(r"t\.me/(?:s/)?([^/]+)/(\d+)", url)
    if not m:
        raise ValueError("لینکی تیلیگرام نادروستە.")
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
        raise RuntimeError("هیچ ڤیدیۆیەک لە پۆستەکەدا نەدۆزرایەوە.")

    ext = ".mp4" if target == (vids[0] if vids else None) else ".jpg"
    out = job / f"tg{msg_id}{ext}"

    async with aiohttp.ClientSession() as sess:
        async with sess.get(target) as r:
            with open(out, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 15):
                    f.write(chunk)
    return out

async def dl_snapchat(url: str) -> Path:
    job = WORK_DIR / uuid.uuid4().hex
    job.mkdir()
    headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"}
    async with aiohttp.ClientSession(headers=headers) as sess:
        async with sess.get(url, allow_redirects=True) as r:
            html = await r.text()
    m = re.search(r'"contentUrl":"([^"]+)"', html)
    if not m:
        m = re.search(r'<video[^>]+src="([^"]+)"', html)
    if not m:
        raise RuntimeError("هیچ ڤیدیۆیەک لە سناپچات نەدۆزرایەوە.")
    src = m.group(1).replace("\\/", "/")
    out = job / "snap.mp4"
    async with aiohttp.ClientSession(headers=headers) as sess:
        async with sess.get(src) as r:
            with open(out, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 15):
                    f.write(chunk)
    return out

# ---------------------------------------------------------
# پاککردنەوە (Scrub)
# ---------------------------------------------------------
async def probe_size(path: Path) -> tuple[int, int]:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        w, h = out.decode().strip().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1920

def build_delogo(regions: list[tuple[float, float, float, float]], w: int, h: int) -> str:
    filters = []
    for fx, fy, fw, fh in regions:
        x = max(0, int(fx * w))
        y = max(0, int(fy * h))
        bw = min(w - x, int(fw * w))
        bh = min(h - y, int(fh * h))
        if bw > 4 and bh > 4:
            filters.append(f"delogo=x={x}:y={y}:w={bw}:h={bh}")
    return ",".join(filters) if filters else ""

async def scrub_media(src: Path, platform: str | None) -> Path:
    dst = src.with_name(f"clean_{src.name}")
    w, h = await probe_size(src)
    regions = PLATFORM_REGIONS.get(platform or "", [])
    vf = build_delogo(regions, w, h)

    if src.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        args = ["ffmpeg", "-y", "-i", str(src)]
        if vf: args += ["-vf", vf]
        args += [str(dst.with_suffix(".png"))]
    else:
        args = ["ffmpeg", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy"]
        if vf: args[3:3] = ["-vf", vf]
        args += [str(dst.with_suffix(".mp4"))]

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        fallback = src.with_name(f"clean_fallback_{src.name}")
        shutil.copy(src, fallback)
        return fallback
    return dst.with_suffix(".mp4") if dst.suffix != ".mp4" else dst

# ---------------------------------------------------------
# هاندلەرەکان
# ---------------------------------------------------------
router = Router()

@router.message(CommandStart())
async def cmd_start(msg: Message):
    await msg.answer(MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_menu())

@router.callback_query(F.data == "menu:main")
async def back_main(cb: CallbackQuery):
    await cb.message.edit_text(MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_menu())
    await cb.answer()

@router.callback_query(F.data == "menu:clean")
async def menu_clean(cb: CallbackQuery):
    PENDING[cb.from_user.id] = "clean"
    await cb.message.edit_text(
        "🧼 <b>لا بردنی نوسین و لۆگۆ</b>\n\n"
        "تکایە ئێستا ڤیدیۆ یان وێنەکەت بنێرە. بە خاوێنی و بێ هیچ لۆگۆیەک بۆت دەگەڕێنمەوە.",
        parse_mode=ParseMode.HTML
    )
    await cb.answer()

@router.callback_query(F.data == "menu:social")
async def menu_social(cb: CallbackQuery):
    await cb.message.edit_text(
        "📥 <b>دابەزاندنی سۆشیال میدیا</b>\n\n"
        "تکایە پلاتفۆرمێک هەڵبژێرە:",
        parse_mode=ParseMode.HTML,
        reply_markup=social_menu()
    )
    await cb.answer()

@router.callback_query(F.data.startswith("p:"))
async def pick_platform(cb: CallbackQuery):
    platform = cb.data.split(":", 1)[1]
    names = {
        "facebook": "فەیسبوک", "instagram": "ئینستاگرام", 
        "telegram": "تیلیگرام", "snapchat": "سناپچات", 
        "tiktok": "تیکتۆک", "pinterest": "پێنتەرێست"
    }
    p_name = names.get(platform, platform.title())
    
    PENDING[cb.from_user.id] = platform
    await cb.message.edit_text(
        f"<b>{p_name}</b>\n\n"
        "تکایە لینکی ڤیدیۆکە بنێرە. بە کوالیتی بەرز و بێ لۆگۆ دایدەگرم.",
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()

@router.message(F.document | F.video | F.photo)
async def handle_file(msg: Message):
    platform = PENDING.pop(msg.from_user.id, "clean")
    file = msg.document or msg.video
    if not file and msg.photo:
        file = msg.photo[-1]
    
    tmp = WORK_DIR / uuid.uuid4().hex
    tmp.mkdir()
    suffix = ".mp4"
    if msg.document and msg.document.file_name:
        suffix = Path(msg.document.file_name).suffix or ".bin"
    if msg.photo: suffix = ".jpg"
    src = tmp / f"in{suffix}"

    status = await msg.answer("⏳ وەرگرتن...")
    start = time.time()
    
    await msg.bot.download(file, destination=src)
    await status.edit_text("🧼 پاککردنەوە...")
    try:
        out = await scrub_media(src, None if platform in ("clean", "scrub") else platform)
        
        elapsed = time.time() - start
        caption = f"✅ بە سەرکەوتوویی پاککرایەوە.\n⏱ کاتی بەکارهاتوو: {elapsed:.1f} چرکە"
        
        await msg.answer_document(FSInputFile(out, filename=out.name), caption=caption)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"⚠️ هەڵە: {e}")
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
        await msg.answer("⚠️ تکایە سەرەتا پلاتفۆرمێک لە مێنیوەکە هەڵبژێرە.")
        return
    PENDING.pop(msg.from_user.id, None)
    
    status = await msg.answer("⏳ داگرتن...")
    start = time.time()
    
    try:
        if platform == "telegram":
            src = await dl_telegram(url)
        elif platform == "snapchat":
            src = await dl_snapchat(url)
        elif platform == "tiktok":
            src = await dl_tiktok(url)
        else:
            src = await dl_ytdlp(url, platform)
            
        await status.edit_text("🧼 لابردنی لۆگۆ...")
        out = await scrub_media(src, platform)
        
        elapsed = time.time() - start
        caption = f"✅ بە سەرکەوتوویی دابەزێنرا.\n⏱ کاتی بەکارهاتوو: {elapsed:.1f} چرکە"
        
        await msg.answer_document(FSInputFile(out, filename=out.name), caption=caption)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"⚠️ هەڵە لە داگرتن: {e}")
    finally:
        for p in WORK_DIR.glob("*"):
            if p.is_dir() and p.name != "keep":
                shutil.rmtree(p, ignore_errors=True)

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
