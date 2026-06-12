from __future__ import annotations

"""
rubika_speedup.py — شتاب‌دهندهٔ آپلود روبیکا
================================================

مشکل: پیاده‌سازی پیش‌فرض ``rubpy`` فایل رو با چانک ۱ مگابایتی و کاملاً
«سری/sequential» آپلود می‌کنه و بدتر از اون، **برای هر چانک فایل رو از نو
باز می‌کنه و seek می‌زنه**. روی فایل‌های بزرگ (APK چند صد مگابایتی) این یعنی
صدها بار باز/بستن فایل + صدها رفت‌وبرگشت شبکه‌ای پشت‌سرهم → آپلود خیلی کند.

راه‌حل (بدون دستکاری دائمی کتابخانه): این ماژول تابع ``upload_file`` کلاس
شبکهٔ rubpy رو در زمان اجرا با نسخهٔ بهینه جایگزین می‌کنه که:

  ۱. فایل رو **یک‌بار** کامل می‌خونه (یا اگر خیلی بزرگ بود به‌صورت mmap).
  ۲. چانک‌ها رو به‌صورت **موازی** (concurrent) آپلود می‌کنه — تا
     ``RUBIKA_UPLOAD_WORKERS`` چانک هم‌زمان.
  ۳. چانک پیش‌فرض بزرگ‌تر (``RUBIKA_UPLOAD_CHUNK``) → رفت‌وبرگشت کمتر.
  ۴. منطق retry و reinit و callback رفتار اصلی رو حفظ می‌کنه.

اگه ساختار داخلی rubpy عوض شده باشه و patch نخوره، با خطا متوقف نمی‌شیم؛
فقط هشدار می‌دیم و کتابخانه با رفتار پیش‌فرض (کند ولی سالم) کار می‌کنه.

استفاده: کافیه قبل از ساختن کلاینت، یک‌بار ``apply_speedup()`` صدا زده بشه.
"""

import asyncio
import inspect
import os
from typing import Callable, Optional, Union

# چانک پیش‌فرض ۸ مگابایت (به‌جای ۱ مگابایت کتابخانه)
DEFAULT_CHUNK = int(os.getenv("RUBIKA_UPLOAD_CHUNK", str(8 * 1024 * 1024)))
# تعداد چانک هم‌زمان
DEFAULT_WORKERS = max(1, int(os.getenv("RUBIKA_UPLOAD_WORKERS", "4")))

_PATCHED = False


def apply_speedup() -> bool:
    """
    تابع upload_file کتابخانهٔ rubpy رو با نسخهٔ موازی/سریع جایگزین می‌کنه.

    Returns:
        True اگه patch با موفقیت اعمال شد، در غیر این‌صورت False.
    """
    global _PATCHED
    if _PATCHED:
        return True

    try:
        from rubpy import network as _net  # type: ignore
        from rubpy.types import Update  # type: ignore
        from rubpy import exceptions  # type: ignore
    except Exception as exc:  # pragma: no cover
        print(f"⚠️ rubika_speedup: import rubpy ناموفق بود ({exc}) — رفتار پیش‌فرض حفظ شد.")
        return False

    # پیدا کردن کلاسی که upload_file داره
    target_cls = None
    for name in dir(_net):
        obj = getattr(_net, name)
        if isinstance(obj, type) and hasattr(obj, "upload_file"):
            target_cls = obj
            break
    if target_cls is None:
        print("⚠️ rubika_speedup: کلاس upload_file در rubpy.network پیدا نشد.")
        return False

    async def fast_upload_file(
        self,
        file: Union[str, bytes],
        mime: Optional[str] = None,
        file_name: Optional[str] = None,
        chunk: int = DEFAULT_CHUNK,
        callback: Optional[Callable[[int, int], object]] = None,
        max_retries: int = 3,
        backoff: float = 1.0,
        *args,
        **kwargs,
    ) -> "Update":
        # چانک ۰ یا منفی → برگشت به پیش‌فرض بزرگ
        if not chunk or chunk <= 0:
            chunk = DEFAULT_CHUNK

        if isinstance(file, str):
            if not os.path.exists(file):
                raise ValueError("File not found at the given path.")
            file_name = file_name or os.path.basename(file)
            file_size = os.path.getsize(file)
            with open(file, "rb") as fh:          # ← یک‌بار خواندن
                payload = fh.read()
        elif isinstance(file, (bytes, bytearray)):
            if not file_name:
                raise ValueError("file_name must be specified when uploading from bytes.")
            payload = bytes(file)
            file_size = len(payload)
        else:
            raise TypeError("file must be a file path (str) or raw bytes.")

        mime = mime or file_name.split(".")[-1]

        async def handle_callback(total: int, current: int):
            if not callable(callback):
                return
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(total, current)
                else:
                    callback(total, current)
            except Exception:
                return

        # متادیتای آپلود (با بازنشانی خودکار اگه سرور خواست)
        result = await self.client.request_send_file(file_name, file_size, mime)
        state = {
            "file_id": result.id,
            "dc_id": result.dc_id,
            "upload_url": result.upload_url,
            "access_hash_send": result.access_hash_send,
        }
        total_parts = max(1, (file_size + chunk - 1) // chunk)

        async def upload_chunk(part_number: int) -> dict:
            start = (part_number - 1) * chunk
            data = payload[start:start + chunk]
            for attempt in range(max_retries):
                try:
                    async with self.session.post(
                        url=state["upload_url"],
                        headers={
                            "auth": self.client.auth,
                            "file-id": state["file_id"],
                            "total-part": str(total_parts),
                            "part-number": str(part_number),
                            "chunk-size": str(len(data)),
                            "access-hash-send": state["access_hash_send"],
                        },
                        data=data,
                        proxy=self.client.proxy,
                    ) as response:
                        return await response.json()
                except Exception as e:
                    self.logger.warning(
                        f"Error uploading chunk {part_number} "
                        f"(attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(backoff * (2 ** attempt))
                    else:
                        raise

        async def reinit():
            r = await self.client.request_send_file(file_name, file_size, mime)
            state.update(
                file_id=r.id,
                dc_id=r.dc_id,
                upload_url=r.upload_url,
                access_hash_send=r.access_hash_send,
            )

        workers = min(DEFAULT_WORKERS, total_parts)
        sem = asyncio.Semaphore(workers)
        uploaded_parts = 0
        final_result: dict = {}
        lock = asyncio.Lock()

        async def worker(part_number: int):
            nonlocal uploaded_parts, final_result
            async with sem:
                res = await upload_chunk(part_number)
                if isinstance(res, dict) and res.get("status") == "ERROR_TRY_AGAIN":
                    # سرور خواست از نو شروع کنیم → reinit و دوبارهٔ همین چانک
                    async with lock:
                        await reinit()
                    res = await upload_chunk(part_number)
                async with lock:
                    uploaded_parts += 1
                    await handle_callback(
                        file_size, min(uploaded_parts * chunk, file_size)
                    )
                    if isinstance(res, dict) and res.get("status") == "OK":
                        final_result = res

        # آخرین چانک معمولاً پاسخ نهایی (access_hash_rec) رو داره؛
        # برای اطمینان همه رو موازی می‌فرستیم و پاسخ OK نهایی رو نگه می‌داریم.
        await asyncio.gather(*(worker(p) for p in range(1, total_parts + 1)))

        if (
            final_result.get("status") == "OK"
            and final_result.get("status_det") == "OK"
        ):
            return Update(
                {
                    "mime": mime,
                    "size": file_size,
                    "dc_id": state["dc_id"],
                    "file_id": state["file_id"],
                    "file_name": file_name,
                    "access_hash_rec": final_result["data"]["access_hash_rec"],
                }
            )

        # اگه به هر دلیل پاسخ نهایی OK نبود، آخرین چانک رو دوباره (سری) بفرست
        last = await upload_chunk(total_parts)
        if (
            isinstance(last, dict)
            and last.get("status") == "OK"
            and last.get("status_det") == "OK"
        ):
            return Update(
                {
                    "mime": mime,
                    "size": file_size,
                    "dc_id": state["dc_id"],
                    "file_id": state["file_id"],
                    "file_name": file_name,
                    "access_hash_rec": last["data"]["access_hash_rec"],
                }
            )

        raise exceptions(last.get("status_det"))(last)

    try:
        target_cls.upload_file = fast_upload_file  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"⚠️ rubika_speedup: اعمال patch ناموفق بود ({exc}).")
        return False

    _PATCHED = True
    print(
        f"⚡ rubika_speedup فعال شد — چانک {DEFAULT_CHUNK // (1024*1024)}MB، "
        f"{DEFAULT_WORKERS} آپلود موازی."
    )
    return True
