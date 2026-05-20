from __future__ import annotations

"""
rubika_uploader.py — آپلود فایل به روبیکا از هر جای پروژه

این ماژول توسط telegram_bot.py استفاده می‌شه تا فایل‌ها رو
مستقیم به روبیکا آپلود کنه.
"""

import time
from pathlib import Path
from typing import Callable, Awaitable

ProgressCallback = Callable[[str], Awaitable[None]]


class RubikaUploadError(RuntimeError):
    pass


def make_file_inline(uploaded, file_type: str = "File") -> dict:
    """
    خروجی client.upload() رو به file_inline مورد نیاز send_message تبدیل می‌کنه.
    
    rubpy ممکنه dict یا object برگردونه. هر دو حالت handle می‌شه.
    """
    if isinstance(uploaded, dict):
        payload = dict(uploaded)
    else:
        raw = getattr(uploaded, "to_dict", None)
        if callable(raw):
            raw = raw()
        payload = dict(raw) if isinstance(raw, dict) else {}
        # اگه payload خالیه، از attributes مستقیم بساز
        if not payload:
            for attr in (
                "file_id", "dc_id", "access_hash_rec", "file_name",
                "size", "mime", "thumb_inline",
            ):
                val = getattr(uploaded, attr, None)
                if val is not None:
                    payload[attr] = val

    payload.setdefault("type", file_type)
    payload.setdefault("time", 1)
    payload.setdefault("width", 0)
    payload.setdefault("height", 0)
    payload.setdefault("music_performer", "")
    payload.setdefault("is_spoil", False)
    return payload


def _guess_file_type(filename: str) -> str:
    """نوع فایل رو از پسوند تشخیص می‌ده."""
    ext = Path(filename).suffix.lower()
    if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"):
        return "Video"
    if ext in (".mp3", ".ogg", ".flac", ".aac", ".wav", ".m4a", ".opus"):
        return "Music"
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        return "Image"
    if ext in (".apk", ".apks", ".xapk"):
        return "File"
    return "File"


async def upload_to_rubika(
    file_path: Path,
    object_guid: str,
    session_name: str,
    caption: str = "",
    reply_to: int | None = None,
    progress: ProgressCallback | None = None,
) -> None:
    """
    یه فایل محلی رو به یه چت روبیکا آپلود می‌کنه.
    
    Args:
        file_path:    مسیر فایل روی دیسک
        object_guid:  GUID چت مقصد در روبیکا
        session_name: نام session روبیکا
        caption:      متن همراه فایل
        reply_to:     message_id که باید ریپلای بشه (اختیاری)
        progress:     async callback برای نمایش وضعیت
    
    Raises:
        RubikaUploadError: اگه آپلود ناموفق بود
    """
    try:
        from rubpy import Client
    except ImportError as e:
        raise RubikaUploadError(f"rubpy نصب نیست: {e}") from e

    async def _progress(msg: str) -> None:
        if progress:
            try:
                await progress(msg)
            except Exception:
                pass

    file_name = file_path.name
    size_mb = file_path.stat().st_size / (1024 * 1024)
    file_type = _guess_file_type(file_name)

    _last_pct: list[int] = [-1]
    _last_ts: list[float] = [0.0]
    _start_ts = time.monotonic()

    async def _upload_cb(total: int, current: int) -> None:
        if total <= 0:
            return
        pct = min(99, max(0, int((current * 100) / total)))
        now = time.monotonic()
        if pct - _last_pct[0] < 10 and now - _last_ts[0] < 3.0:
            return
        _last_pct[0] = pct
        _last_ts[0] = now
        elapsed = now - _start_ts
        speed = current / elapsed if elapsed > 0 else 0
        speed_str = (
            f"{speed / (1024 * 1024):.1f} MB/s"
            if speed > 1024 * 1024
            else f"{speed / 1024:.0f} KB/s"
        )
        await _progress(
            f"⬆️ آپلود به روبیکا...\n"
            f"📁 {file_name}\n"
            f"💾 {size_mb:.1f} MB\n"
            f"📊 {pct}%  •  {speed_str}"
        )

    await _progress(
        f"⬆️ آپلود به روبیکا...\n"
        f"📁 {file_name}\n"
        f"💾 {size_mb:.1f} MB"
    )

    try:
        async with Client(name=session_name) as client:
            uploaded = await client.upload(
                str(file_path),
                file_name=file_name,
                callback=_upload_cb,
            )

            file_inline = make_file_inline(uploaded, file_type=file_type)
            final_caption = caption or f"📁 {file_name}\n💾 {size_mb:.1f} MB"

            kwargs: dict = {
                "object_guid": object_guid,
                "text": final_caption,
                "file_inline": file_inline,
            }
            if reply_to is not None:
                kwargs["reply_to_message_id"] = reply_to

            await client.send_message(**kwargs)

    except RubikaUploadError:
        raise
    except Exception as exc:
        raise RubikaUploadError(
            f"آپلود به روبیکا ناموفق بود:\n{type(exc).__name__}: {exc}"
        ) from exc
