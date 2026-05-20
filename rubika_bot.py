from __future__ import annotations

"""
rubika_bot.py — ربات روبیکا
"""

import asyncio
import os
import shutil
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from downloader import (
    DownloadError,
    download_and_prepare,
    extract_package_name,
    is_google_play_url,
)
from url_downloader import download_url, is_direct_url, URLDownloadError
from rubika_uploader import make_file_inline, _guess_file_type  # noqa: F401

load_dotenv()

# ─── تنظیمات ─────────────────────────────────────────────────────────────────

RUBIKA_SESSION = os.getenv("RUBIKA_SESSION", "rubsession").strip() or "rubsession"
PLAY_ARCH = os.getenv("PLAY_ARCH", "arm64").strip() or "arm64"
_raw_dl = os.getenv("DOWNLOAD_DIR", "downloads").strip() or "downloads"
DOWNLOAD_DIR = Path(_raw_dl) / "rub"
APKEDITOR_JAR = Path(os.getenv("APKEDITOR_JAR", "tools/APKEditor.jar"))
BASE_DIR = Path(__file__).resolve().parent

API_ID_RAW = os.getenv("API_ID", "").strip()
try:
    API_ID = int(API_ID_RAW) if API_ID_RAW else 0
except ValueError:
    API_ID = 0

API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

_owner_raw = os.getenv("OWNER_TELEGRAM_ID", "").strip()
try:
    OWNER_TELEGRAM_ID = int(_owner_raw) if _owner_raw else 0
except ValueError:
    OWNER_TELEGRAM_ID = 0

MAX_CONCURRENT = 2
_semaphore: asyncio.Semaphore | None = None

def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore

def _session_exists() -> bool:
    base = BASE_DIR / RUBIKA_SESSION
    candidates = [
        base, base.with_suffix(".rp"), base.with_suffix(".session"),
        base.with_suffix(".sqlite"), Path(RUBIKA_SESSION),
        Path(RUBIKA_SESSION).with_suffix(".rp"),
    ]
    return any(p.exists() for p in candidates)

# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_file_inline(uploaded, file_type: str = "File") -> dict:
    if isinstance(uploaded, dict):
        payload = dict(uploaded)
    else:
        raw = getattr(uploaded, "to_dict", None)
        if callable(raw): raw = raw()
        payload = dict(raw) if isinstance(raw, dict) else {}
        if not payload:
            for attr in ("file_id", "dc_id", "access_hash_rec", "file_name", "size", "mime", "thumb_inline"):
                val = getattr(uploaded, attr, None)
                if val is not None: payload[attr] = val
    payload.setdefault("type", file_type)
    payload.setdefault("time", 1)
    payload.setdefault("width", 0)
    payload.setdefault("height", 0)
    payload.setdefault("music_performer", "")
    payload.setdefault("is_spoil", False)
    return payload

def _guess_rubika_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"): return "Video"
    if ext in (".mp3", ".ogg", ".flac", ".aac", ".wav", ".m4a", ".opus"): return "Music"
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"): return "Image"
    return "File"

async def _safe_send(client, object_guid: str, text: str, reply_to: int | None = None) -> int | None:
    try:
        kwargs: dict = {"object_guid": object_guid, "text": text}
        if reply_to is not None: kwargs["reply_to_message_id"] = reply_to
        result = await client.send_message(**kwargs)
        msg_id = getattr(result, "message_id", None) or (result.get("message_id") if isinstance(result, dict) else None)
        return int(msg_id) if msg_id else None
    except Exception as exc:
        print(f"[rubika] ⚠️  ارسال پیام ناموفق: {type(exc).__name__}: {exc}")
        return None

async def _safe_edit(client, object_guid: str, message_id: int, text: str) -> None:
    try: await client.edit_message(object_guid=object_guid, message_id=message_id, text=text)
    except Exception: pass

async def _safe_delete(client, object_guid: str, message_id: int) -> None:
    try: await client.delete_messages(object_guid=object_guid, message_ids=[message_id])
    except Exception: pass

def _parse_update(update) -> tuple[str, str | None, int | None]:
    text, object_guid, message_id = "", None, None
    if isinstance(update, dict):
        text = str(update.get("text") or "")
        object_guid = update.get("object_guid")
        try: message_id = int(update["message_id"])
        except: pass
        return text, object_guid, message_id

    if hasattr(update, "text") and update.text: text = str(update.text)
    if hasattr(update, "object_guid") and update.object_guid: object_guid = str(update.object_guid)
    if hasattr(update, "message_id") and update.message_id is not None:
        try: message_id = int(update.message_id)
        except: pass
    return text, object_guid, message_id

def _get_file_inline(update) -> dict | None:
    if isinstance(update, dict): return update.get("file_inline")
    return getattr(update, "file_inline", None)

# ─── آپلود به تلگرام ─────────────────────────────────────────────────────────

async def _upload_to_telegram(file_path: Path, caption: str = "") -> bool:
    if not all([API_ID, API_HASH, BOT_TOKEN, OWNER_TELEGRAM_ID]):
        print("[rubika] ⚠️  برای ارسال به تلگرام مقادیر .env تکمیل نیست.")
        return False
    try:
        from pyrogram import Client as TGClient
        async with TGClient("rub_to_tg_sender", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN) as tg:
            await tg.send_document(chat_id=OWNER_TELEGRAM_ID, document=str(file_path), file_name=file_path.name, caption=caption)
        return True
    except Exception as exc:
        print(f"[rubika] ❌ ارسال به تلگرام ناموفق: {type(exc).__name__}: {exc}")
        return False

# ─── پایپلاین‌ها ─────────────────────────────────────────────────────────────

async def _process_play_link(client, object_guid: str, original_msg_id: int | None, package: str, send_to_telegram: bool = False) -> None:
    job_id = uuid.uuid4().hex[:8]
    job_dir = DOWNLOAD_DIR / job_id
    status_id = await _safe_send(client, object_guid, f"📦 دانلود شروع شد\n\n📱 {package}\n🆔 {job_id}", reply_to=original_msg_id)
    _prev_text = [""]

    async def update_status(text: str) -> None:
        full = f"{text}\n\n🆔 {job_id}"
        if full == _prev_text[0] or status_id is None: return
        _prev_text[0] = full
        await _safe_edit(client, object_guid, status_id, full)

    try:
        async with _sem():
            apk_path = await download_and_prepare(package=package, job_dir=job_dir, apkeditor_jar=APKEDITOR_JAR, arch=PLAY_ARCH, progress_callback=update_status)
        caption = f"✅ آماده شد!\n📱 {package}\n📁 {apk_path.name}"
        if send_to_telegram:
            await update_status(f"⬆️ ارسال به تلگرام...")
            if await _upload_to_telegram(apk_path, caption): await _safe_edit(client, object_guid, status_id, f"✅ ارسال به تلگرام انجام شد!\n📱 {package}")
            else: await update_status(f"❌ ارسال به تلگرام ناموفق بود.")
        else:
            await _upload_to_rubika(client, object_guid, apk_path, caption, original_msg_id, status_id, update_status)
    except Exception as exc:
        await update_status(f"❌ خطا:\n{str(exc)[:300]}")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)

async def _process_url(client, object_guid: str, original_msg_id: int | None, url: str, send_to_telegram: bool = False) -> None:
    job_id = uuid.uuid4().hex[:8]
    job_dir = DOWNLOAD_DIR / job_id
    status_id = await _safe_send(client, object_guid, f"🔗 دانلود لینک\n\n🌐 {url[:50]}...\n🆔 {job_id}", reply_to=original_msg_id)
    _prev_text = [""]

    async def update_status(text: str) -> None:
        full = f"{text}\n\n🆔 {job_id}"
        if full == _prev_text[0] or status_id is None: return
        _prev_text[0] = full
        await _safe_edit(client, object_guid, status_id, full)

    try:
        async with _sem(): file_path = await download_url(url, job_dir, update_status)
        caption = f"✅ دانلود تموم شد!\n📁 {file_path.name}"
        if send_to_telegram:
            await update_status(f"⬆️ ارسال به تلگرام...")
            if await _upload_to_telegram(file_path, caption): await _safe_edit(client, object_guid, status_id, f"✅ ارسال به تلگرام انجام شد!\n📁 {file_path.name}")
            else: await update_status("❌ ارسال به تلگرام ناموفق بود.")
        else:
            await _upload_to_rubika(client, object_guid, file_path, caption, original_msg_id, status_id, update_status)
    except Exception as exc:
        await update_status(f"❌ خطا:\n{str(exc)[:300]}")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)

async def _process_received_file(client, object_guid: str, original_msg_id: int | None, file_inline: dict, send_to_telegram: bool = False) -> None:
    job_id = uuid.uuid4().hex[:8]
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    file_name = (file_inline.get("file_name") if isinstance(file_inline, dict) else getattr(file_inline, "file_name", None)) or f"file_{job_id}"
    status_id = await _safe_send(client, object_guid, f"📥 دریافت فایل...\n\n📁 {file_name}\n🆔 {job_id}", reply_to=original_msg_id)
    _prev_text = [""]

    async def update_status(text: str) -> None:
        full = f"{text}\n\n🆔 {job_id}"
        if full == _prev_text[0] or status_id is None: return
        _prev_text[0] = full
        await _safe_edit(client, object_guid, status_id, full)

    try:
        dest_path = job_dir / file_name
        try:
            downloaded = await client.download(file_inline=file_inline, save_as=str(dest_path))
            if downloaded: dest_path = Path(downloaded)
        except:
            try:
                result = await client.download(file_inline=file_inline)
                if isinstance(result, bytes): dest_path.write_bytes(result)
                elif isinstance(result, (str, Path)): dest_path = Path(result)
            except Exception as e: raise RuntimeError("دانلود از روبیکا ناموفق بود.") from e

        if not dest_path.exists() or dest_path.stat().st_size == 0:
            await update_status("❌ دانلود فایل از روبیکا ناموفق بود.")
            return

        caption = f"📁 {dest_path.name}"
        if send_to_telegram:
            await update_status(f"⬆️ ارسال به تلگرام...")
            if await _upload_to_telegram(dest_path, caption): await _safe_edit(client, object_guid, status_id, f"✅ ارسال به تلگرام انجام شد!\n📁 {dest_path.name}")
            else: await update_status("❌ ارسال به تلگرام ناموفق بود.")
        else:
            await _upload_to_rubika(client, object_guid, dest_path, caption, original_msg_id, status_id, update_status)
    except Exception as exc:
        await update_status(f"❌ خطا:\n{str(exc)[:300]}")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)

async def _upload_to_rubika(client, object_guid: str, file_path: Path, caption: str, reply_to: int | None, status_id: int | None, update_status) -> None:
    file_type = _guess_rubika_file_type(file_path.name)
    _last_pct, _last_ts, _start_ts = [-1], [0.0], time.monotonic()

    async def upload_progress(total: int, current: int) -> None:
        if total <= 0: return
        pct = min(99, max(0, int((current * 100) / total)))
        now = time.monotonic()
        if pct - _last_pct[0] < 10 and now - _last_ts[0] < 3.0: return
        _last_pct[0] = pct
        _last_ts[0] = now
        await update_status(f"⬆️ آپلود به روبیکا...\n📁 {file_path.name}\n📊 {pct}%")

    await update_status(f"⬆️ آپلود به روبیکا...\n📁 {file_path.name}")
    uploaded = await client.upload(str(file_path), file_name=file_path.name, callback=upload_progress)
    file_inline = _make_file_inline(uploaded, file_type)
    
    kwargs = {"object_guid": object_guid, "text": caption, "file_inline": file_inline}
    if reply_to is not None: kwargs["reply_to_message_id"] = reply_to
    await client.send_message(**kwargs)
    if status_id is not None: await _safe_delete(client, object_guid, status_id)

# ─── اجرای اصلی، بدون هک دستی Loop ──────────────────────────────────────────

def run_rubika_bot() -> None:
    # 🌟 ثبت دستی و تمیز Event Loop در روبیکا برای پایتون ۳.۱۲
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if not _session_exists():
        print(
            "\n[rubika] ⚠️  Session روبیکا پیدا نشد.\n"
            "  ۱. ربات تلگرام رو باز کن\n"
            "  ۲. /set_rubika رو اجرا کن\n"
            "  ۳. مراحل ورود رو کامل کن\n"
            "  این پروسه صبر می‌کنه تا session ساخته بشه...\n"
        )
        import time as _t
        while not _session_exists():
            _t.sleep(8)
        print("[rubika] ✅ Session پیدا شد. شروع به کار...")

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    from rubpy import Client
    client = Client(name=RUBIKA_SESSION)

    @client.on_message_updates()
    async def on_message(update) -> None:
        text, object_guid, message_id = _parse_update(update)
        if not object_guid: return
        text_clean = text.strip()
        send_to_tg = False

        if text_clean.lower().startswith("/telegram"):
            send_to_tg = True
            text_clean = text_clean[len("/telegram"):].strip()
            if not text_clean:
                await _safe_send(client, object_guid, "📱 حالت ارسال به تلگرام فعال شد.\n\nلینک یا فایل رو با /telegram شروع کن.", reply_to=message_id)
                return

        file_inline = _get_file_inline(update)
        if file_inline and not text_clean:
            asyncio.create_task(_process_received_file(client, object_guid, message_id, file_inline, send_to_tg))
            return

        if is_google_play_url(text_clean):
            package = extract_package_name(text_clean)
            if package: asyncio.create_task(_process_play_link(client, object_guid, message_id, package, send_to_tg))
            else: await _safe_send(client, object_guid, "❌ خطا در استخراج پکیج.", reply_to=message_id)
            return

        if is_direct_url(text_clean):
            asyncio.create_task(_process_url(client, object_guid, message_id, text_clean, send_to_tg))
            return

        lower = text_clean.lower()
        if lower in ("/start", "start", "سلام", "hi"):
            await _safe_send(client, object_guid, "سلام! 👋\nلینک گوگل پلی، لینک مستقیم یا فایل بفرست.\nبرای راهنما /help رو بزن.", reply_to=message_id)
            return
        if lower in ("/help", "help", "راهنما"):
            await _safe_send(client, object_guid, "📖 راهنما\n• فایل بفرست تا آپلود بشه\n• با /telegram میتونی به تلگرام بفرستی\n• با /myid آیدی خودت رو بگیر", reply_to=message_id)
            return
        if lower in ("/myid", "myid"):
            await _safe_send(client, object_guid, f"🆔 GUID شما:\n{object_guid}\n\nدر ربات تلگرام با /set_dest وارد کن.", reply_to=message_id)
            return

    print("[rubika] ✅ ربات روبیکا شروع به کار کرد.")
    # اجرای بومی، مدیریت کامل Loop بر عهده خود rubpy
    client.run()

if __name__ == "__main__":
    run_rubika_bot()
