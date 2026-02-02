"""
Конфигурация бота SWAGA VPN.
Загрузка переменных окружения и констант.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
]

# ── 3X-UI Panel ───────────────────────────────────────────────────────────────
XUI_HOST: str = os.getenv("XUI_HOST", "")
XUI_PORT: str = os.getenv("XUI_PORT", "443")
# Пользователь может указать путь с /panel на конце (как в браузере).
# 3X-UI root path НЕ включает /panel — это часть внутренних маршрутов панели.
_raw_web_path: str = os.getenv("XUI_WEB_PATH", "").rstrip("/")
XUI_WEB_PATH: str = _raw_web_path.removesuffix("/panel")
XUI_USER: str = os.getenv("XUI_USERNAME", "")
XUI_PASS: str = os.getenv("XUI_PASSWORD", "")
INBOUND_ID: int = int(os.getenv("INBOUND_ID", "1"))

# ── YooKassa (stub) ──────────────────────────────────────────────────────────
YOOKASSA_ID: str = os.getenv("YOOKASSA_ACCOUNT_ID", "")
YOOKASSA_KEY: str = os.getenv("YOOKASSA_SECRET_KEY", "")

# ── VPN connection ───────────────────────────────────────────────────────────
# VPN_HOST — публичный IP или домен сервера (для клиентского подключения)
VPN_HOST: str = os.getenv("VPN_HOST", "")
VPN_PORT: int = int(os.getenv("VPN_PORT", "19571"))

# ── XHTTP transport ─────────────────────────────────────────────────────────
VPN_TRANSPORT: str = os.getenv("VPN_TRANSPORT", "xhttp")
VPN_PATH: str = os.getenv("VPN_PATH", "/adv")
VPN_CAMOUFLAGE_HOST: str = os.getenv("VPN_CAMOUFLAGE_HOST", "yandex.ru")
VPN_XHTTP_MODE: str = os.getenv("VPN_XHTTP_MODE", "packet-up")

# ── Reality ──────────────────────────────────────────────────────────────────
REALITY_PUBLIC_KEY: str = os.getenv("REALITY_PUBLIC_KEY", "")
REALITY_SHORT_ID: str = os.getenv("REALITY_SHORT_ID", "")
REALITY_FINGERPRINT: str = os.getenv("REALITY_FINGERPRINT", "chrome")
REALITY_SNI: str = os.getenv("REALITY_SNI", "web.de")
REALITY_SPIDERX: str = os.getenv("REALITY_SPIDERX", "/")

# ── Links ─────────────────────────────────────────────────────────────────────
SUPPORT_URL: str = os.getenv("SUPPORT_URL", "https://t.me/swagasupport_bot")
SUB_BASE_URL: str = os.getenv("SUB_BASE_URL", "https://sub.swaga-vpn.ru/sub/")
SUB_LISTEN_PORT: int = int(os.getenv("SUB_LISTEN_PORT", "8888"))

# ── Subscription plans ────────────────────────────────────────────────────────
PLANS: dict = {
    "trial": {"name": "Пробный", "days": 7, "price": 0},
    "1m":    {"name": "1 месяц", "days": 30, "price": 130},
    "3m":    {"name": "3 месяца", "days": 90, "price": 350},
    "1y":    {"name": "1 год", "days": 365, "price": 800},
}

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DATABASE_PATH", "./vpn_bot.db")
BACKUP_DIR: str = os.getenv("BACKUP_PATH", "./backups")
