from __future__ import annotations

"""
downloader.py — دانلود APK از گوگل پلی

سه حالت:
  arm64     → گوشی‌های ۲۰۱۶+ (پیشفرض، ۹۵٪+ دستگاه‌های فعلی)
  armv7     → گوشی‌های قدیمی ۳۲ بیتی
  universal → fat APK شامل هر دو معماری (دو بار دانلود، فایل بزرگ‌تر)
"""

import asyncio
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Awaitable

DEFAULT_ARCH = "arm64"
VALID_ARCHS = {"arm64", "armv7", "universal"}
DOWNLOAD_TIMEOUT = 600
MERGE_TIMEOUT = 300

ProgressCallback = Callable[[str], Awaitable[None]]


class DownloadError(RuntimeError):
    pass


# ─── پیدا کردن نتیجه دانلود ───────────────────────────────────────────────────


def _find_result(output_dir: Path) -> Path:
    """بهترین APK/APKS رو از پوشه خروجی پیدا می‌کنه."""
    all_files = list(output_dir.rglob("*.apk")) + list(output_dir.rglob("*.apks"))

    if not all_files:
        raise DownloadError(
            "هیچ فایل APK بعد از دانلود پیدا نشد.\n"
            "ممکنه دانلود ناقص بوده باشه یا برنامه در دسترس نباشه."
        )

    # اگه merged.apk هست اولویت داره
    merged = [p for p in all_files if p.suffix == ".apk" and "merged" in p.stem.lower()]
    if merged:
        return max(merged, key=lambda p: p.stat().st_mtime)

    apks = [p for p in all_files if p.suffix == ".apk"]
    apkss = [p for p in all_files if p.suffix == ".apks"]

    if len(apks) == 1:
        return apks[0]
    if apkss and not apks:
        return apkss[0]
    if len(apks) > 1:
        return output_dir  # چند split → پوشه رو می‌دیم تا APKEditor ادغام کنه

    return max(all_files, key=lambda p: p.stat().st_mtime)


# ─── دانلود با gplaydl ────────────────────────────────────────────────────────


async def _run_gplaydl(package: str, output_dir: Path, arch: str) -> Path:
    """
    gplaydl رو برای یه معماری اجرا می‌کنه.
    فقط arm64 یا armv7 قبول می‌کنه.
    """
    assert arch in {"arm64", "armv7"}, f"arch نامعتبر برای gplaydl: {arch}"
    output_dir.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "gplaydl", "download", package,
        "-o", str(output_dir),
        "-a", arch,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=DOWNLOAD_TIMEOUT)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise DownloadError(
            f"دانلود بعد از {DOWNLOAD_TIMEOUT // 60} دقیقه تایم‌اوت شد."
        ) from exc

    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()
    combined = (err or out).lower()

    if proc.returncode != 0:
        if "not found" in combined or "does not exist" in combined:
            raise DownloadError(f"برنامه «{package}» در گوگل پلی پیدا نشد.")
        if "auth" in combined or "token" in combined or "credentials" in combined:
            raise DownloadError(
                "gplaydl auth نداره یا منقضی شده.\n"
                "دستور زیر رو اجرا کن:\n    gplaydl auth"
            )
        if "paid" in combined or "purchase" in combined:
            raise DownloadError("این برنامه پولیه و قابل دانلود رایگان نیست.")
        if "not available" in combined or "country" in combined:
            raise DownloadError("این برنامه در منطقه جغرافیایی سرور در دسترس نیست.")
        raise DownloadError(f"gplaydl خطا داد:\n{(err or out)[-400:]}")

    return _find_result(output_dir)


# ─── ادغام با APKEditor ───────────────────────────────────────────────────────


async def _merge_apk(
    source: Path,
    apkeditor_jar: Path,
    output_name: str = "merged.apk",
) -> Path:
    """
    پوشه یا فایل .apks رو با APKEditor به یه APK واحد تبدیل می‌کنه.
    """
    java = shutil.which("java")
    if not java:
        raise DownloadError(
            "Java پیدا نشد.\n"
            "نصب: sudo apt install -y openjdk-17-jre-headless"
        )
    if not apkeditor_jar.exists():
        raise DownloadError(
            f"APKEditor.jar پیدا نشد: {apkeditor_jar}\n"
            "از https://github.com/REAndroid/APKEditor/releases دانلود کن."
        )

    output = source.parent / output_name

    proc = await asyncio.create_subprocess_exec(
        java, "-jar", str(apkeditor_jar),
        "m",
        "-i", str(source),
        "-o", str(output),
        "-f",  # overwrite اگه وجود داشت
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=MERGE_TIMEOUT)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise DownloadError("ادغام APK تایم‌اوت شد.") from exc

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise DownloadError(f"APKEditor ناموفق بود:\n{err[-400:]}")

    if not output.exists():
        raise DownloadError("فایل خروجی بعد از ادغام پیدا نشد.")

    return output


# ─── Universal: دو معماری رو ادغام می‌کنیم ──────────────────────────────────


def _collect_splits(src: Path, combined_dir: Path, prefix: str) -> int:
    """
    همه split APKهای یه معماری رو به combined_dir کپی می‌کنه.

    - فایل‌های تکراری (مثل base.apk) از arm64 گرفته می‌شن و armv7 رد می‌شه.
    - فایل‌های معماری‌مخصوص (config.arm64 / config.armeabi) هر دو نگه داشته می‌شن.

    Returns:
        تعداد فایل‌های کپی‌شده
    """
    copied = 0

    # اگه src پوشه هست، همه .apkهاش رو بگیر
    if src.is_dir():
        files = sorted(p for p in src.rglob("*.apk") if p.is_file())
    elif src.suffix == ".apks":
        # فایل .apks رو unzip کن
        tmp = combined_dir / f"_unzip_{prefix}"
        tmp.mkdir(exist_ok=True)
        with zipfile.ZipFile(src) as z:
            z.extractall(tmp)
        files = sorted(p for p in tmp.rglob("*.apk") if p.is_file())
    else:
        # تنها APK
        files = [src] if src.suffix == ".apk" else []

    for f in files:
        dest = combined_dir / f.name
        if dest.exists():
            # اگه فایل از قبل هست (مثل base.apk از arm64)، نسخه جدید رو با پیشوند ذخیره کن
            dest = combined_dir / f"{prefix}_{f.name}"
        shutil.copy2(f, dest)
        copied += 1

    return copied


async def _build_universal_apk(
    package: str,
    job_dir: Path,
    apkeditor_jar: Path,
    progress: ProgressCallback,
) -> Path:
    """
    Fat APK شامل هر دو معماری arm64 و armv7.

    روش:
      ۱. دانلود splits مخصوص arm64
      ۲. دانلود splits مخصوص armv7
      ۳. کپی همه splits در یه پوشه مشترک
         (splits مشترک مثل base.apk و config.xxhdpi فقط یه بار کپی می‌شن)
      ۴. APKEditor همه splits رو با هم ادغام می‌کنه
    """
    arm64_dir = job_dir / "dl_arm64"
    armv7_dir = job_dir / "dl_armv7"
    combined_dir = job_dir / "combined"
    combined_dir.mkdir(parents=True, exist_ok=True)

    # ─── arm64 ──────────────────────────────────────────────────────────────
    await progress(
        f"⬇️ دانلود splits مخصوص arm64...\n"
        f"📱 {package}\n"
        f"🔄 این برای ساخت Universal APK دو بار دانلود می‌کنه"
    )
    try:
        arm64_result = await _run_gplaydl(package, arm64_dir, "arm64")
    except DownloadError as exc:
        raise DownloadError(f"دانلود arm64 برای universal APK ناموفق بود:\n{exc}") from exc

    # ─── armv7 ──────────────────────────────────────────────────────────────
    await progress(
        f"⬇️ دانلود splits مخصوص armv7...\n"
        f"📱 {package}\n"
        f"🔄 بخش دوم دانلود..."
    )
    try:
        armv7_result = await _run_gplaydl(package, armv7_dir, "armv7")
    except DownloadError as exc:
        raise DownloadError(f"دانلود armv7 برای universal APK ناموفق بود:\n{exc}") from exc

    # ─── ترکیب splits ──────────────────────────────────────────────────────
    # arm64 اول (splits مشترک از نسخه arm64 گرفته می‌شن)
    n1 = _collect_splits(arm64_result if not arm64_result.is_dir() else arm64_dir, combined_dir, "arm64")
    n2 = _collect_splits(armv7_result if not armv7_result.is_dir() else armv7_dir, combined_dir, "armv7")
    total_splits = len(list(combined_dir.glob("*.apk")))

    if total_splits == 0:
        raise DownloadError("هیچ split APKی برای ادغام پیدا نشد.")

    await progress(
        f"🔧 ادغام {total_splits} فایل split APK با APKEditor...\n"
        f"📱 {package}\n"
        f"⏳ این ممکنه چند دقیقه طول بکشه"
    )
    return await _merge_apk(combined_dir, apkeditor_jar, output_name="universal.apk")


# ─── پایپلاین اصلی (public API) ──────────────────────────────────────────────


async def download_and_prepare(
    package: str,
    job_dir: Path,
    apkeditor_jar: Path,
    arch: str = DEFAULT_ARCH,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """
    پایپلاین کامل: دانلود → ادغام splits → APK نهایی.

    arch:
      "arm64"     → گوشی‌های مدرن ۶۴ بیتی، ۲۰۱۶+ (پیشفرض)
      "armv7"     → گوشی‌های قدیمی ۳۲ بیتی
      "universal" → fat APK برای همه (دو بار دانلود، فایل بزرگ‌تر)

    Returns:
        مسیر فایل .apk نهایی
    """
    job_dir.mkdir(parents=True, exist_ok=True)

    arch = (arch or DEFAULT_ARCH).strip().lower()
    if arch not in VALID_ARCHS:
        arch = DEFAULT_ARCH

    async def progress(msg: str) -> None:
        if progress_callback:
            try:
                await progress_callback(msg)
            except Exception:
                pass

    # ─── Universal ──────────────────────────────────────────────────────────
    if arch == "universal":
        return await _build_universal_apk(package, job_dir, apkeditor_jar, progress)

    # ─── arm64 یا armv7 ─────────────────────────────────────────────────────
    arch_label = "arm64 (گوشی مدرن)" if arch == "arm64" else "armv7 (گوشی قدیمی)"
    await progress(
        f"⬇️ دانلود از گوگل پلی...\n"
        f"📱 {package}\n"
        f"🏗 معماری: {arch_label}"
    )

    result = await _run_gplaydl(package, job_dir, arch)

    if result.is_dir() or result.suffix == ".apks":
        await progress(
            f"🔧 ادغام split APKها...\n"
            f"📱 {package}"
        )
        result = await _merge_apk(result, apkeditor_jar)

    return result


# ─── helper‌های عمومی ─────────────────────────────────────────────────────────


def extract_package_name(text: str) -> str | None:
    """نام پکیج رو از لینک گوگل پلی استخراج می‌کنه."""
    import re
    m = re.search(
        r"https?://play\.google\.com/store/apps/details\?[^\s]*id=([a-zA-Z0-9._]+)",
        text,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def is_google_play_url(text: str) -> bool:
    return "play.google.com/store/apps/details" in text and "id=" in text


def arch_description(arch: str) -> str:
    """توضیح فارسی هر حالت معماری."""
    return {
        "arm64":     "arm64 — گوشی مدرن ۶۴ بیتی (۲۰۱۶+)",
        "armv7":     "armv7 — گوشی قدیمی ۳۲ بیتی",
        "universal": "Universal — همه گوشی‌ها (فایل بزرگ‌تر)",
    }.get(arch.lower(), arch)
