# -*- coding: utf-8 -*-
from __future__ import annotations

"""
telegram_bot.py - ربات تلگرام با سیستم لاگینگ پیشرفته و فشرده سازی هوشمند
"""

import asyncio
import logging
import os
import random
import shutil
import string
import subprocess
import sys
import uuid
import traceback
import time
from html import escape
from pathlib import Path

# فیکس حیاتی انکودینگ لینوکس برای جلوگیری از خرابی کاراکترها در ترمینال
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

# فیکس حیاتی Event Loop در پایتون 3.12 (رفع هشدار زرد رنگ)
try:
    _loop = asyncio.get_running_loop()
except RuntimeError:
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

from dotenv import load_dotenv
from pyrogram import Client, enums, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from bootstrap import ensure_bootstrap
from downloader import download_and_prepare, DownloadError, extract_package_name, is_google_play_url
from url_downloader import download_url, is_direct_url, URLDownloadError
from rubika_uploader import RubikaUploadError

# --- تنظیمات لاگینگ ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("telegram_bot")
logging.getLogger("pyrogram").setLevel(logging.WARNING)

# بارگذاری ایمن فایل متغیرهای محیطی
try:
    load_dotenv(encoding="utf-8")
except Exception as e:
    logger.error(f"خطا در خواندن فایل .env: {e}")

# --- تنظیمات اولیه ---

_api_id_raw = os.getenv("API_ID", "").strip()
try:
    API_ID = int(_api_id_raw) if _api_id_raw else 0
except ValueError:
    logger.critical("API_ID در .env باید عدد باشد!")
    sys.exit(1)

API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

_owner_raw = os.getenv("OWNER_TELEGRAM_ID", "").strip()
try:
    OWNER_ID = int(_owner_raw) if _owner_raw else 0
except ValueError:
    OWNER_ID = 0

RUBIKA_SESSION = os.getenv("RUBIKA_SESSION", "rubsession").strip()
PLAY_ARCH = os.getenv("PLAY_ARCH", "arm64").strip()
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
APKEDITOR_JAR = Path(os.getenv("APKEDITOR_JAR", "tools/APKEditor.jar"))
BASE_DIR = Path(__file__).resolve().parent
RUBIKA_AUTH_HELPER = BASE_DIR / "rubika_auth_helper.py"

_DEST_GUID_FILE = BASE_DIR / ".rubika_dest_guid"

MAX_CONCURRENT = 3
_semaphore: asyncio.Semaphore | None = None

# 🌟 فیکس پایداری روبیکا: اجرای یک‌به‌یک برای جلوگیری از تداخل کانکشن‌ها
_rubika_upload_lock: asyncio.Lock | None = None

# 🌟 کلاینت سراسری و ماندگار روبیکا جهت بهینه‌سازی سرعت و دور زدن هندشیک‌های اضافی 🌟
_rubika_client = None

def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore

def _rub_lock() -> asyncio.Lock:
    global _rubika_upload_lock
    if _rubika_upload_lock is None:
        _rubika_upload_lock = asyncio.Lock()
    return _rubika_upload_lock

# وضعیت ها
_active: dict[str, dict] = {}
_modes: dict[int, str] = {}
_auth_states: dict[int, dict] = {}
_user_states: dict[int, str] = {}

# سیستم هوشمند ZIP
_zip_modes: dict[int, str] = {}
_zip_passwords: dict[int, str] = {}

# --- Pyrogram ---

app = Client(
    "walrus_tg",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# --- helpers ---

def _is_owner(user_id: int | None) -> bool:
    if not OWNER_ID: return True
    return bool(user_id and user_id == OWNER_ID)

def _has_rubika_session() -> bool:
    base = BASE_DIR / RUBIKA_SESSION
    return (
        base.with_suffix(".rp").exists()
        or base.with_suffix(".session").exists()
        or base.exists()
        or Path(RUBIKA_SESSION).with_suffix(".rp").exists()
    )

async def get_rubika_client():
    """دریافت یا راه‌اندازی کلاینت ماندگار روبیکا برای جلوگیری از قطع ارتباط"""
    global _rubika_client
    if not _has_rubika_session():
        return None
    if _rubika_client is None:
        try:
            from rubpy import Client as RubikaClient
            _rubika_client = RubikaClient(name=str(BASE_DIR / RUBIKA_SESSION))
            await _rubika_client.start()
            logger.info("سشن ماندگار روبیکا با موفقیت متصل شد.")
        except Exception as e:
            logger.error(f"خطا در راه‌اندازی سشن ماندگار روبیکا: {e}")
            _rubika_client = None
    return _rubika_client

async def reset_rubika_client() -> None:
    """بستن کلاینت قدیمی در صورت تغییر شماره یا سشن"""
    global _rubika_client
    if _rubika_client is not None:
        try:
            await _rubika_client.stop()
        except Exception:
            pass
        _rubika_client = None
        logger.info("سشن قدیمی روبیکا با موفقیت بسته شد.")

def _load_dest_guid() -> str:
    env_guid = os.getenv("RUBIKA_DEST_GUID", "").strip()
    if env_guid: return env_guid
    if _DEST_GUID_FILE.exists():
        try: return _DEST_GUID_FILE.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception: pass
    return ""

def _save_dest_guid(guid: str) -> None:
    try:
        _DEST_GUID_FILE.write_text(guid.strip(), encoding="utf-8", errors="ignore")
        logger.info(f"GUID مقصد ذخیره شد: {guid}")
    except Exception as e:
        logger.error(f"ذخیره GUID ناموفق: {e}")

def _get_mode(user_id: int) -> str:
    return _modes.get(user_id, "rubika")

def _get_zip_mode(user_id: int) -> str:
    return _zip_modes.get(user_id, "auto")

def _get_zip_password(user_id: int) -> str:
    return _zip_passwords.get(user_id, "none")

async def _edit(msg: Message, text: str) -> None:
    try: await msg.edit_text(text, parse_mode=enums.ParseMode.HTML)
    except Exception as e: logger.warning(f"خطا در ویرایش پیام: {e}")

async def _reply(msg: Message, text: str) -> Message:
    return await msg.reply_text(text, parse_mode=enums.ParseMode.HTML)

# --- سیستم فشرده سازی ---

async def _compress_file(file_path: Path, password_mode: str) -> tuple[Path, str]:
    """
    فایل رو به صورت ناهمگام ZIP می‌کنه.
    """
    zip_path = file_path.with_suffix(".zip")
    actual_password = ""

    if password_mode != "none":
        actual_password = password_mode

    # 🌟 استفاده از -0 برای جلوگیری از فشرده‌سازی اضافی و کُندی سرعت 🌟
    cmd = ["zip", "-0", "-j"]
    if actual_password:
        cmd.extend(["-P", actual_password])
    cmd.extend([str(zip_path), str(file_path)])

    logger.info(f"شروع بسته‌بندی سریع ZIP: {file_path.name}")
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if process.returncode == 0 and zip_path.exists():
            file_path.unlink(missing_ok=True)
            return zip_path, actual_password
        else:
            logger.error(f"خطا در زیپ کردن فایل. کد خروج: {process.returncode}")
            return file_path, ""
            
    except Exception as e:
        logger.error(f"خطای کریتیکال در فشرده سازی: {e}")
        return file_path, ""

# --- آپلود به مقصد ---

async def _upload_to_target(
    original_msg: Message,
    status_msg: Message,
    file_path: Path,
    mode: str,
    caption: str,
) -> None:
    user_id = original_msg.from_user.id
    zip_mode = _get_zip_mode(user_id)
    zip_pass = _get_zip_password(user_id)
    
    forbidden_exts = [".apk", ".exe", ".bat"]
    
    # منطق هوشمند تصمیم‌گیری برای فشرده‌سازی
    should_zip = False
    if zip_mode == "always":
        should_zip = True
    elif zip_mode == "auto" and file_path.suffix.lower() in forbidden_exts and mode == "rubika":
        should_zip = True

    if should_zip:
        await _edit(status_msg, f"🗜 <b>در حال بسته‌بندی سریع (تغییر فرمت به ZIP)...</b>\n\nاین کار در کسری از ثانیه انجام شده و باعث عبور از فیلتر روبیکا می شود.")
        new_file_path, applied_pass = await _compress_file(file_path, zip_pass)
        
        if new_file_path != file_path:
            file_path = new_file_path
            # در صورتی که فایل ZIP شده باشد، اطلاعات را به انتهای کپشن اورجینال اضافه می‌کنیم
            caption += "\n\n📦 <b>فایل بسته‌بندی شده است.</b>"
            if applied_pass:
                caption += f"\n🔐 رمز استخراج: <code>{applied_pass}</code>"
            else:
                caption += "\n🔓 بدون رمز."

    size_mb = file_path.stat().st_size / (1024 * 1024)
    logger.info(f"شروع آپلود به {'تلگرام' if mode == 'telegram' else 'روبیکا'} - فایل: {file_path.name}")

    if mode == "telegram":
        await _edit(
            status_msg,
            f"⬆️ <b>در حال ارسال به تلگرام...</b>\n\n"
            f"📁 <code>{escape(file_path.name)}</code>\n"
            f"💾 {size_mb:.1f} MB",
        )
        try:
            await original_msg.reply_document(
                document=str(file_path),
                file_name=file_path.name,
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
            )
            await status_msg.delete()
            logger.info("آپلود در تلگرام با موفقیت انجام شد.")
        except Exception as e:
            logger.error(f"خطا در آپلود تلگرام: {e}")
            await _edit(status_msg, f"❌ <b>خطا در ارسال به تلگرام:</b>\n\n{escape(str(e))}")

    else:
        dest_guid = _load_dest_guid()
        if not dest_guid:
            logger.warning("تلاش برای آپلود به روبیکا اما GUID مقصد تنظیم نشده است.")
            await _edit(
                status_msg,
                "❌ <b>GUID مقصد روبیکا تنظیم نشده!</b>\n\n"
                "با دستور /set_dest GUID رو تنظیم کن.",
            )
            return

        if not _has_rubika_session():
            logger.warning("تلاش برای آپلود به روبیکا اما Session وجود ندارد.")
            await _edit(
                status_msg,
                "❌ <b>Session روبیکا وجود نداره!</b>\n\n"
                "با /set_rubika اول وارد روبیکا بشو.",
            )
            return

        await _edit(status_msg, "⏳ <b>در صف آپلود روبیکا...</b>\n\nفایل آماده است و منتظر خلوت شدن خط آپلود می‌باشد.")

        # 🌟 قفل صف: فایل‌ها یکی‌یکی آپلود می‌شوند تا از قطع ارتباط سرور جلوگیری شود 🌟
        async with _rub_lock():
            max_retries = 5
            file_name = file_path.name
            
            # متغیرهای محلی برای Throttling و جلوگیری از اسپم کردن تلگرام
            _last_pct = -1
            _last_ts = 0.0
            _start_ts = time.monotonic()

            async def progress_cb(total: int, current: int) -> None:
                nonlocal _last_pct, _last_ts, _start_ts
                if total <= 0: return
                pct = min(99, max(0, int((current * 100) / total)))
                now = time.monotonic()
                
                # 🌟 فقط در صورت تغییر ۵ درصدی پیشرفت یا عبور ۳ ثانیه به تلگرام پیام بفرست 🌟
                if pct - _last_pct < 5 and now - _last_ts < 3.0:
                    if pct < 99:
                        return
                        
                _last_pct = pct
                _last_ts = now
                elapsed = now - _start_ts
                speed = current / elapsed if elapsed > 0 else 0
                speed_str = (
                    f"{speed / (1024 * 1024):.1f} MB/s"
                    if speed > 1024 * 1024
                    else f"{speed / 1024:.0f} KB/s"
                )
                await _edit(
                    status_msg,
                    f"⬆️ <b>آپلود به روبیکا...</b>\n\n"
                    f"📁 <code>{escape(file_name)}</code>\n"
                    f"💾 {size_mb:.1f} MB\n"
                    f"📊 {pct}%  •  {speed_str}"
                )

            for attempt in range(1, max_retries + 1):
                try:
                    # دریافت کلاینت سراسری و ماندگار
                    client = await get_rubika_client()
                    if not client:
                        raise RuntimeError("کلاینت روبیکا فعال نیست.")
                    
                    await _edit(status_msg, f"🚀 <b>در حال اتصال و شروع آپلود روبیکا (تلاش {attempt}/{max_retries})...</b>")
                    
                    # تشخیص پسوند فایل برای فرستادن به روبیکا
                    ext = file_path.suffix.lower()
                    if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"):
                        file_type = "Video"
                    elif ext in (".mp3", ".ogg", ".flac", ".aac", ".wav", ".m4a", ".opus"):
                        file_type = "Music"
                    elif ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
                        file_type = "Image"
                    else:
                        file_type = "File"

                    # آپلود در لایه‌ی اصلی بدون مسدود کردن تردها
                    uploaded = await client.upload(
                        str(file_path),
                        file_name=file_name,
                        callback=progress_cb,
                    )

                    # تبدیل پاسخ آپلودر به دیکشنری معتبر
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

                    # ارسال پیام نهایی
                    await client.send_message(
                        object_guid=dest_guid,
                        text=caption,
                        file_inline=payload,
                    )

                    await _edit(
                        status_msg,
                        f"✅ <b>آپلود به روبیکا انجام شد!</b>\n\n"
                        f"📁 <code>{escape(file_path.name)}</code>\n"
                        f"💾 {size_mb:.1f} MB",
                    )
                    logger.info("آپلود در روبیکا با موفقیت انجام شد.")
                    break
                except Exception as exc:
                    logger.error(f"خطا در تلاش {attempt} آپلود روبیکا: {exc}")
                    if attempt < max_retries:
                        await _edit(
                            status_msg,
                            f"⚠️ <b>خطای موقت شبکه روبیکا (تلاش {attempt}/{max_retries})</b>\n\n"
                            f"سیستم در حال تلاش مجدد است. لطفا شکیبا باشید...\n"
                            f"جزئیات خطا: <code>{escape(str(exc)[:150])}</code>"
                        )
                        await asyncio.sleep(5)
                    else:
                        await _edit(status_msg, f"❌ <b>خطا در آپلود به روبیکا بعد از {max_retries} تلاش:</b>\n\n{escape(str(exc)[:400])}")

# --- پردازش دانلود APK ---

async def _handle_apk_download(message: Message, package: str, mode: str) -> None:
    logger.info(f"درخواست دانلود APK دریافت شد: {package}")
    task_id = uuid.uuid4().hex[:8]
    job_dir = DOWNLOAD_DIR / task_id
    _active[task_id] = {"cancelled": False}

    dest_label = "تلگرام 📱" if mode == "telegram" else "روبیکا 💬"
    status = await _reply(
        message,
        f"📦 <b>شروع دانلود APK</b>\n\n"
        f"📱 <code>{escape(package)}</code>\n"
        f"📤 مقصد: {dest_label}\n\n"
        f"⏳ در حال دریافت از گوگل پلی...\n"
        f"🆔 <code>{task_id}</code>",
    )

    async def progress(text: str) -> None:
        if _active.get(task_id, {}).get("cancelled"):
            raise asyncio.CancelledError("لغو شد")
        await _edit(status, f"{text}\n\n🆔 <code>{task_id}</code>")

    try:
        async with _sem():
            if _active.get(task_id, {}).get("cancelled"):
                await _edit(status, "🛑 <b>لغو شد</b>")
                return

            apk_path = await download_and_prepare(
                package=package,
                job_dir=job_dir,
                apkeditor_jar=APKEDITOR_JAR,
                arch=PLAY_ARCH,
                progress_callback=progress,
            )

        caption = f"📱 <code>{escape(package)}</code>"
        await _upload_to_target(message, status, apk_path, mode, caption)

    except asyncio.CancelledError:
        logger.info(f"تسک {task_id} لغو شد.")
        await _edit(status, f"🛑 <b>لغو شد</b>\n🆔 <code>{task_id}</code>")
    except DownloadError as exc:
        logger.error(f"خطای دانلود APK ({task_id}): {exc}")
        await _edit(status, f"❌ <b>خطا در دانلود APK:</b>\n\n{escape(str(exc))}\n\n🆔 <code>{task_id}</code>")
    except Exception as exc:
        logger.error(f"خطای کریتیکال در APK ({task_id}): {exc}", exc_info=True)
        await _edit(status, f"❌ <b>خطای غیرمنتظره:</b>\n\n{escape(str(exc)[:300])}\n\n🆔 <code>{task_id}</code>")
    finally:
        _active.pop(task_id, None)
        shutil.rmtree(job_dir, ignore_errors=True)

# --- پردازش دانلود URL ---

async def _handle_url_download(message: Message, url: str, mode: str) -> None:
    logger.info(f"درخواست دانلود از URL دریافت شد: {url[:50]}...")
    task_id = uuid.uuid4().hex[:8]
    job_dir = DOWNLOAD_DIR / task_id
    _active[task_id] = {"cancelled": False}

    dest_label = "تلگرام 📱" if mode == "telegram" else "روبیکا 💬"
    status = await _reply(
        message,
        f"🔗 <b>شروع دانلود از لینک</b>\n\n"
        f"🌐 <code>{escape(url[:80])}</code>\n"
        f"📤 مقصد: {dest_label}\n\n"
        f"⏳ در حال دریافت...\n"
        f"🆔 <code>{task_id}</code>",
    )

    async def progress(text: str) -> None:
        if _active.get(task_id, {}).get("cancelled"):
            raise asyncio.CancelledError("لغو شد")
        await _edit(status, f"{text}\n\n🆔 <code>{task_id}</code>")

    try:
        async with _sem():
            file_path = await download_url(url, job_dir, progress)

        caption = f"🔗 دانلود از لینک مستقیم"
        await _upload_to_target(message, status, file_path, mode, caption)

    except URLDownloadError as exc:
        logger.error(f"خطای دانلود URL ({task_id}): {exc}")
        await _edit(status, f"❌ <b>خطا در دانلود:</b>\n\n{escape(str(exc))}\n\n🆔 <code>{task_id}</code>")
    except Exception as exc:
        logger.error(f"خطای کریتیکال در URL ({task_id}): {exc}", exc_info=True)
        await _edit(status, f"❌ <b>خطای غیرمنتظره:</b>\n\n{escape(str(exc)[:300])}\n\n🆔 <code>{task_id}</code>")
    finally:
        _active.pop(task_id, None)
        shutil.rmtree(job_dir, ignore_errors=True)

# --- پردازش فایل فوروارد شده ---

async def _handle_forwarded_file(message: Message, mode: str) -> None:
    media = (message.document or message.video or message.audio or 
             message.voice or message.video_note or message.animation or message.sticker)

    if message.photo and not media:
        photo = message.photo
        filename = f"photo_{photo.file_unique_id}.jpg"
        file_size = getattr(photo, "file_size", 0) or 0
    elif media:
        filename = getattr(media, "file_name", None) or f"file_{media.file_unique_id}"
        if "." not in Path(filename).suffix:
            mime = getattr(media, "mime_type", "") or ""
            ext_map = {
                "video/mp4": ".mp4", "video/x-matroska": ".mkv",
                "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
                "application/zip": ".zip", "application/pdf": ".pdf",
            }
            ext = ext_map.get(mime, "")
            if ext and not filename.endswith(ext):
                filename += ext
        file_size = getattr(media, "file_size", 0) or 0
    else:
        return

    logger.info(f"دریافت فایل از تلگرام برای فوروارد: {filename}")
    task_id = uuid.uuid4().hex[:8]
    job_dir = DOWNLOAD_DIR / task_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _active[task_id] = {"cancelled": False}

    dest_label = "تلگرام 📱" if mode == "telegram" else "روبیکا 💬"
    size_label = f"{file_size / (1024*1024):.1f} MB" if file_size else "نامشخص"

    status = await _reply(
        message,
        f"📥 <b>دریافت فایل از تلگرام...</b>\n\n"
        f"📁 <code>{escape(filename)}</code>\n"
        f"💾 {size_label}\n"
        f"📤 مقصد: {dest_label}\n\n"
        f"🆔 <code>{task_id}</code>",
    )

    try:
        dest_path = job_dir / filename
        downloaded = await app.download_media(message, file_name=str(dest_path))

        if not downloaded or not Path(downloaded).exists():
            logger.error(f"دانلود مدیا از سرور تلگرام ناموفق بود: {filename}")
            await _edit(status, "❌ <b>دانلود فایل از تلگرام ناموفق بود.</b>")
            return

        file_path = Path(downloaded)
        
        # 🌟 سیستم هوشمند امانت‌داری کپشن (Caption Preservation) 🌟
        original_caption = message.caption or ""
        if original_caption:
            caption = original_caption
        else:
            caption = "📎 فایل دریافتی از تلگرام"
        
        await _upload_to_target(message, status, file_path, mode, caption)

    except Exception as exc:
        logger.error(f"خطا در دانلود از تلگرام: {exc}", exc_info=True)
        await _edit(status, f"❌ <b>خطا:</b>\n\n{escape(str(exc)[:300])}\n\n🆔 <code>{task_id}</code>")
    finally:
        _active.pop(task_id, None)
        shutil.rmtree(job_dir, ignore_errors=True)

# --- هندلرهای تنظیمات ---

@app.on_message(filters.private & filters.command("start"))
async def cmd_start(client: Client, message: Message) -> None:
    logger.info(f"دستور /start از کاربر {message.from_user.id} دریافت شد.")
    if not _is_owner(getattr(message.from_user, "id", None)): return
    
    mode = _get_mode(message.from_user.id)
    zip_mode = _get_zip_mode(message.from_user.id)
    zip_pass = _get_zip_password(message.from_user.id)
    rubika_ok = "✅ متصل" if _has_rubika_session() else "❌ متصل نیست"
    
    pass_text = "بدون رمز" if zip_pass == "none" else f"دارد ({zip_pass})"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تنظیمات فشرده سازی (ZIP)", callback_data="menu_zipmode")],
        [InlineKeyboardButton("🔐 تنظیمات رمز عبور", callback_data="menu_zippass")]
    ])

    await message.reply_text(
        f"<b>⛵️ APK Downloader + Uploader Bot</b>\n\n"
        f"📤 مقصد فعلی: <b>{'تلگرام' if mode == 'telegram' else 'روبیکا'}</b>\n"
        f"🗜 حالت زیپ: <b>{zip_mode.upper()}</b>\n"
        f"🔐 وضعیت رمز: <b>{pass_text}</b>\n"
        f"📱 حساب روبیکا: {rubika_ok}\n\n"
        f"<b>دستورات اصلی:</b>\n"
        f"/rubika - مقصد روبیکا (پیش فرض)\n"
        f"/telegram - مقصد تلگرام\n"
        f"/set_dest - تنظیم GUID گروه/کانال مقصد روبیکا\n"
        f"/set_rubika - لاگین به حساب روبیکا\n\n"
        f"از دکمه های زیر برای تنظیمات فایل های ارسالی استفاده کن:",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=keyboard
    )

async def send_zipmode_menu(client: Client, chat_id: int, user_id: int) -> None:
    current = _get_zip_mode(user_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 حالت هوشمند (پیش فرض) " + ("✅" if current=="auto" else ""), callback_data="set_zip_auto")],
        [InlineKeyboardButton("📦 همیشه زیپ کن " + ("✅" if current=="always" else ""), callback_data="set_zip_always")],
        [InlineKeyboardButton("❌ خاموش " + ("✅" if current=="off" else ""), callback_data="set_zip_off")]
    ])
    
    await client.send_message(
        chat_id=chat_id,
        text=(
            f"🗜 <b>تنظیمات فشرده سازی (ZIP Mode)</b>\n"
            f"حالت فعلی: <b>{current.upper()}</b>\n\n"
            f"<b>توضیحات:</b>\n"
            f"🤖 <b>هوشمند (Auto):</b> فقط برنامه ها (apk, exe) زیپ می شوند.\n"
            f"📦 <b>همیشه:</b> تمام فایل ها زیپ می شوند.\n"
            f"❌ <b>خاموش:</b> هیچ فایلی زیپ نمی شود.\n\n"
            f"یکی از گزینه های زیر را انتخاب کنید:"
        ),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=keyboard
    )

async def send_zippass_menu(client: Client, chat_id: int, user_id: int) -> None:
    current = _get_zip_password(user_id)
    current_text = "بدون رمز (none)" if current == "none" else f"رمز فعلی: {current}"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تنظیم رمز جدید", callback_data="set_pass_new")],
        [InlineKeyboardButton("🗑 حذف رمز", callback_data="set_pass_none")]
    ])

    await client.send_message(
        chat_id=chat_id,
        text=(
            f"🔐 <b>تنظیمات رمز (ZIP Password)</b>\n"
            f"وضعیت فعلی: <b>{current_text}</b>\n\n"
            f"آیا می خواهید روی فایل های ZIP رمز قرار دهید؟"
        ),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=keyboard
    )

@app.on_message(filters.private & filters.command("zipmode"))
async def cmd_zipmode(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    await send_zipmode_menu(client, message.chat.id, message.from_user.id)

@app.on_message(filters.private & filters.command("zippass"))
async def cmd_zippass(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    await send_zippass_menu(client, message.chat.id, message.from_user.id)

@app.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    if not _is_owner(user_id): return
    
    data = callback_query.data
    
    if data == "menu_zipmode":
        await callback_query.message.delete()
        await send_zipmode_menu(client, chat_id, user_id)
        
    elif data == "menu_zippass":
        await callback_query.message.delete()
        await send_zippass_menu(client, chat_id, user_id)
        
    elif data.startswith("set_zip_"):
        mode = data.split("_")[2]
        _zip_modes[user_id] = mode
        await callback_query.answer(f"حالت فشرده سازی به {mode.upper()} تغییر یافت.", show_alert=True)
        await callback_query.message.delete()
        await send_zipmode_menu(client, chat_id, user_id)
        
    elif data == "set_pass_new":
        _user_states[user_id] = "awaiting_zippass"
        await client.send_message(
            chat_id=chat_id,
            text="💬 <b>لطفاً رمز عبور دلخواه خود را تایپ کرده و ارسال کنید:</b>\n"
                 "این رمز برای تمام فایل های فشرده بعدی اعمال می شود.",
            parse_mode=enums.ParseMode.HTML
        )
        await callback_query.answer()
        
    elif data == "set_pass_none":
        _zip_passwords[user_id] = "none"
        await callback_query.answer("رمز عبور با موفقیت حذف شد.", show_alert=True)
        await callback_query.message.delete()
        await send_zippass_menu(client, chat_id, user_id)

@app.on_message(filters.private & filters.command("mode"))
async def cmd_mode(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    mode = _get_mode(message.from_user.id)
    await _reply(message, f"<b>حالت فعلی مقصد:</b> {'📱 تلگرام' if mode == 'telegram' else '💬 روبیکا'}")

@app.on_message(filters.private & filters.command("telegram"))
async def cmd_mode_telegram(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    _modes[message.from_user.id] = "telegram"
    await _reply(message, "📱 <b>مقصد: تلگرام</b>\nفایل ها اینجا آپلود می شن.")

@app.on_message(filters.private & filters.command("rubika"))
async def cmd_mode_rubika(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    _modes[message.from_user.id] = "rubika"
    await _reply(message, "💬 <b>مقصد: روبیکا</b>")

@app.on_message(filters.private & filters.command("set_dest"))
async def cmd_set_dest(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    args = message.command[1:] if message.command else []
    if not args:
        current = _load_dest_guid()
        info = f"GUID فعلی: <code>{current}</code>\n\n" if current else ""
        await _reply(message, f"<b>🎯 تنظیم GUID مقصد</b>\n\n{info}فرمت: /set_dest guid")
        return
    guid = args[0].strip()
    _save_dest_guid(guid)
    await _reply(message, f"✅ <b>GUID ذخیره شد:</b>\n<code>{escape(guid)}</code>")

@app.on_message(
    filters.private & (
        filters.document | filters.video | filters.audio | filters.voice | 
        filters.video_note | filters.animation | filters.photo | filters.sticker
    )
)
async def file_handler(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    mode = _get_mode(message.from_user.id)
    asyncio.create_task(_handle_forwarded_file(message, mode))

# --- auth روبیکا ---

@app.on_message(filters.private & filters.command("set_rubika"))
async def cmd_set_rubika(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    args = message.command[1:] if message.command else []
    if args: await _start_rubika_auth(message, " ".join(args))
    else: await _prompt_rubika_phone(message)

async def _prompt_rubika_phone(message: Message) -> None:
    _auth_states[message.chat.id] = {"stage": "await_phone"}
    await _reply(message, "📱 <b>تنظیم حساب روبیکا</b>\n\nشماره موبایل را بفرست (فرمت: 09123456789):")

async def _handle_auth_input(message: Message, text: str, state: dict) -> bool:
    stage = state.get("stage")
    if stage == "await_phone":
        await _start_rubika_auth(message, text)
        return True
    if stage in ("await_otp", "await_passkey"):
        process: subprocess.Popen | None = state.get("process")
        if process and process.stdin:
            try:
                process.stdin.write(text.strip() + "\n")
                process.stdin.flush()
                state["stage"] = "waiting"
                await _reply(message, "⏳ در حال بررسی...")
            except Exception as e: logger.error(f"خطا در ارسال دیتای auth: {e}")
        return True
    return False

async def _start_rubika_auth(message: Message, phone: str) -> None:
    chat_id = message.chat.id
    if not RUBIKA_AUTH_HELPER.exists():
        await _reply(message, "❌ فایل <code>rubika_auth_helper.py</code> پیدا نشد.")
        return
    status = await _reply(message, "📨 در حال ارتباط با روبیکا...")
    try:
        process = subprocess.Popen(
            [sys.executable, str(RUBIKA_AUTH_HELPER), RUBIKA_SESSION, phone.strip()],
            cwd=str(BASE_DIR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
    except OSError as exc:
        await _edit(status, f"❌ خطا: {exc}")
        return
    _auth_states[chat_id] = {"stage": "waiting_for_otp", "process": process, "status_msg": status}
    asyncio.create_task(_monitor_auth(chat_id, process, status))

async def _monitor_auth(chat_id: int, process: subprocess.Popen, status: Message) -> None:
    try:
        while True:
            line = await asyncio.to_thread(process.stdout.readline)
            if not line:
                if process.poll() is not None: break
                continue
            text = line.strip()
            if not text: continue
            current = _auth_states.get(chat_id)
            if not current or current.get("process") is not process: return

            if text == "__AUTH_OTP_PROMPT__":
                current["stage"] = "await_otp"
                await _edit(status, "🔐 کد OTP روبیکا رو بفرست:")
            elif text.startswith("__AUTH_PASSKEY_PROMPT__:"):
                current["stage"] = "await_passkey"
                await _edit(status, f"🔑 رمز دو مرحله‌ای روبیکا رو بفرست:\n{text.split(':', 1)[1]}")
            elif text == "__AUTH_SUCCESS__":
                _auth_states.pop(chat_id, None)
                # 🌟 بستن کلاینت قبلی و آماده‌سازی برای سشن جدید 🌟
                await reset_rubika_client()
                await _edit(status, "✅ <b>حساب روبیکا متصل شد!</b>")
                return
            elif text == "__AUTH_CANCELLED__":
                _auth_states.pop(chat_id, None)
                await _edit(status, "⚪️ لغو شد.")
                return
            elif text.startswith("__AUTH_ERROR__:"):
                _auth_states.pop(chat_id, None)
                await _edit(status, f"❌ خطا:\n{text.split(':', 1)[1]}")
                return
    except Exception as exc:
        _auth_states.pop(chat_id, None)
        await _edit(status, f"❌ خطا: {exc}")

# --- هندلر پیام‌های متنی ---

@app.on_message(filters.private & filters.text)
async def text_handler(client: Client, message: Message) -> None:
    if not _is_owner(getattr(message.from_user, "id", None)): return
    text = (message.text or "").strip()
    if not text or text.startswith("/"): return

    user_id = message.from_user.id

    # بررسی وضعیت دریافت رمز ZIP
    if _user_states.get(user_id) == "awaiting_zippass":
        _zip_passwords[user_id] = text
        _user_states.pop(user_id, None)
        await _reply(message, f"✅ <b>رمز عبور با موفقیت تنظیم شد!</b>\nاز این به بعد فایل های فشرده با رمز <code>{escape(text)}</code> محافظت می شوند.")
        return

    if (auth_state := _auth_states.get(message.chat.id)):
        if await _handle_auth_input(message, text, auth_state): return

    mode = _get_mode(user_id)

    if is_google_play_url(text):
        package = extract_package_name(text)
        if package: 
            asyncio.create_task(_handle_apk_download(message, package, mode))
        else: 
            await _reply(message, "❌ خطا در استخراج پکیج.")
        return

    if is_direct_url(text):
        asyncio.create_task(_handle_url_download(message, text, mode))
        return

    await _reply(
        message,
        f"ℹ️ حالت فعلی: آپلود به <b>{'تلگرام' if mode == 'telegram' else 'روبیکا'}</b>\n\n"
        "لینک گوگل پلی، لینک مستقیم، یا فایل بفرست."
    )

# --- اجرای ربات ---

if __name__ == "__main__":
    try:
        if not API_ID or not API_HASH or not BOT_TOKEN:
            logger.critical("مقادیر API_ID, API_HASH, BOT_TOKEN در .env تنظیم نشدن.")
            sys.exit(1)

        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        
        # نیازمند بودن برنامه zip در لینوکس
        if shutil.which("zip") is None:
            logger.warning("ابزار 'zip' در لینوکس نصب نیست. برای کارکرد سیستم فشرده سازی باید آن را نصب کنید: apt-get install zip")

        _loop.run_until_complete(ensure_bootstrap(APKEDITOR_JAR))
        
        dest_guid = _load_dest_guid()
        if dest_guid: logger.info(f"مقصد روبیکا: {dest_guid[:16]}...")
        
        logger.info("✅ ربات تلگرام در حال راه اندازی است...")
        app.run()
    except Exception as e:
        logger.critical(f"خطای بحرانی در هنگام اجرای ربات: {e}")
        traceback.print_exc()
        sys.exit(1)