#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
#  setup.sh — نصب و راه‌اندازی APK Downloader Bot
#  اجرا: bash setup.sh
# ═══════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
err()  { echo -e "${RED}❌ $*${NC}"; exit 1; }
info() { echo -e "${BLUE}➤  $*${NC}"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    APK Downloader Bot — نصب خودکار      ║"
echo "╚══════════════════════════════════════════╝"
echo ""

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ─── ۱. بررسی Python ──────────────────────────────────────────────────────────
info "بررسی Python..."
if command -v python3 &>/dev/null; then
    PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    ok "Python $PYVER پیدا شد"
    # بررسی نسخه حداقل 3.9
    python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" \
        || err "Python 3.9+ لازم داری. نسخه فعلی: $PYVER"
else
    err "Python3 پیدا نشد. نصب: sudo apt install -y python3 python3-pip python3-venv"
fi

# ─── ۲. بررسی Java ────────────────────────────────────────────────────────────
info "بررسی Java..."
if command -v java &>/dev/null; then
    JAVAVER=$(java -version 2>&1 | head -1)
    ok "Java پیدا شد: $JAVAVER"
else
    warn "Java پیدا نشد. بدون Java، split APKها ترکیب نمی‌شن."
    warn "نصب: sudo apt install -y openjdk-17-jre-headless"
fi

# ─── ۳. بررسی rubika_auth_helper.py ──────────────────────────────────────────
info "بررسی rubika_auth_helper.py..."
if [ -f "rubika_auth_helper.py" ]; then
    ok "rubika_auth_helper.py پیدا شد"
else
    warn "rubika_auth_helper.py پیدا نشد!"
    echo ""
    echo "  این فایل رو از ریپوی Walrus کپی کن:"
    echo "  https://github.com/rezaaa/walrus/blob/main/rubika_auth_helper.py"
    echo ""
    echo "  یا با wget:"
    echo "  wget https://raw.githubusercontent.com/rezaaa/walrus/main/rubika_auth_helper.py"
    echo ""
    read -r -p "  الان دانلود کنم؟ [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        if command -v wget &>/dev/null; then
            wget -q "https://raw.githubusercontent.com/rezaaa/walrus/main/rubika_auth_helper.py" \
                && ok "rubika_auth_helper.py دانلود شد" \
                || err "دانلود ناموفق بود. دستی کپی کن."
        elif command -v curl &>/dev/null; then
            curl -sO "https://raw.githubusercontent.com/rezaaa/walrus/main/rubika_auth_helper.py" \
                && ok "rubika_auth_helper.py دانلود شد" \
                || err "دانلود ناموفق بود. دستی کپی کن."
        else
            err "wget و curl هیچ‌کدام پیدا نشدند. دستی کپی کن."
        fi
    fi
fi

# ─── ۴. virtualenv ────────────────────────────────────────────────────────────
info "ساخت virtualenv..."
if [ ! -d "venv" ]; then
    python3 -m venv venv || err "ساخت venv ناموفق. نصب: sudo apt install -y python3-venv"
    ok "venv ساخته شد"
else
    ok "venv از قبل وجود داره"
fi

# activate
# shellcheck disable=SC1091
source venv/bin/activate

# ─── ۵. نصب packages ─────────────────────────────────────────────────────────
info "نصب packages..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "packages نصب شدند"

# ─── ۶. فایل .env ─────────────────────────────────────────────────────────────
info "بررسی .env..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env ساخته شد — باید پرش کنی!"
    echo ""
    echo "  فایل .env رو باز کن و مقادیر زیر رو وارد کن:"
    echo ""
    echo "  API_ID      → از https://my.telegram.org"
    echo "  API_HASH    → از https://my.telegram.org"
    echo "  BOT_TOKEN   → از @BotFather در تلگرام"
    echo ""
    read -r -p "  الان .env رو ویرایش کنم؟ [Y/n] " ans
    if [[ ! "$ans" =~ ^[Nn]$ ]]; then
        "${EDITOR:-nano}" .env
    fi
else
    ok ".env از قبل وجود داره"
fi

# بررسی اینکه API_ID و API_HASH و BOT_TOKEN پر شدن
source .env 2>/dev/null || true
if [ -z "${API_ID:-}" ] || [ "${API_ID}" = "your_api_id" ]; then
    warn "API_ID هنوز پر نشده — قبل از اجرا باید .env رو کامل کنی"
fi
if [ -z "${BOT_TOKEN:-}" ] || [ "${BOT_TOKEN}" = "your_bot_token" ]; then
    warn "BOT_TOKEN هنوز پر نشده — قبل از اجرا باید .env رو کامل کنی"
fi

# ─── ۷. تنظیم gplaydl ─────────────────────────────────────────────────────────
info "بررسی gplaydl..."
if venv/bin/python -c "import gplaydl" &>/dev/null; then
    ok "gplaydl نصب شده"

    # بررسی auth (gplaydl v2 از auth-*.json در ~/.config/gplaydl استفاده می‌کنه)
    AUTH_DIR="$HOME/.config/gplaydl"
    LEGACY_CRED="$HOME/.gplaydl/credentials.json"
    if ls "$AUTH_DIR"/auth-*.json &>/dev/null || [ -f "$LEGACY_CRED" ]; then
        ok "gplaydl auth پیدا شد — تنظیم شده"
    else
        warn "gplaydl هنوز احراز هویت نشده!"
        echo ""
        echo "  باید یه بار این دستور رو اجرا کنی:"
        echo ""
        echo "  source venv/bin/activate && gplaydl auth"
        echo ""
        echo "  توکن ناشناس (anonymous) می‌گیره — نیازی به اکانت گوگل نیست."
        echo "  بعدش می‌تونی گوگل پلی رو دانلود کنی."
        echo ""
        read -r -p "  الان auth بگیرم؟ [Y/n] " ans
        if [[ ! "$ans" =~ ^[Nn]$ ]]; then
            echo "  در حال گرفتن anonymous token از Aurora OSS..."
            venv/bin/gplaydl auth && {
                ok "auth موفق بود"
                echo "  برای پشتیبانی از گوشی‌های ۳۲ بیتی (حالت universal) این رو هم بزن:"
                echo "  source venv/bin/activate && gplaydl auth --arch armv7"
            } || {
                warn "auth ناموفق بود — احتمالاً مشکل شبکه یا سرعت."
                echo "  بعداً دستی اجرا کن: source venv/bin/activate && gplaydl auth"
                echo "  اگه باز هم ناموفق بود، dispenser دیگه‌ای امتحان کن:"
                echo "  gplaydl auth --dispenser https://auroraoss.com/api/auth"
            }
        fi
    fi
else
    warn "gplaydl نصب نشده — bootstrap موقع اجرا نصبش می‌کنه"
fi

# ─── ۸. ساخت پوشه‌ها ──────────────────────────────────────────────────────────
info "ساخت پوشه‌های لازم..."
mkdir -p downloads/rub tools
ok "پوشه‌ها آماده‌اند"

# ─── خلاصه ────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo ""
ok "نصب کامل شد!"
echo ""
echo "  برای اجرا:"
echo ""
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
echo "  بعد از اجرا، توی ربات تلگرام:"
echo "  /set_rubika  ←  تنظیم حساب روبیکا"
echo ""
echo "═══════════════════════════════════════════════"
