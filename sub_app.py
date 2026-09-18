"""
Lightweight subscription server for VPN clients (V2RayTun, v2rayN, etc.).

Serves base64-encoded VLESS links at /sub/{sub_id}.
Replaces 3X-UI's broken built-in subscription service that returns 127.0.0.1.
"""

import base64
import logging
from datetime import datetime
from urllib.parse import quote

# RSA публичные ключи Happ Plus для deeplink шифрования
_HAPP_PUBLIC_KEY_V4 = """\
-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA3UZ0M3L4K+WjM3vkbQnz
ozHg/cRbEXvQ6i4A8RVN4OM3rK9kU01FdjyoIgywve8OEKsFnVwERZAQZ1Trv60B
hmaM76QQEE+EUlIOL9EpwKWGtTL5lYC1sT9XJMNP3/CI0gP5wwQI88cY/xedpOEB
W72EmOOShHUm/b/3m+HPmqwc4ugKj5zWV5SyiT829aFA5DxSjmIIFBAms7DafmSq
LFTYIQL5cShDY2u+/sqyAw9yZIOoqW2TFIgIHhLPWek/ocDU7zyOrlu1E0SmcQQb
LFqHq02fsnH6IcqTv3N5Adb/CkZDDQ6HvQVBmqbKZKf7ZdXkqsc/Zw27xhG7OfXC
tUmWsiL7zA+KoTd3avyOh93Q9ju4UQsHthL3Gs4vECYOCS9dsXXSHEY/1ngU/hjO
WFF8QEE/rYV6nA4PTyUvo5RsctSQL/9DJX7XNh3zngvif8LsCN2MPvx6X+zLouBX
zgBkQ9DFfZAGLWf9TR7KVjZC/3NsuUCDoAOcpmN8pENBbeB0puiKMMWSvll36+2M
YR1Xs0MgT8Y9TwhE2+TnnTJOhzmHi/BxiUlY/w2E0s4ax9GHAmX0wyF4zeV7kDkc
vHuEdc0d7vDmdw0oqCqWj0Xwq86HfORu6tm1A8uRATjb4SzjTKclKuoElVAVa5Jo
oh/uZMozC65SmDw+N5p6Su8CAwEAAQ==
-----END PUBLIC KEY-----"""


def _create_happ_deeplink(subscription_url: str) -> str | None:
    """Шифрует URL подписки RSA публичным ключом Happ и возвращает deeplink."""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric import padding as _padding
        public_key = load_pem_public_key(_HAPP_PUBLIC_KEY_V4.encode())
        encrypted = public_key.encrypt(subscription_url.encode(), _padding.PKCS1v15())
        b64 = base64.b64encode(encrypted).decode()
        return f"happ://crypt4/{b64}"
    except Exception as e:
        logging.getLogger(__name__).warning("Happ deeplink generation failed: %s", e)
        return None

from aiohttp import web

from config import (
    VPN_HOST, VPN_PORT, VPN_TRANSPORT, VPN_PATH,
    VPN_CAMOUFLAGE_HOST, VPN_XHTTP_MODE,
    REALITY_PUBLIC_KEY, REALITY_SHORT_ID, REALITY_FINGERPRINT,
    REALITY_SNI, REALITY_SPIDERX,
    SUB_LISTEN_PORT, SUB_BASE_URL, SUPPORT_URL,
)
from database import get_sub_by_xui_id
from utils import build_vless_link, format_date
from servers import server_manager, PROTECTED_SERVER_IDS

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

# Флаги и названия стран
LOCATION_FLAGS = {
    "DE": "🇩🇪", "NL": "🇳🇱", "EE": "🇪🇪", "US": "🇺🇸", "FI": "🇫🇮",
    "FR": "🇫🇷", "GB": "🇬🇧", "LV": "🇱🇻", "RU": "🇷🇺", "KZ": "🇰🇿",
    "CH": "🇨🇭", "JP": "🇯🇵", "CA": "🇨🇦",
}


def get_server_config(server_id: str) -> dict:
    """Получить настройки сервера по ID. Возвращает дефолтные если не найден."""
    if not server_manager.servers:
        server_manager.load_config()

    srv = server_manager.get_server(server_id) if server_id else None

    if srv and (srv.reality_pbk or getattr(srv, "transport", "") == "ws"):
        return {
            "host": srv.host,
            "port": srv.vpn_port,
            "transport": srv.transport or VPN_TRANSPORT,
            "path": srv.transport_path or VPN_PATH,
            "camouflage_host": srv.transport_host or VPN_CAMOUFLAGE_HOST,
            "xhttp_mode": srv.xhttp_mode or VPN_XHTTP_MODE,
            "flow": srv.flow or "",
            "reality_pbk": srv.reality_pbk,
            "reality_sid": srv.reality_sid,
            "reality_fp": srv.reality_fp or REALITY_FINGERPRINT,
            "reality_sni": srv.reality_sni,
            "flag": LOCATION_FLAGS.get(srv.location, "🌐"),
            "location": srv.location,
        }

    # Дефолтные настройки из .env
    return {
        "host": VPN_HOST,
        "port": VPN_PORT,
        "transport": VPN_TRANSPORT,
        "path": VPN_PATH,
        "camouflage_host": VPN_CAMOUFLAGE_HOST,
        "xhttp_mode": VPN_XHTTP_MODE,
        "flow": "",
        "reality_pbk": REALITY_PUBLIC_KEY,
        "reality_sid": REALITY_SHORT_ID,
        "reality_fp": REALITY_FINGERPRINT,
        "reality_sni": REALITY_SNI,
        "flag": "🇩🇪",
        "location": "DE",
    }


@routes.get("/health")
async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint for monitoring."""
    return web.Response(
        text="OK",
        content_type="text/plain",
        status=200,
        headers={"X-Service": "SWAGA-VPN-Subscription-Server"}
    )


@routes.get("/sub/{sub_id}")
async def handle_subscription(request: web.Request) -> web.Response:
    """Return base64-encoded VLESS links for all enabled servers."""
    sub_id = request.match_info["sub_id"]

    sub = await get_sub_by_xui_id(sub_id)
    if not sub or not sub.get("vless_uuid"):
        return web.Response(status=404, text="subscription not found")

    if not sub.get("is_active"):
        return web.Response(status=403, text="subscription expired")

    # Загружаем конфигурацию серверов если не загружена
    if not server_manager.servers:
        server_manager.load_config()

    # Получаем все включенные серверы
    enabled_servers = [
        s for s in server_manager.get_all_servers()
        if s.enabled and s.id not in PROTECTED_SERVER_IDS
    ]

    if not enabled_servers:
        # Fallback на дефолтный сервер если нет включенных
        logger.warning("No enabled servers found, using default config")
        server_id = sub.get("server_id", "")
        cfg = get_server_config(server_id)

        end_date_str = format_date(sub["end_date"]) if sub.get("end_date") else ""
        flag = cfg["flag"]
        remark = f"{flag} SWAGA VPN - до {end_date_str}" if end_date_str else f"{flag} SWAGA VPN"

        vless_link = build_vless_link(
            uuid_str=sub["vless_uuid"],
            host=cfg["host"],
            port=cfg["port"],
            transport=cfg["transport"],
            path=cfg["path"],
            camouflage_host=cfg["camouflage_host"],
            xhttp_mode=cfg["xhttp_mode"],
            reality_pbk=cfg["reality_pbk"],
            reality_sid=cfg["reality_sid"],
            reality_fp=cfg["reality_fp"],
            reality_sni=cfg["reality_sni"],
            reality_spx=REALITY_SPIDERX,
            remark=remark,
            flow=cfg["flow"],
        )
        encoded = base64.b64encode(vless_link.encode()).decode()
    else:
        # Генерируем VLESS ссылки для всех включенных серверов
        vless_links = []
        end_date_str = format_date(sub["end_date"]) if sub.get("end_date") else ""

        for server in enabled_servers:
            cfg = get_server_config(server.id)
            flag = cfg["flag"]

            # Формируем уникальное название для каждого сервера
            server_name = server.name if hasattr(server, 'name') else server.location
            remark = f"{flag} SWAGA {server_name} - до {end_date_str}" if end_date_str else f"{flag} SWAGA {server_name}"

            vless_link = build_vless_link(
                uuid_str=sub["vless_uuid"],
                host=cfg["host"],
                port=cfg["port"],
                transport=cfg["transport"],
                path=cfg["path"],
                camouflage_host=cfg["camouflage_host"],
                xhttp_mode=cfg["xhttp_mode"],
                reality_pbk=cfg["reality_pbk"],
                reality_sid=cfg["reality_sid"],
                reality_fp=cfg["reality_fp"],
                reality_sni=cfg["reality_sni"],
                reality_spx=REALITY_SPIDERX,
                remark=remark,
                flow=cfg["flow"],
            )
            vless_links.append(vless_link)

        # Объединяем все ссылки с переносом строки (стандарт для V2Ray подписок)
        all_links = "\n".join(vless_links)
        encoded = base64.b64encode(all_links.encode()).decode()

    # Вычисляем expire timestamp для V2RayTun
    expire_ts = 0
    if sub.get("end_date"):
        try:
            end_dt = sub["end_date"]
            if isinstance(end_dt, str):
                end_dt = datetime.fromisoformat(end_dt)
            expire_ts = int(end_dt.timestamp())
        except (ValueError, TypeError):
            expire_ts = 0

    # Лимит трафика: 100 ГБ = 107374182400 байт (0 = безлимит)
    total_bytes = 107374182400

    return web.Response(
        text=encoded,
        content_type="text/plain",
        headers={
            "subscription-userinfo": f"upload=0; download=0; total={total_bytes}; expire={expire_ts}",
            "profile-update-interval": "12",
            "profile-title": "SWAGA VPN",
            "profile-web-page-url": "https://t.me/Swaga_vpnbot",
            "content-disposition": "attachment; filename=SWAGA-VPN",
        },
    )


CONNECT_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SWAGA VPN</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         text-align: center; padding: 30px 16px; background: #0d1117; color: #e6edf3;
         margin: 0; }}
  h2 {{ margin: 0 0 6px; font-size: 22px; }}
  .logo {{ font-size: 40px; margin-bottom: 8px; }}
  .step {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px;
           padding: 16px; margin: 14px auto; max-width: 380px; text-align: left; }}
  .step-num {{ display: inline-block; width: 28px; height: 28px; line-height: 28px;
               border-radius: 50%; background: #238636; color: #fff; text-align: center;
               font-weight: 700; font-size: 14px; margin-right: 8px; flex-shrink: 0; }}
  .step-row {{ display: flex; align-items: center; margin-bottom: 6px; }}
  .step-text {{ font-size: 15px; }}
  .btn {{ display: block; margin: 14px auto; padding: 16px 28px; border-radius: 12px;
          text-decoration: none; font-size: 17px; font-weight: 600; cursor: pointer;
          border: none; max-width: 380px; width: 100%; text-align: center; }}
  .btn-primary {{ background: #238636; color: #fff; }}
  .btn-primary:active {{ background: #1a7f37; }}
  .btn-happ {{ background: #7c3aed; color: #fff; }}
  .btn-happ:active {{ background: #6d28d9; }}
  .btn-hiddify {{ background: #0284c7; color: #fff; }}
  .btn-hiddify:active {{ background: #0369a1; }}
  .btn-karing {{ background: #059669; color: #fff; }}
  .btn-karing:active {{ background: #047857; }}
  .btn-singbox {{ background: #7c3aed; color: #fff; }}
  .btn-singbox:active {{ background: #6d28d9; }}
  .btn-incy {{ background: #6c5ce7; color: #fff; }}
  .btn-incy:active {{ background: #5a4bd1; }}
  .btn-secondary {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d; }}
  .btn-app {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d;
              display: inline-block; width: auto; margin: 6px; padding: 12px 20px;
              font-size: 14px; border-radius: 10px; text-decoration: none; }}
  .apps {{ margin-top: 16px; }}
  .hint {{ color: #8b949e; font-size: 13px; margin-top: 8px; }}
  .hidden {{ display: none; }}
  .or {{ color: #8b949e; font-size: 14px; margin: 10px 0; }}
  .tabs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
           max-width: 380px; margin: 12px auto 4px; }}
  .tab {{ padding: 12px 8px; font-size: 13px; font-weight: 700; cursor: pointer;
          background: #161b22; border: 2px solid #30363d; border-radius: 12px;
          color: #8b949e; transition: all .2s; text-align: center; line-height: 1.3; }}
  .tab:last-child:nth-child(odd) {{ grid-column: 1 / -1; }}
  .tab.active {{ border-color: currentColor; background: #21262d; color: #e6edf3; }}
  .tab[data-app="v2raytun"].active {{ border-color: #2563eb; color: #60a5fa; background: #0d1f3c; }}
  .tab[data-app="happ"].active    {{ border-color: #7c3aed; color: #a78bfa; background: #1a0d3c; }}
  .tab[data-app="karing"].active  {{ border-color: #059669; color: #34d399; background: #0d2e22; }}
  .tab[data-app="hiddify"].active {{ border-color: #0284c7; color: #38bdf8; background: #0d2233; }}
  .tab[data-app="singbox"].active {{ border-color: #9333ea; color: #c084fc; background: #1e0d3c; }}
  .tab[data-app="incy"].active   {{ border-color: #6c5ce7; color: #a78bfa; background: #1a0d3c; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
</style>
</head>
<body>

<div id="tg-warning" style="display:none; background:#7c3a00; border:1px solid #f59e0b; border-radius:10px; padding:12px 14px; margin:0 auto 16px; max-width:380px; font-size:13px; color:#fde68a; text-align:left;">
  &#x26A0;&#xFE0F; <b>Страница открыта внутри Telegram.</b><br>
  Кнопки «Добавить подписку» не работают из встроенного браузера.<br><br>
  Нажмите <b>«&#xB7;&#xB7;&#xB7;»</b> (три точки) → <b>«Открыть в браузере»</b> — и повторите.
</div>

<div class="logo">&#x26A1;</div>
<h2>SWAGA VPN</h2>
<p style="color:#8b949e; margin-top:4px;">Быстрое подключение</p>
<a href="https://t.me/Swaga_vpnbot" style="display:block; max-width:380px; margin:14px auto 0; padding:12px 16px; background:#1c2d3d; border:1px solid #1f6feb; border-radius:12px; text-decoration:none; text-align:center;">
  <span style="font-size:13px; color:#8b949e; display:block; margin-bottom:2px;">Управление подпиской и оплата</span>
  <span style="font-size:16px; font-weight:700; color:#58a6ff;">🚀 @Swaga_vpnbot</span>
</a>

<div style="display:flex; align-items:center; justify-content:space-between; max-width:380px; margin:10px auto 0; padding:12px 16px; background:#161b22; border:1px solid {status_color}40; border-radius:12px;">
  <span style="font-size:14px; color:#e6edf3;">{status_icon} <b>{status_text}</b></span>
  <span style="font-size:13px; color:#8b949e;">{days_text}</span>
</div>

<p style="color:#8b949e; font-size:12px; text-transform:uppercase; letter-spacing:.5px; margin:20px auto 6px; max-width:380px; text-align:left;">Выберите приложение</p>
<div class="tabs">
  <button class="tab active" data-app="v2raytun" onclick="switchTab('v2raytun', this)">🚀 V2RayTun</button>
  <button class="tab" data-app="happ" onclick="switchTab('happ', this)">🟣 Happ Plus</button>
  <button class="tab" data-app="karing" onclick="switchTab('karing', this)">🟢 Karing</button>
  <button class="tab" data-app="hiddify" onclick="switchTab('hiddify', this)">🔵 Hiddify</button>
  <button class="tab" data-app="singbox" onclick="switchTab('singbox', this)">⚡ sing-box</button>
  <button class="tab" data-app="incy" onclick="switchTab('incy', this)">🟣 INCY</button>
</div>

<!-- ── V2RayTun ── -->
<div id="tab-v2raytun" class="tab-content active">
  <a class="btn btn-primary" href="{deeplink}">
    &#x1F680; Добавить подписку в V2RayTun
  </a>
  <p class="hint">Нажмите, чтобы автоматически добавить VPN</p>

  <p class="or">— или —</p>

  <button class="btn btn-secondary" id="copyBtn" onclick="copyConfig()">
    &#x1F4CB; Скопировать конфиг вручную
  </button>
  <p class="hint" id="copyHint"></p>

  <div class="step">
    <p style="color:#8b949e; font-size:14px; margin:0 0 10px;">Если автоматически не открылось:</p>
    <div class="step-row"><span class="step-num">1</span>
      <span class="step-text">Нажмите <b>«Скопировать конфиг»</b></span></div>
    <div class="step-row"><span class="step-num">2</span>
      <span class="step-text">Откройте <b>V2RayTun</b></span></div>
    <div class="step-row"><span class="step-num">3</span>
      <span class="step-text">Приложение предложит <b>импортировать</b></span></div>
  </div>

  <div class="apps">
    <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Нет приложения? Скачайте:</p>
    <a class="btn btn-app" href="https://apps.apple.com/app/v2raytun/id6476628951">iOS</a>
    <a class="btn btn-app" href="https://play.google.com/store/apps/details?id=com.v2raytun.android">Android</a>
    <p style="color:#f59e0b; font-size:12px; margin-top:10px;">⚠️ iOS: приложение удалено из App Store РФ. Смените регион Apple ID на Казахстан или Турцию и скачайте повторно.</p>
  </div>
</div>

<!-- ── Happ Plus ── -->
<div id="tab-happ" class="tab-content">
  <a class="btn btn-happ" href="{happ_deeplink}">
    &#x1F7E3; Добавить подписку в Happ Plus
  </a>
  <p class="hint">Нажмите, чтобы автоматически добавить все серверы в Happ Plus</p>

  <p class="or">— или —</p>

  <button class="btn btn-secondary" onclick="copyConfigAndOpenHapp(this)">
    &#x1F4CB; Скопировать конфиг вручную
  </button>
  <p class="hint" id="happHint">Откройте Happ Plus → «+» → «Вставить из буфера»</p>

  <div class="step">
    <p style="color:#8b949e; font-size:14px; margin:0 0 10px;">Если автоматически не открылось:</p>
    <div class="step-row"><span class="step-num">1</span>
      <span class="step-text">Нажмите <b>«Скопировать конфиг»</b></span></div>
    <div class="step-row"><span class="step-num">2</span>
      <span class="step-text">Откройте <b>Happ Plus</b> → нажмите <b>«+»</b></span></div>
    <div class="step-row"><span class="step-num">3</span>
      <span class="step-text">Выберите <b>«Вставить из буфера»</b></span></div>
  </div>

  <div class="apps">
    <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Нет приложения? Скачайте:</p>
    <a class="btn btn-app" href="https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973">iOS</a>
    <a class="btn btn-app" href="https://play.google.com/store/apps/details?id=com.happproxy.app">Android</a>
  </div>
</div>

<!-- ── Karing ── -->
<div id="tab-karing" class="tab-content">
  <a class="btn btn-karing" href="{karing_deeplink}">
    &#x1F7E2; Добавить подписку в Karing
  </a>
  <p class="hint">Нажмите, чтобы автоматически добавить все серверы в Karing</p>

  <p class="or">— или —</p>

  <button class="btn btn-secondary" onclick="copySubUrl('copyHintKaring', this)">
    &#x1F4CB; Скопировать ссылку подписки
  </button>
  <p class="hint" id="copyHintKaring"></p>

  <div class="step">
    <p style="color:#8b949e; font-size:14px; margin:0 0 10px;">Если автоматически не открылось:</p>
    <div class="step-row"><span class="step-num">1</span>
      <span class="step-text">Нажмите <b>«Скопировать ссылку»</b></span></div>
    <div class="step-row"><span class="step-num">2</span>
      <span class="step-text">Откройте <b>Karing</b> → нажмите <b>«+»</b></span></div>
    <div class="step-row"><span class="step-num">3</span>
      <span class="step-text">Выберите <b>«Из буфера обмена»</b> и подтвердите</span></div>
  </div>

  <div class="apps">
    <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Нет приложения? Скачайте:</p>
    <a class="btn btn-app" href="https://apps.apple.com/us/app/karing/id6472431552">iOS</a>
    <a class="btn btn-app" href="https://karing.app/en/download/">Android APK</a>
  </div>
</div>

<!-- ── Hiddify ── -->
<div id="tab-hiddify" class="tab-content">
  <a class="btn btn-hiddify" href="{hiddify_deeplink}">
    &#x1F535; Добавить подписку в Hiddify
  </a>
  <p class="hint">⚠️ Полностью закройте Hiddify перед нажатием — иначе не откроется</p>

  <p class="or">— или —</p>

  <button class="btn btn-secondary" onclick="copySubUrl('copyHintHiddify', this)">
    &#x1F4CB; Скопировать ссылку подписки
  </button>
  <p class="hint" id="copyHintHiddify"></p>

  <div class="step">
    <p style="color:#8b949e; font-size:14px; margin:0 0 10px;">Если автоматически не открылось:</p>
    <div class="step-row"><span class="step-num">1</span>
      <span class="step-text">Нажмите <b>«Скопировать ссылку»</b></span></div>
    <div class="step-row"><span class="step-num">2</span>
      <span class="step-text">Откройте <b>Hiddify</b> → <b>Новый профиль</b></span></div>
    <div class="step-row"><span class="step-num">3</span>
      <span class="step-text">Вставьте ссылку и нажмите <b>«Добавить»</b></span></div>
  </div>

  <div class="apps">
    <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Нет приложения? Скачайте:</p>
    <a class="btn btn-app" href="https://apps.apple.com/app/hiddify/id6596777532">iOS</a>
    <a class="btn btn-app" href="https://play.google.com/store/apps/details?id=app.hiddify.com">Android</a>
  </div>
</div>

<!-- ── INCY ── -->
<div id="tab-incy" class="tab-content">
  <a class="btn btn-incy" href="{incy_deeplink}">
    &#x1F7E3; Добавить подписку в INCY
  </a>
  <p class="hint">Нажмите, чтобы автоматически добавить все серверы в INCY</p>

  <p class="or">— или —</p>

  <button class="btn btn-secondary" onclick="copySubUrl('copyHintIncy', this)">
    &#x1F4CB; Скопировать ссылку подписки
  </button>
  <p class="hint" id="copyHintIncy"></p>

  <div class="step">
    <p style="color:#8b949e; font-size:14px; margin:0 0 10px;">Если автоматически не открылось:</p>
    <div class="step-row"><span class="step-num">1</span>
      <span class="step-text">Нажмите <b>«Скопировать ссылку»</b></span></div>
    <div class="step-row"><span class="step-num">2</span>
      <span class="step-text">Откройте <b>INCY</b> → нажмите <b>«+»</b></span></div>
    <div class="step-row"><span class="step-num">3</span>
      <span class="step-text">Выберите <b>«Добавить подписку»</b> → вставьте ссылку</span></div>
  </div>

  <div class="apps">
    <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Нет приложения? Скачайте:</p>
    <a class="btn btn-app" href="https://apps.apple.com/ru/app/incy/id6756943388">iOS</a>
    <a class="btn btn-app" href="https://play.google.com/store/apps/details?id=llc.itdev.incy">Android</a>
  </div>
</div>

<!-- ── sing-box ── -->
<div id="tab-singbox" class="tab-content">
  <a class="btn btn-singbox" href="{singbox_deeplink}">
    &#x1F7E3; Добавить подписку в sing-box
  </a>
  <p class="hint">Нажмите, чтобы автоматически добавить все серверы в sing-box</p>

  <p class="or">— или —</p>

  <button class="btn btn-secondary" onclick="copySubUrl('copyHintSingbox', this)">
    &#x1F4CB; Скопировать ссылку подписки
  </button>
  <p class="hint" id="copyHintSingbox"></p>

  <div class="step">
    <p style="color:#8b949e; font-size:14px; margin:0 0 10px;">Если автоматически не открылось:</p>
    <div class="step-row"><span class="step-num">1</span>
      <span class="step-text">Нажмите <b>«Скопировать ссылку»</b></span></div>
    <div class="step-row"><span class="step-num">2</span>
      <span class="step-text">Откройте <b>sing-box</b> → нажмите <b>«+»</b></span></div>
    <div class="step-row"><span class="step-num">3</span>
      <span class="step-text">Выберите <b>«Удалённый профиль»</b> → вставьте ссылку</span></div>
  </div>

  <div class="apps">
    <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Нет приложения? Скачайте:</p>
    <a class="btn btn-app" href="https://apps.apple.com/app/sing-box/id6451272673">iOS</a>
    <a class="btn btn-app" href="https://play.google.com/store/apps/details?id=io.nekohasekai.sfa">Android</a>
  </div>
</div>

<input type="text" id="configData" value="{vless_link}" class="hidden">
<input type="text" id="subUrlData" value="{sub_url}" class="hidden">
<script>var happAllConfigs = {happ_links};</script>

<script>
function switchTab(name, el) {{
  document.querySelectorAll('.tab-content').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
}}

function copyConfig() {{
  var config = document.getElementById('configData').value;
  var btn = document.getElementById('copyBtn');
  var hint = document.getElementById('copyHint');
  copyText(config, btn, hint, 'Откройте V2RayTun — он предложит импорт');
}}

function copySubUrl(hintId, btn) {{
  var url = document.getElementById('subUrlData').value;
  var hint = document.getElementById(hintId);
  copyText(url, btn, hint, 'Вставьте ссылку в приложение');
}}

function copyConfigAndOpenHapp(btn) {{
  var config = happAllConfigs;
  var hint = document.getElementById('happHint');
  function onCopied() {{
    btn.innerHTML = '&#x2705; Конфиг скопирован!';
    hint.textContent = 'Теперь откройте Happ Plus — он предложит импорт';
  }}
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(config).then(onCopied).catch(function() {{
      var inp = document.createElement('textarea');
      inp.value = config; document.body.appendChild(inp); inp.select();
      try {{ document.execCommand('copy'); onCopied(); }} catch(e) {{
        hint.textContent = 'Не удалось скопировать — попробуйте вручную';
      }}
      document.body.removeChild(inp);
    }});
  }} else {{
    var inp = document.createElement('textarea');
    inp.value = config; document.body.appendChild(inp); inp.select();
    try {{ document.execCommand('copy'); onCopied(); }} catch(e) {{
      hint.textContent = 'Не удалось скопировать — попробуйте вручную';
    }}
    document.body.removeChild(inp);
  }}
}}

function copyText(text, btn, hint, successHint) {{
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(function() {{
      btn.innerHTML = '&#x2705; Скопировано!';
      if (hint) hint.textContent = successHint;
    }}).catch(function() {{ fallback(text, btn, hint, successHint); }});
  }} else {{
    fallback(text, btn, hint, successHint);
  }}
}}

function fallback(text, btn, hint, successHint) {{
  var inp = document.createElement('textarea');
  inp.value = text;
  document.body.appendChild(inp);
  inp.select();
  try {{
    document.execCommand('copy');
    btn.innerHTML = '&#x2705; Скопировано!';
    if (hint) hint.textContent = successHint;
  }} catch(e) {{
    if (hint) hint.textContent = 'Скопируйте вручную';
  }}
  document.body.removeChild(inp);
}}

// Определяем Telegram WebView и показываем предупреждение
(function() {{
  var isTg = typeof window.TelegramWebviewProxy !== 'undefined'
    || (typeof window.Telegram !== 'undefined' && window.Telegram.WebApp)
    || /\bTelegram\b/i.test(navigator.userAgent);
  if (isTg) {{
    document.getElementById('tg-warning').style.display = 'block';
  }}
}})();
</script>
<div style="max-width:380px; margin:28px auto 0; text-align:left;">
  <p style="color:#8b949e; font-size:12px; text-transform:uppercase; letter-spacing:.5px; margin-bottom:12px;">Какое приложение выбрать?</p>

  <!-- iOS -->
  <div style="background:#161b22; border:1px solid #30363d; border-radius:12px; padding:14px 16px; margin-bottom:10px;">
    <p style="margin:0 0 10px; font-size:14px; font-weight:600; color:#e6edf3;">📱 iPhone / iPad (iOS)</p>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0; border-bottom:1px solid #21262d;">
      <div>
        <span style="color:#e6edf3; font-size:14px; font-weight:500;">INCY</span>
        <span style="margin-left:6px; font-size:11px; background:#064e1e; color:#4caf50; padding:2px 7px; border-radius:20px;">App Store РФ</span>
      </div>
      <a href="https://apps.apple.com/ru/app/incy/id6756943388" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0; border-bottom:1px solid #21262d;">
      <div>
        <span style="color:#e6edf3; font-size:14px; font-weight:500;">Happ Plus</span>
        <span style="margin-left:6px; font-size:11px; background:#064e1e; color:#4caf50; padding:2px 7px; border-radius:20px;">App Store РФ</span>
      </div>
      <a href="https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0; border-bottom:1px solid #21262d;">
      <div>
        <span style="color:#e6edf3; font-size:14px; font-weight:500;">Karing</span>
        <span style="margin-left:6px; font-size:11px; background:#064e1e; color:#4caf50; padding:2px 7px; border-radius:20px;">App Store РФ</span>
      </div>
      <a href="https://apps.apple.com/us/app/karing/id6472431552" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0;">
      <div>
        <span style="color:#8b949e; font-size:14px; font-weight:500;">V2RayTun</span>
        <span style="margin-left:6px; font-size:11px; background:#3a1f00; color:#f59e0b; padding:2px 7px; border-radius:20px;">Смена региона</span>
      </div>
      <a href="https://apps.apple.com/app/v2raytun/id6476628951" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
    <p style="margin:8px 0 0; font-size:12px; color:#8b949e;">⚠️ V2RayTun удалён из App Store РФ. Для скачивания смените регион Apple ID на Казахстан или Турцию.</p>
  </div>

  <!-- Android -->
  <div style="background:#161b22; border:1px solid #30363d; border-radius:12px; padding:14px 16px; margin-bottom:10px;">
    <p style="margin:0 0 10px; font-size:14px; font-weight:600; color:#e6edf3;">📱 Android</p>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0; border-bottom:1px solid #21262d;">
      <div>
        <span style="color:#e6edf3; font-size:14px; font-weight:500;">INCY</span>
        <span style="margin-left:6px; font-size:11px; background:#064e1e; color:#4caf50; padding:2px 7px; border-radius:20px;">Google Play</span>
      </div>
      <a href="https://play.google.com/store/apps/details?id=llc.itdev.incy" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0; border-bottom:1px solid #21262d;">
      <div>
        <span style="color:#e6edf3; font-size:14px; font-weight:500;">Hiddify</span>
        <span style="margin-left:6px; font-size:11px; background:#064e1e; color:#4caf50; padding:2px 7px; border-radius:20px;">Google Play</span>
      </div>
      <a href="https://play.google.com/store/apps/details?id=app.hiddify.com" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0;">
      <div>
        <span style="color:#e6edf3; font-size:14px; font-weight:500;">Karing</span>
        <span style="margin-left:6px; font-size:11px; background:#3a1f00; color:#f59e0b; padding:2px 7px; border-radius:20px;">APK</span>
      </div>
      <a href="https://karing.app/en/download/" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
  </div>

  <!-- Desktop -->
  <div style="background:#161b22; border:1px solid #30363d; border-radius:12px; padding:14px 16px; margin-bottom:10px;">
    <p style="margin:0 0 10px; font-size:14px; font-weight:600; color:#e6edf3;">💻 Windows / macOS</p>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0; border-bottom:1px solid #21262d;">
      <span style="color:#e6edf3; font-size:14px; font-weight:500;">v2rayN <span style="color:#8b949e; font-weight:400;">(Windows)</span></span>
      <a href="https://github.com/2dust/v2rayN/releases" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0;">
      <span style="color:#e6edf3; font-size:14px; font-weight:500;">v2rayU <span style="color:#8b949e; font-weight:400;">(macOS)</span></span>
      <a href="https://github.com/yanue/V2rayU/releases" style="color:#58a6ff; font-size:13px; text-decoration:none;">Скачать</a>
    </div>
    <p style="margin:8px 0 0; font-size:12px; color:#8b949e;">Скопируйте ссылку подписки в боте → «Импорт из буфера обмена» в приложении.</p>
  </div>

</div>

<p style="color:#8b949e; font-size:13px; margin-top:16px;">Вопросы: <a href="https://t.me/Swaga_vpnbot" style="color:#58a6ff; text-decoration:none;">@Swaga_vpnbot</a></p>
</body>
</html>"""


@routes.get("/connect/{sub_id}")
async def handle_connect(request: web.Request) -> web.Response:
    """HTML page that auto-opens V2RayTun with subscription URL containing all servers."""
    sub_id = request.match_info["sub_id"]

    sub = await get_sub_by_xui_id(sub_id)
    if not sub or not sub.get("vless_uuid"):
        return web.Response(status=404, text="subscription not found")

    if not sub.get("is_active"):
        return web.Response(status=403, text="subscription expired")

    # Загружаем конфигурацию серверов если не загружена
    if not server_manager.servers:
        server_manager.load_config()

    # Получаем все включенные не-защищённые серверы
    enabled_servers = [
        s for s in server_manager.get_all_servers()
        if s.enabled and s.id not in PROTECTED_SERVER_IDS
    ]

    # Формируем список VLESS ссылок для отображения
    vless_links = []
    end_date_str = format_date(sub["end_date"]) if sub.get("end_date") else ""

    if not enabled_servers:
        # Fallback на дефолтный сервер
        server_id = sub.get("server_id", "")
        cfg = get_server_config(server_id)
        flag = cfg["flag"]
        remark = f"{flag} SWAGA VPN - до {end_date_str}" if end_date_str else f"{flag} SWAGA VPN"

        vless_link = build_vless_link(
            uuid_str=sub["vless_uuid"],
            host=cfg["host"],
            port=cfg["port"],
            transport=cfg["transport"],
            path=cfg["path"],
            camouflage_host=cfg["camouflage_host"],
            xhttp_mode=cfg["xhttp_mode"],
            reality_pbk=cfg["reality_pbk"],
            reality_sid=cfg["reality_sid"],
            reality_fp=cfg["reality_fp"],
            reality_sni=cfg["reality_sni"],
            reality_spx=REALITY_SPIDERX,
            remark=remark,
            flow=cfg["flow"],
        )
        vless_links.append(vless_link)
    else:
        for server in enabled_servers:
            cfg = get_server_config(server.id)
            flag = cfg["flag"]
            server_name = server.name if hasattr(server, 'name') else server.location
            remark = f"{flag} SWAGA {server_name} - до {end_date_str}" if end_date_str else f"{flag} SWAGA {server_name}"

            vless_link = build_vless_link(
                uuid_str=sub["vless_uuid"],
                host=cfg["host"],
                port=cfg["port"],
                transport=cfg["transport"],
                path=cfg["path"],
                camouflage_host=cfg["camouflage_host"],
                xhttp_mode=cfg["xhttp_mode"],
                reality_pbk=cfg["reality_pbk"],
                reality_sid=cfg["reality_sid"],
                reality_fp=cfg["reality_fp"],
                reality_sni=cfg["reality_sni"],
                reality_spx=REALITY_SPIDERX,
                remark=remark,
                flow=cfg["flow"],
            )
            vless_links.append(vless_link)

    # Используем URL подписки для deeplink (все клиенты загрузят все серверы автоматически)
    sub_url = f"{SUB_BASE_URL}{sub_id}"
    deeplink = f"v2raytun://import/{sub_url}"
    hiddify_deeplink = f"hiddify://import/{sub_url}#SWAGA+VPN"
    karing_deeplink = f"karing://install-config?url={quote(sub_url, safe='')}&name=SWAGA+VPN"
    happ_deeplink = _create_happ_deeplink(sub_url) or ""
    singbox_deeplink = f"sing-box://import-remote-profile?url={quote(sub_url, safe='')}"
    incy_deeplink = f"incy://import/{sub_url}"

    # Для ручного копирования показываем первую ссылку (V2RayTun)
    first_vless_link = vless_links[0] if vless_links else ""
    # Для Happ передаём все серверы через \n (JSON-кодировка для безопасной вставки в HTML)
    import json as _json
    happ_links_json = _json.dumps("\n".join(vless_links))

    # Статус подписки
    from datetime import datetime as _dt
    is_active = bool(sub.get("is_active"))
    end_date_raw = sub.get("end_date", "")
    try:
        end_dt = _dt.fromisoformat(end_date_raw)
        days_left = max((end_dt - _dt.utcnow()).days, 0)
        end_date_display = end_dt.strftime("%d.%m.%Y")
    except Exception:
        days_left = 0
        end_date_display = "—"

    if not is_active:
        status_text = "Подписка неактивна"
        status_color = "#f44336"
        status_icon = "🔴"
        days_text = ""
    elif days_left == 0:
        status_text = "Истекает сегодня"
        status_color = "#f59e0b"
        status_icon = "🟡"
        days_text = f"до {end_date_display}"
    elif days_left <= 3:
        status_text = f"Осталось {days_left} дн."
        status_color = "#f59e0b"
        status_icon = "🟡"
        days_text = f"до {end_date_display}"
    else:
        status_text = f"Осталось {days_left} дн."
        status_color = "#4caf50"
        status_icon = "🟢"
        days_text = f"до {end_date_display}"

    html = CONNECT_HTML.format(
        vless_link=first_vless_link, sub_url=sub_url,
        deeplink=deeplink, hiddify_deeplink=hiddify_deeplink,
        karing_deeplink=karing_deeplink, happ_links=happ_links_json,
        happ_deeplink=happ_deeplink, singbox_deeplink=singbox_deeplink,
        incy_deeplink=incy_deeplink,
        status_icon=status_icon, status_text=status_text,
        status_color=status_color, days_text=days_text,
    )

    return web.Response(text=html, content_type="text/html")


# ── YooKassa Webhook ─────────────────────────────────────────────────────────

# Callback для обработки успешного платежа (будет установлен из bot.py)
_payment_success_callback = None


def set_payment_callback(callback):
    """Установить callback для обработки успешного платежа."""
    global _payment_success_callback
    _payment_success_callback = callback


@routes.post("/webhook/yookassa")
async def handle_yookassa_webhook(request: web.Request) -> web.Response:
    """
    Handle YooKassa webhook notification.

    Trust model:
      - Webhook body is an UNTRUSTED transport trigger.
      - Only payment_id is extracted from the body.
      - Entitlement fields (user_id, plan, server, amount) come exclusively
        from the local DB order that was written when the user initiated payment.
      - Payment final status, paid flag, amount, and currency are verified via
        an authoritative YooKassa API call (Payment.find_one).
      - Any verification failure is fail-closed: no fulfillment, no mutation.
      - Temporary API errors return 500 to allow YooKassa webhook retry.
    """
    try:
        body = await request.text()
        logger.info("YooKassa webhook received: %s", body[:200])

        from yookassa_payment import parse_webhook, fetch_authoritative_payment
        from database import get_payment, update_payment_status

        # 1. Minimal parse — extract notification identifiers only
        data = parse_webhook(body)
        if not data:
            logger.error("Webhook: failed to parse notification body")
            return web.Response(status=400, text="Invalid webhook")

        payment_id = data["payment_id"]
        status = data["status"]

        logger.info("Webhook: payment_id=%s status=%s", payment_id, status)

        # 2. Find local trusted order in DB
        local_payment = await get_payment(payment_id)
        if not local_payment:
            logger.warning("Webhook: unknown payment_id=%s — no local order", payment_id)
            return web.Response(status=200, text="OK")

        if status == "succeeded":
            # 3. Authoritative verification — fail-closed on any API error
            try:
                auth = fetch_authoritative_payment(payment_id)
            except Exception as e:
                logger.error(
                    "Webhook: authoritative lookup raised for payment_id=%s: %s",
                    payment_id, type(e).__name__,
                )
                return web.Response(status=500, text="Verification error")

            if auth is None:
                logger.error(
                    "Webhook: authoritative lookup returned None for payment_id=%s",
                    payment_id,
                )
                return web.Response(status=500, text="Verification error")

            # 4. Validate every security condition against the authoritative response
            from decimal import Decimal

            if auth.get("id") != payment_id:
                logger.warning(
                    "Webhook: payment_id mismatch webhook=%s api=%s",
                    payment_id, auth.get("id"),
                )
                return web.Response(status=200, text="OK")

            if auth.get("status") != "succeeded":
                logger.warning(
                    "Webhook: authoritative status=%s for payment_id=%s",
                    auth.get("status"), payment_id,
                )
                return web.Response(status=200, text="OK")

            if not auth.get("paid"):
                logger.warning(
                    "Webhook: authoritative paid=False for payment_id=%s", payment_id
                )
                return web.Response(status=200, text="OK")

            if auth.get("amount_currency") != "RUB":
                logger.warning(
                    "Webhook: unexpected currency=%s for payment_id=%s",
                    auth.get("amount_currency"), payment_id,
                )
                return web.Response(status=200, text="OK")

            try:
                auth_dec = Decimal(str(auth["amount_value"])).quantize(
                    Decimal("0.01"))
                local_dec = Decimal(str(local_payment["amount"])).quantize(
                    Decimal("0.01"))
            except Exception as e:
                logger.error(
                    "Webhook: amount parse error for payment_id=%s: %s",
                    payment_id, type(e).__name__,
                )
                return web.Response(status=200, text="OK")

            if auth_dec != local_dec:
                logger.warning(
                    "Webhook: amount mismatch for payment_id=%s auth=%s local=%s",
                    payment_id, auth_dec, local_dec,
                )
                return web.Response(status=200, text="OK")

            # 5. All checks passed — entitlement from LOCAL DB, not webhook body
            from datetime import datetime
            paid_at = datetime.utcnow().isoformat()

            if not _payment_success_callback:
                logger.error("Webhook: payment success callback not set — returning 503 for retry")
                return web.Response(status=503, text="Service unavailable")

            await _payment_success_callback(
                payment_id=payment_id,
                user_id=local_payment["user_id"],    # LOCAL DB
                plan_key=local_payment["plan_key"],  # LOCAL DB
                server_id=local_payment["server_id"],# LOCAL DB
                amount=local_payment["amount"],       # LOCAL DB
                paid_at=paid_at,
            )

        elif status == "canceled":
            # Authoritative verification — same fail-closed pattern as succeeded path
            try:
                auth = fetch_authoritative_payment(payment_id)
            except Exception as e:
                logger.error(
                    "Webhook: canceled: authoritative lookup raised for payment_id=%s: %s",
                    payment_id, type(e).__name__,
                )
                return web.Response(status=500, text="Verification error")

            if auth is None:
                logger.error(
                    "Webhook: canceled: authoritative lookup returned None for payment_id=%s",
                    payment_id,
                )
                return web.Response(status=500, text="Verification error")

            if auth.get("id") != payment_id:
                logger.warning(
                    "Webhook: canceled: payment_id mismatch webhook=%s api=%s",
                    payment_id, auth.get("id"),
                )
                return web.Response(status=200, text="OK")

            if auth.get("status") != "canceled":
                logger.warning(
                    "Webhook: canceled: authoritative status=%s for payment_id=%s, not canceled",
                    auth.get("status"), payment_id,
                )
                return web.Response(status=200, text="OK")

            # Refuse to downgrade an already-succeeded payment
            if local_payment.get("status") == "succeeded":
                logger.warning(
                    "Webhook: canceled: refusing to downgrade succeeded payment_id=%s",
                    payment_id,
                )
                return web.Response(status=200, text="OK")

            await update_payment_status(payment_id, "canceled")

        return web.Response(status=200, text="OK")

    except Exception as e:
        logger.error("Error processing webhook: %s", type(e).__name__)
        return web.Response(status=500, text="Internal error")


# ── Server lifecycle ─────────────────────────────────────────────────────────

_runner: web.AppRunner | None = None


async def start_sub_server() -> None:
    """Start the subscription HTTP server."""
    global _runner
    app = web.Application()
    app.add_routes(routes)
    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "127.0.0.1", SUB_LISTEN_PORT)
    await site.start()
    logger.info("Subscription server started on 127.0.0.1:%s", SUB_LISTEN_PORT)


async def stop_sub_server() -> None:
    """Stop the subscription HTTP server."""
    global _runner
    if _runner:
        await _runner.cleanup()
        _runner = None
        logger.info("Subscription server stopped")
