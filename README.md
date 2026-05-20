# APK Downloader Bot

ربات تلگرام + روبیکا برای دانلود APK از گوگل پلی.

کاربر لینک گوگل پلی می‌فرسته → ربات APK رو دانلود می‌کنه → همونجا (تلگرام یا روبیکا) ارسال می‌کنه.

## معماری

```
کاربر تلگرام ──→ telegram_bot.py ──┐
                                    ├──→ downloader.py ──→ APK نهایی
کاربر روبیکا ──→ rubika_bot.py ────┘         ↓               ↓
                                         (gplaydl)      (APKEditor)
                                              ↓               ↓
                                    APK برمی‌گرده به همون پلتفرم
```

## پیش‌نیازها

- Python 3.10+
- Java 17+ (برای APKEditor — ترکیب split APKها)
- یک اکانت گوگل (برای gplaydl)

نصب Java روی اوبونتو:
```bash
sudo apt update && sudo apt install -y openjdk-17-jre-headless
```

## نصب

```bash
git clone <this-repo>
cd apkdl-bot

# کپی کردن rubika_auth_helper.py از Walrus
cp /path/to/walrus/rubika_auth_helper.py .

python3 -m venv venv
source venv/bin/activate        # ویندوز: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
nano .env                       # تنظیمات رو پر کن
```

## تنظیمات (.env)

```env
API_ID=...           # از https://my.telegram.org
API_HASH=...
BOT_TOKEN=...        # از @BotFather
OWNER_TELEGRAM_ID=   # اختیاری: ID تلگرام خودت
RUBIKA_SESSION=rubsession
PLAY_ARCH=arm64
```

## اولین اجرا — تنظیم gplaydl

```bash
gplaydl setup
```
یه ایمیل گوگل و پسورد می‌خواد. بعد از setup، gplaydl توکن auth می‌سازه و ذخیره می‌کنه.

## راه‌اندازی

```bash
python main.py
```

main.py:
- ابزارها رو بررسی می‌کنه (APKEditor رو اتوماتیک دانلود می‌کنه)
- telegram_bot.py و rubika_bot.py رو به‌عنوان process جداگانه شروع می‌کنه
- اگه هر کدوم کرش کردن، ری‌استارت می‌کنه

## تنظیم حساب روبیکا

ربات تلگرام رو باز کن:
```
/set_rubika
```

مراحل:
1. شماره موبایل روبیکا رو بفرست
2. اگه رمز حساب پرسید، رمز رو بفرست
3. کد OTP رو بفرست
4. تموم! session ذخیره شد

بعد از این، rubika_bot.py اتوماتیک session رو پیدا می‌کنه.

## استفاده

**از تلگرام:**
```
https://play.google.com/store/apps/details?id=org.telegram.messenger
```
APK توی چت تلگرام برات ارسال می‌شه.

**از روبیکا:**
همون لینک رو برای حساب روبیکاِ ربات بفرست.
APK توی روبیکا بهت می‌رسه.

## دستورات تلگرام

| دستور | کار |
|-------|-----|
| `/start` | وضعیت و راهنما |
| `/set_rubika` | تنظیم حساب روبیکا |
| `/status` | وضعیت دانلودهای فعال |
| `/help` | راهنما |

## دستورات روبیکا

| پیام | کار |
|------|-----|
| `سلام` یا `/start` | خوش‌آمد |
| لینک گوگل پلی | دانلود APK |
| `/help` | راهنما |

## نکات مهم

- فقط برنامه‌های رایگان قابل دانلودند.
- بعضی برنامه‌ها DRM دارن و gplaydl نمی‌تونه دانلودشون کنه.
- split APKها اتوماتیک با APKEditor ترکیب می‌شن — Java لازم داره.
- APKEditor اتوماتیک از GitHub دانلود می‌شه اگه نبود.

## ساختار فایل‌ها

```
apkdl-bot/
├── main.py                  ← نقطه ورود
├── telegram_bot.py          ← ربات تلگرام (Pyrogram)
├── rubika_bot.py            ← ربات روبیکا (rubpy)
├── downloader.py            ← پایپلاین دانلود
├── bootstrap.py             ← نصب خودکار ابزارها
├── rubika_auth_helper.py    ← auth روبیکا (از Walrus کپی کن)
├── requirements.txt
├── .env
└── tools/
    └── APKEditor.jar        ← اتوماتیک دانلود می‌شه
```

## رفع مشکل

**gplaydl: credentials error**
```bash
gplaydl setup   # دوباره اجرا کن
```

**APKEditor پیدا نشد**
از [اینجا](https://github.com/REAndroid/APKEditor/releases) دانلود کن و توی `tools/APKEditor.jar` بذار.

**session روبیکا کار نمی‌کنه**
```
/set_rubika   # در ربات تلگرام
```

**rubika_auth_helper.py پیدا نشد**
از ریپوی [Walrus](https://github.com/rezaaa/walrus) کپی کن.
