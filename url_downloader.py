from __future__ import annotations

"""
url_downloader.py — دانلود فایل از هر URL عمومی

از Content-Disposition header اسم فایل رو میخونه،
اگه نبود از آخر URL میگیره.
"""

import asyncio
import re
import urllib.parse
from pathlib import Path
from typing import Callable, Awaitable

import requests

DOWNLOAD_TIMEOUT_S = 600  # ۱۰ دقیقه
CHUNK_SIZE = 1024 * 512   # ۵۱۲ KB

ProgressCallback = Callable[[str], Awaitable[None]]


class URLDownloadError(RuntimeError):
    pass


def _extract_filename(url: str, headers: dict) -> str:
    """اسم فایل رو از header یا URL پیدا می‌کنه."""
    cd = headers.get("Content-Disposition", "")
    if cd:
        # filename*=UTF-8''encoded_name
        m = re.search(r"filename\*=(?:UTF-8''|utf-8'')([^\s;]+)", cd, re.IGNORECASE)
        if m:
            try:
                return urllib.parse.unquote(m.group(1))
            except Exception:
                pass
        # filename="name.ext"
        m = re.search(r'filename=["\']?([^"\';]+)["\']?', cd, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if name:
                return name

    # از URL استخراج کن
    parsed = urllib.parse.urlparse(url)
    path_part = parsed.path.rstrip("/")
    if path_part:
        name = path_part.split("/")[-1]
        name = urllib.parse.unquote(name)
        if name and "." in name:
            return name

    # fallback
    ct = headers.get("Content-Type", "").split(";")[0].strip()
    ext_map = {
        "video/mp4": "video.mp4",
        "video/mkv": "video.mkv",
        "video/webm": "video.webm",
        "audio/mpeg": "audio.mp3",
        "audio/ogg": "audio.ogg",
        "image/jpeg": "image.jpg",
        "image/png": "image.png",
        "application/zip": "archive.zip",
        "application/pdf": "document.pdf",
        "application/octet-stream": "file.bin",
    }
    return ext_map.get(ct, "downloaded_file")


def _download_sync(url: str, dest: Path, on_progress=None) -> None:
    """همزمان دانلود می‌کنه (برای استفاده در asyncio.to_thread)."""
    try:
        resp = requests.get(
            url,
            stream=True,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible; apkdl-bot/1.0)"},
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise URLDownloadError(f"اتصال به سرور برقرار نشد:\n{e}") from e
    except requests.exceptions.Timeout:
        raise URLDownloadError("اتصال به سرور تایم‌اوت شد.")
    except requests.exceptions.HTTPError as e:
        raise URLDownloadError(f"سرور خطا داد: {e.response.status_code}") from e

    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    last_pct = -1

    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress and total > 0:
                    pct = min(99, int(downloaded * 100 / total))
                    if pct - last_pct >= 5:
                        last_pct = pct
                        on_progress(pct, downloaded, total)


async def download_url(
    url: str,
    dest_dir: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    """
    یه URL رو دانلود می‌کنه و مسیر فایل ذخیره‌شده رو برمی‌گردونه.
    
    Args:
        url:       آدرس کامل (http/https)
        dest_dir:  پوشه‌ای که فایل توش ذخیره بشه
        progress:  async callback برای نمایش پیشرفت
    
    Returns:
        Path به فایل دانلودشده
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # اول header رو بگیر تا اسم فایل رو بفهمیم
    try:
        head = await asyncio.to_thread(
            lambda: requests.head(
                url,
                timeout=15,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; apkdl-bot/1.0)"},
            )
        )
        headers = dict(head.headers)
        final_url = head.url
    except Exception:
        headers = {}
        final_url = url

    filename = _extract_filename(final_url, headers)
    dest = dest_dir / filename

    # اگه فایل از قبل هست یه suffix اضافه کن
    counter = 1
    while dest.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        dest = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    size_hint = ""
    try:
        cl = int(headers.get("Content-Length", 0))
        if cl:
            size_hint = f"\n💾 {cl / (1024*1024):.1f} MB"
    except (ValueError, TypeError):
        pass

    if progress:
        await progress(
            f"⬇️ در حال دانلود...\n"
            f"🔗 {url[:60]}{'...' if len(url) > 60 else ''}"
            f"{size_hint}"
        )

    last_report: list[float] = [0.0]

    def sync_progress(pct: int, current: int, total: int) -> None:
        import time
        now = time.monotonic()
        if now - last_report[0] < 2.0:
            return
        last_report[0] = now
        # این callback sync هست، نمیتونیم مستقیم await کنیم
        # فقط اطلاعات رو ذخیره می‌کنیم

    try:
        await asyncio.wait_for(
            asyncio.to_thread(_download_sync, final_url, dest, sync_progress),
            timeout=DOWNLOAD_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        dest.unlink(missing_ok=True)
        raise URLDownloadError(
            f"دانلود بعد از {DOWNLOAD_TIMEOUT_S // 60} دقیقه تایم‌اوت شد."
        ) from exc
    except URLDownloadError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise URLDownloadError(f"خطا در دانلود:\n{exc}") from exc

    if not dest.exists() or dest.stat().st_size == 0:
        raise URLDownloadError("فایل دانلود نشد یا خالی است.")

    return dest


def is_direct_url(text: str) -> bool:
    """چک می‌کنه آیا متن یه URL مستقیم هست یا نه."""
    text = text.strip()
    return text.startswith(("http://", "https://")) and " " not in text
