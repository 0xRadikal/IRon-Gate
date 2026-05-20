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
    from pathlib import Path as P
    config_candidates = [
        P.home() / ".gplaydl" / "credentials.json",
        P.home() / ".config" / "gplaydl" / "credentials.json",
    ]
    if any(p.exists() for p in config_candidates):
        return

    print(
        "\n"
        "═══════════════════════════════════════════\n"
        "⚠️  gplaydl هنوز تنظیم نشده!\n"
        "یه بار این دستور رو بزن:\n\n"
        "    gplaydl setup\n\n"
        "یه اکانت گوگل می‌خواد (برای دانلود از گوگل پلی)\n"
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
