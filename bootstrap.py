from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

APKEDITOR_API = "https://api.github.com/repos/REAndroid/APKEditor/releases/latest"


class BootstrapError(RuntimeError):
    pass


async def ensure_bootstrap(
    apkeditor_jar: Path | None = None,
) -> None:
    """بررسی و نصب خودکار gplaydl و APKEditor."""
    jar = apkeditor_jar or Path("tools/APKEditor.jar")

    await _ensure_gplaydl()
    await _ensure_apkeditor(jar)


async def _ensure_gplaydl() -> None:
    if shutil.which("gplaydl"):
        logger.info("[bootstrap] gplaydl پیدا شد.")
        return

    logger.info("[bootstrap] gplaydl پیدا نشد — در حال نصب...")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "gplaydl>=2.1,<3",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
    if proc.returncode != 0:
        raise BootstrapError(
            f"نصب gplaydl ناموفق بود:\n{stdout.decode(errors='replace')[-500:]}\n\n"
            "دستی نصب کن: pip install gplaydl"
        )
    logger.info("[bootstrap] gplaydl نصب شد.")

    if not shutil.which("gplaydl"):
        print(
            "\n⚠️  gplaydl نصب شد اما در PATH نیست.\n"
            "ممکنه نیاز باشه پایتون رو از venv اجرا کنی.\n"
        )

    _warn_gplaydl_setup()


def _warn_gplaydl_setup() -> None:
    """
    اگه gplaydl v2 هنوز auth نشده، به کاربر هشدار می‌ده.

    gplaydl v2 توکن احراز هویت رو در این مسیرها ذخیره می‌کنه (به ازای هر معماری):
        ~/.config/gplaydl/auth-arm64.json
        ~/.config/gplaydl/auth-armv7.json
    (نسخهٔ ۱ از credentials.json و دستور «gplaydl setup» استفاده می‌کرد که منسوخ شده.)
    """
    from pathlib import Path as P

    config_dir = P.home() / ".config" / "gplaydl"
    legacy_candidates = [
        P.home() / ".gplaydl" / "credentials.json",
        config_dir / "credentials.json",
    ]
    # v2: هر فایل auth-*.json یعنی احراز هویت انجام شده
    has_v2_auth = config_dir.is_dir() and any(config_dir.glob("auth-*.json"))
    has_legacy = any(p.exists() for p in legacy_candidates)

    if has_v2_auth or has_legacy:
        return

    print(
        "\n"
        "═══════════════════════════════════════════\n"
        "⚠️  gplaydl هنوز احراز هویت نشده!\n"
        "یه بار این دستور رو بزن:\n\n"
        "    gplaydl auth\n\n"
        "این یه توکن ناشناس (anonymous) از dispenser می‌گیره و\n"
        "نیازی به وارد کردن اکانت گوگل نداره. برای armv7 جداگانه:\n\n"
        "    gplaydl auth --arch armv7\n"
        "═══════════════════════════════════════════\n"
    )


async def _ensure_apkeditor(jar_path: Path) -> None:
    if jar_path.exists():
        logger.info("[bootstrap] APKEditor پیدا شد: %s", jar_path)
        return

    if not shutil.which("java"):
        print(
            "\n⚠️  Java پیدا نشد. بدون Java، split APKها ترکیب نمی‌شن.\n"
            "نصب: sudo apt install -y openjdk-17-jre-headless\n"
        )
        return

    logger.info("[bootstrap] APKEditor.jar پیدا نشد — در حال دانلود از GitHub...")
    jar_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        url = await asyncio.to_thread(_fetch_latest_apkeditor_url)
        await asyncio.to_thread(_download_file, url, jar_path)
        logger.info("[bootstrap] APKEditor دانلود شد: %s", jar_path)
    except Exception as exc:
        logger.warning("[bootstrap] دانلود APKEditor ناموفق بود: %s", exc)
        print(
            f"\n⚠️  APKEditor دانلود نشد ({exc}).\n"
            "دستی از اینجا دانلود کن و توی tools/ بذار:\n"
            "https://github.com/REAndroid/APKEditor/releases\n"
        )


def _fetch_latest_apkeditor_url() -> str:
    req = urllib.request.Request(
        APKEDITOR_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "apkdl-bot"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")
        if name.endswith(".jar") and url:
            return url
    raise BootstrapError("APKEditor jar در GitHub releases پیدا نشد.")


def _download_file(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as resp:
        dest.write_bytes(resp.read())
