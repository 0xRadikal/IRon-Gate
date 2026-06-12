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


def _iter_apk_files(src: Path, tmp_dir: Path, tag: str) -> list[Path]:
    """
    همه فایل‌های APK یه دانلود رو برمی‌گردونه.

    - اگه src پوشه باشه: همه *.apk داخلش
    - اگه .apks (zip) باشه: اول unzip بعد *.apk
    - اگه یه .apk تنها باشه: همون
    """
    if src.is_dir():
        return sorted(p for p in src.rglob("*.apk") if p.is_file())
    if src.suffix == ".apks":
        unzip_dir = tmp_dir / f"_unzip_{tag}"
        unzip_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src) as z:
            z.extractall(unzip_dir)
        return sorted(p for p in unzip_dir.rglob("*.apk") if p.is_file())
    if src.suffix == ".apk":
        return [src]
    return []


# نشانه‌های نام فایل برای تشخیص split معماری ۳۲ بیتی (armv7)
_ARMV7_MARKERS = ("armeabi_v7a", "armeabi-v7a", "armeabi", "_armeabi", ".armeabi")


def _is_armv7_abi_split(name: str) -> bool:
    low = name.lower()
    return any(m in low for m in _ARMV7_MARKERS)


def _collect_universal_splits(
    arm64_files: list[Path],
    armv7_files: list[Path],
    combined_dir: Path,
) -> int:
    """
    splitهای دو دانلود رو هوشمندانه ترکیب می‌کنه تا یه مجموعهٔ معتبر بسازه.

    منطق درست (مشکل قبلی این بود که base.apk دوبار با پیشوند کپی می‌شد و
    باعث خرابی ادغام APKEditor می‌شد):

      ۱. کل مجموعهٔ arm64 رو می‌گیریم (base + config.arm64_v8a + همهٔ
         splitهای DPI/زبان مشترک). این مبنا (canonical) هست.
      ۲. از دانلود armv7 فقط split معماری ۳۲ بیتی (config.armeabi_v7a)
         رو اضافه می‌کنیم؛ base و بقیهٔ splitهای مشترک نادیده گرفته می‌شن
         چون از قبل در مجموعهٔ arm64 هستن.
      ۳. کپی بر اساس «نام فایل» de-dup می‌شه؛ هیچ پیشوند تکراری اضافه نمی‌شه
         تا APKEditor دقیقاً یک base ببینه.

    خروجی: مجموعه‌ای از splitها که هم arm64_v8a و هم armeabi_v7a داره →
    APK نهایی روی هر دو معماری نصب می‌شه (universal/fat).
    """
    seen: set[str] = set()
    copied = 0

    # ۱. مبنا: کل arm64
    for f in arm64_files:
        if f.name in seen:
            continue
        shutil.copy2(f, combined_dir / f.name)
        seen.add(f.name)
        copied += 1

    # ۲. از armv7 فقط split ABI سی‌و‌دو‌بیتی
    for f in armv7_files:
        if not _is_armv7_abi_split(f.name):
            continue
        if f.name in seen:
            continue
        shutil.copy2(f, combined_dir / f.name)
        seen.add(f.name)
        copied += 1

    return copied


async def _build_universal_apk(
    package: str,
    job_dir: Path,
    apkeditor_jar: Path,
    progress: ProgressCallback,
) -> Path:
    """
    Universal (fat) APK شامل هر دو معماری arm64-v8a و armeabi-v7a.

    روش درست:
      ۱. یک‌بار با arm64 دانلود می‌کنیم → base + config.arm64_v8a +
         splitهای DPI/زبان (مجموعهٔ مبنا).
      ۲. یک‌بار با armv7 دانلود می‌کنیم → فقط برای گرفتن config.armeabi_v7a.
      ۳. base و splitهای مشترک فقط یک‌بار نگه داشته می‌شن (de-dup بر اساس نام)؛
         سپس split معماری ۳۲ بیتی اضافه می‌شه.
      ۴. APKEditor مجموعه رو به یک APK واحد ادغام می‌کنه که روی همهٔ
         دستگاه‌ها (۳۲ و ۶۴ بیتی) نصب می‌شه.
    """
    arm64_dir = job_dir / "dl_arm64"
    armv7_dir = job_dir / "dl_armv7"
    combined_dir = job_dir / "combined"
    combined_dir.mkdir(parents=True, exist_ok=True)

    # ─── دانلود مبنا (arm64) ─────────────────────────────────────────────────
    await progress(
        f"⬇️ مرحله ۱/۲ — دانلود مجموعهٔ کامل (arm64-v8a)...\n"
        f"📱 {package}\n"
        f"🌍 در حال ساخت Universal APK (دو بار دانلود)"
    )
    try:
        arm64_result = await _run_gplaydl(package, arm64_dir, "arm64")
    except DownloadError as exc:
        raise DownloadError(f"دانلود arm64 برای universal APK ناموفق بود:\n{exc}") from exc

    # ─── دانلود مکمل (armv7) ─────────────────────────────────────────────────
    await progress(
        f"⬇️ مرحله ۲/۲ — دانلود split معماری ۳۲ بیتی (armeabi-v7a)...\n"
        f"📱 {package}"
    )
    try:
        armv7_result = await _run_gplaydl(package, armv7_dir, "armv7")
    except DownloadError as exc:
        raise DownloadError(f"دانلود armv7 برای universal APK ناموفق بود:\n{exc}") from exc

    # ─── ترکیب درست splitها ─────────────────────────────────────────────────
    arm64_files = _iter_apk_files(
        arm64_result if not arm64_result.is_dir() else arm64_dir,
        job_dir, "arm64",
    )
    armv7_files = _iter_apk_files(
        armv7_result if not armv7_result.is_dir() else armv7_dir,
        job_dir, "armv7",
    )

    if not arm64_files:
        raise DownloadError("هیچ APKی از دانلود arm64 پیدا نشد.")

    n = _collect_universal_splits(arm64_files, armv7_files, combined_dir)
    combined_files = sorted(combined_dir.glob("*.apk"))
    total_splits = len(combined_files)

    if total_splits == 0:
        raise DownloadError("هیچ split APKی برای ادغام پیدا نشد.")

    # اگه فقط یک فایل APK داریم (برنامه split نداره)، همون خودش universal هست
    if total_splits == 1:
        return combined_files[0]

    has_armv7 = any(_is_armv7_abi_split(p.name) for p in combined_files)
    abi_note = "هر دو معماری (arm64-v8a + armeabi-v7a)" if has_armv7 else "arm64-v8a"

    await progress(
        f"🔧 ادغام {total_splits} فایل split با APKEditor...\n"
        f"📱 {package}\n"
        f"🏗 معماری: {abi_note}\n"
        f"⏳ ممکنه چند دقیقه طول بکشه"
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
