from __future__ import annotations

"""
main.py — نقطه ورود اصلی پروژه

  ۱. اگه venv وجود داشت، خودکار باهاش ری‌اجرا می‌کنه.
  ۲. ابزارها رو بررسی و نصب می‌کنه (gplaydl، APKEditor).
  ۳. telegram_bot.py و rubika_bot.py رو به‌عنوان subprocess شروع می‌کنه.
  ۴. اگه هر کدوم کرش کردن، بعد از چند ثانیه ری‌استارت می‌کنه.
  ۵. با Ctrl+C همه چیز متوقف می‌شه.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

# ─── venv detection (باید قبل از هر import دیگه‌ای باشه) ────────────────────

BASE_DIR = Path(__file__).resolve().parent


def _maybe_use_venv() -> None:
    """
    اگه venv/ وجود داشت و الان باهاش اجرا نمی‌شیم،
    خودکار با python داخل venv ری‌اجرا می‌کنه.
    """
    venv_python = BASE_DIR / "venv" / (
        "Scripts\\python.exe" if os.name == "nt" else "bin/python"
    )
    if not venv_python.exists():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)


_maybe_use_venv()

# ─── ثابت‌ها ──────────────────────────────────────────────────────────────────

TELEGRAM_SCRIPT = BASE_DIR / "telegram_bot.py"
RUBIKA_SCRIPT = BASE_DIR / "rubika_bot.py"

# چند ثانیه صبر قبل از ری‌استارت subprocess ای که کرش کرده
RESTART_DELAY_S = 5

# فاصله بین چک‌های سلامت subprocess‌ها
HEALTH_CHECK_INTERVAL_S = 2

# ─── مدیریت subprocess ───────────────────────────────────────────────────────


def _start(script: Path) -> subprocess.Popen:
    """یه subprocess جدید برای script داده‌شده شروع می‌کنه."""
    return subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(BASE_DIR),
        # stdin/stdout/stderr رو به ارث از main می‌بره (log‌ها در ترمینال دیده می‌شن)
    )


class ProcessGroup:
    """
    نگه‌داری و مانیتورینگ گروهی از subprocess‌ها.
    هر کدوم که کرش کرد رو ری‌استارت می‌کنه.
    """

    def __init__(self, scripts: dict[str, Path]) -> None:
        self._scripts = scripts
        self._procs: dict[str, subprocess.Popen] = {}

    def start_all(self) -> None:
        for name, script in self._scripts.items():
            if not script.exists():
                print(f"[main] ⚠️  فایل {script.name} پیدا نشد — رد شد.")
                continue
            self._procs[name] = _start(script)
            print(f"[main] ▶  {script.name}  →  PID {self._procs[name].pid}")

    def stop_all(self) -> None:
        for name, proc in self._procs.items():
            if proc.poll() is None:
                proc.terminate()
                print(f"[main] ■  {name} متوقف شد.")
        self._procs.clear()

    async def monitor_forever(self) -> None:
        """
        تا ابد subprocess‌ها رو زیر نظر داره.
        اگه telegram_bot با exit code 0 متوقف شد، همه چیز رو می‌بنده.
        """
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL_S)

            for name, proc in list(self._procs.items()):
                ret = proc.poll()
                if ret is None:
                    continue  # هنوز داره اجرا می‌شه

                # کرش یا خروج
                if ret == 0 and name == "telegram":
                    print("[main] telegram_bot خروج تمیز داشت — همه چیز متوقف می‌شه.")
                    return

                print(
                    f"[main] ⚠️  {name} با exit code {ret} متوقف شد. "
                    f"ری‌استارت در {RESTART_DELAY_S} ثانیه..."
                )
                await asyncio.sleep(RESTART_DELAY_S)

                script = self._scripts.get(name)
                if script and script.exists():
                    self._procs[name] = _start(script)
                    print(f"[main] 🔄  {name} ری‌استارت شد  →  PID {self._procs[name].pid}")
                else:
                    print(f"[main] ❌  {name}: فایل script پیدا نشد، ری‌استارت ممکن نیست.")
                    self._procs.pop(name, None)


# ─── اصلی ────────────────────────────────────────────────────────────────────


async def main() -> None:
    print()
    print("╔══════════════════════════════════════╗")
    print("║      APK Downloader Bot — v1.0       ║")
    print("║  Telegram + Rubika  •  Google Play   ║")
    print("╚══════════════════════════════════════╝")
    print()

    # ─── bootstrap ───────────────────────────────────────────────────────────
    print("[main] بررسی ابزارها...")
    try:
        from bootstrap import ensure_bootstrap
        apkeditor = Path(os.getenv("APKEDITOR_JAR", "tools/APKEditor.jar"))
        await ensure_bootstrap(apkeditor)
        print("[main] ✅ ابزارها آماده‌اند.\n")
    except Exception as exc:
        print(f"[main] ⚠️  bootstrap خطا داشت: {exc}")
        print("[main]    ادامه می‌دیم — ممکنه دانلود بعداً خطا بده.\n")

    # ─── شروع process‌ها ─────────────────────────────────────────────────────
    group = ProcessGroup(
        {
            "telegram": TELEGRAM_SCRIPT,
            "rubika": RUBIKA_SCRIPT,
        }
    )
    group.start_all()
    print()
    print("[main] هر دو ربات در حال اجرا هستند.")
    print("[main] برای توقف Ctrl+C بزن.\n")

    try:
        await group.monitor_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[main] در حال توقف...")
        group.stop_all()
        print("[main] خداحافظ!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
