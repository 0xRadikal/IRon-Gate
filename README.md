<div align="center">

# 🛡️ IRon-Gate

**پل امن دانلود APK از گوگل پلی به تلگرام و روبیکا**

ربات دوگانه‌ای که در روزهای محدودیت اینترنت ساخته شد تا دسترسی به برنامه‌ها قطع نشه.

کاربر لینک گوگل پلی می‌فرسته → ربات APK رو دانلود و آماده می‌کنه → روی همون پلتفرم (تلگرام یا روبیکا) برمی‌گردونه.

</div>

---

## ✨ امکانات

- 📥 **دانلود از گوگل پلی** بدون نیاز به اکانت گوگل (توکن anonymous از طریق `gplaydl` v2)
- 🌍 **خروجی Universal APK** — یک فایل که روی **همهٔ** گوشی‌ها (هم ۳۲ بیتی هم ۶۴ بیتی) نصب می‌شه
- 🔗 **دانلود از هر لینک مستقیم** (نه فقط گوگل پلی) با نوار پیشرفت زنده
- 📲 **دو پلتفرم هم‌زمان**: تلگرام (Pyrogram) و روبیکا (rubpy)
- ⚡ **آپلود سریع روبیکا** — آپلود موازی چندچانکی به‌جای آپلود سری کند
- 🗜️ **حالت ZIP اختیاری** با رمز برای دور زدن محدودیت پسوند فایل
- 🔁 **خودترمیم**: اگه یکی از ربات‌ها کرش کنه، `main.py` خودکار ری‌استارتش می‌کنه

---

## 🏗️ معماری

```
کاربر تلگرام ──→ telegram_bot.py ──┐
                                    ├──→ downloader.py ──→ APK نهایی (universal)
کاربر روبیکا ──→ rubika_bot.py ────┘         │                    │
                                          (gplaydl v2)        (APKEditor.jar)
                                              │                    │
                                    APK روی همون پلتفرم برمی‌گرده
                                    (با rubika_speedup برای آپلود سریع)
```

---

## 🚀 بهبودهای نسخهٔ جدید

| مشکل قبلی | راه‌حل |
|-----------|--------|
| **آپلود روبیکا خیلی کند بود** | ماژول `rubika_speedup.py`: فایل رو **یک‌بار** می‌خونه (به‌جای باز کردن مجدد برای هر چانک)، چانک‌ها رو **موازی** (`RUBIKA_UPLOAD_WORKERS`) آپلود می‌کنه و چانک پیش‌فرض رو به **۸ مگابایت** بزرگ می‌کنه. |
| **خروجی فقط برای یک معماری بود** | حالت `universal` در `downloader.py` بازنویسی شد: مجموعهٔ کامل arm64 + split معماری ۳۲ بیتی (armeabi-v7a) با de-dup درست بر اساس نام فایل ترکیب و با APKEditor ادغام می‌شه (دیگه `base.apk` تکراری/خراب ساخته نمی‌شه). |
| **نوار پیشرفت دانلود لینک کار نمی‌کرد** | `url_downloader.py`: پل بین thread دانلود (sync) و callback (async) با `run_coroutine_threadsafe` درست شد. |
| **bootstrap از دستور منسوخ `gplaydl setup` استفاده می‌کرد** | به `gplaydl auth` (نسخهٔ ۲) و مسیر درست `~/.config/gplaydl/auth-*.json` به‌روزرسانی شد. |

---

## 📋 پیش‌نیازها

- Python 3.10+
- Java 17+ (برای APKEditor — ترکیب split APKها)

نصب Java روی اوبونتو:
```bash
sudo apt update && sudo apt install -y openjdk-17-jre-headless
```

---

## ⚙️ نصب

```bash
git clone https://github.com/0xRadikal/IRon-Gate.git
cd IRon-Gate

# نصب خودکار (توصیه می‌شه)
bash setup.sh

# یا دستی:
python3 -m venv venv
source venv/bin/activate          # ویندوز: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
nano .env                         # تنظیمات رو پر کن
```

---

## 🔐 تنظیمات (.env)

همهٔ مقادیر در `.env.example` با توضیح کامل اومده. مهم‌ترین‌ها:

```env
API_ID=...              # از https://my.telegram.org
API_HASH=...
BOT_TOKEN=...           # از @BotFather
OWNER_TELEGRAM_ID=      # اختیاری ولی توصیه‌شده: فقط خودت دسترسی داشته باشی
RUBIKA_SESSION=rubsession
PLAY_ARCH=universal     # universal | arm64 | armv7
RUBIKA_UPLOAD_CHUNK=8388608   # ۸MB — برای آپلود سریع‌تر
RUBIKA_UPLOAD_WORKERS=4       # تعداد آپلود موازی
```

> ⚠️ **امنیت:** فایل‌های `.env` و `*.session` (حاوی توکن ورود روبیکا) هرگز نباید commit بشن — در `.gitignore` مسدود شدن.

---

## 🔑 اولین اجرا — احراز هویت gplaydl

```bash
source venv/bin/activate
gplaydl auth                  # توکن ناشناس می‌گیره (بدون اکانت گوگل)
gplaydl auth --arch armv7     # برای پشتیبانی universal از گوشی‌های ۳۲ بیتی
```

---

## ▶️ راه‌اندازی

```bash
python main.py
```

`main.py` ابزارها رو بررسی می‌کنه (APKEditor رو خودکار دانلود می‌کنه)، هر دو ربات رو به‌عنوان process جداگانه اجرا می‌کنه و در صورت کرش ری‌استارت می‌کنه.

---

## 📲 تنظیم حساب روبیکا

در ربات تلگرام `/set_rubika` رو بزن و مراحل رو دنبال کن:
1. شمارهٔ موبایل روبیکا
2. رمز حساب (اگه داشت)
3. کد OTP

بعد از این، `rubika_bot.py` خودکار session رو پیدا می‌کنه.

---

## 💡 استفاده

**گوگل پلی** — این لینک رو به ربات بفرست:
```
https://play.google.com/store/apps/details?id=org.telegram.messenger
```

**لینک مستقیم** — هر URL مستقیم فایل هم پشتیبانی می‌شه.

APK آماده‌شده روی همون پلتفرمی که ازش پیام دادی برمی‌گرده.

---

## 🧩 دستورات

| تلگرام | کار |  | روبیکا | کار |
|--------|-----|--|--------|-----|
| `/start` | وضعیت و راهنما |  | `/start` / `سلام` | خوش‌آمد |
| `/set_rubika` | تنظیم حساب روبیکا |  | لینک گوگل پلی | دانلود APK |
| `/telegram` / `/rubika` | انتخاب مقصد |  | `/help` | راهنما |
| `/help` | راهنما |  | | |

---

## 📁 ساختار فایل‌ها

```
IRon-Gate/
├── main.py                  ← نقطهٔ ورود و مدیریت process
├── telegram_bot.py          ← ربات تلگرام (Pyrogram)
├── rubika_bot.py            ← ربات روبیکا (rubpy)
├── downloader.py            ← پایپلاین دانلود + ساخت universal APK
├── url_downloader.py        ← دانلود لینک مستقیم (با پیشرفت زنده)
├── rubika_uploader.py       ← آپلود فایل به روبیکا
├── rubika_speedup.py        ← ⚡ شتاب‌دهندهٔ آپلود (آپلود موازی)
├── rubika_auth_helper.py    ← احراز هویت روبیکا
├── bootstrap.py             ← نصب خودکار gplaydl + APKEditor
├── setup.sh                 ← اسکریپت نصب
├── requirements.txt
├── .env.example
└── tools/
    └── APKEditor.jar        ← خودکار دانلود می‌شه
```

---

## 🛠️ رفع مشکل

| مشکل | راه‌حل |
|------|--------|
| `gplaydl: auth error` | `gplaydl auth` رو دوباره اجرا کن |
| APKEditor پیدا نشد | از [releases](https://github.com/REAndroid/APKEditor/releases) دانلود و در `tools/APKEditor.jar` بذار |
| session روبیکا کار نمی‌کنه | در ربات تلگرام `/set_rubika` رو بزن |
| آپلود روبیکا هنوز کنده | `RUBIKA_UPLOAD_WORKERS` و `RUBIKA_UPLOAD_CHUNK` رو در `.env` بیشتر کن |

---

## ⚖️ نکات

- فقط برنامه‌های **رایگان** قابل دانلودند؛ برنامه‌های پولی یا دارای DRM کار نمی‌کنن.
- این پروژه صرفاً برای دسترسی شخصی به برنامه‌های رایگان در شرایط محدودیت اینترنت ساخته شده.
- بخش احراز هویت روبیکا از پروژهٔ Walrus الهام گرفته شده.
