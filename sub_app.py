"""
Lightweight subscription server for VPN clients (V2RayTun, v2rayN, etc.).

Serves base64-encoded VLESS links at /sub/{sub_id}.
Replaces 3X-UI's broken built-in subscription service that returns 127.0.0.1.
"""

import base64
import logging
from datetime import datetime
from urllib.parse import quote

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
from servers import server_manager

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

# Флаги и названия стран
LOCATION_FLAGS = {
    "DE": "🇩🇪", "NL": "🇳🇱", "EE": "🇪🇪", "US": "🇺🇸", "FI": "🇫🇮",
    "FR": "🇫🇷", "GB": "🇬🇧", "LV": "🇱🇻", "RU": "🇷🇺", "KZ": "🇰🇿",
}


def get_server_config(server_id: str) -> dict:
    """Получить настройки сервера по ID. Возвращает дефолтные если не найден."""
    if not server_manager.servers:
        server_manager.load_config()

    srv = server_manager.get_server(server_id) if server_id else None

    if srv and srv.reality_pbk:
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
    enabled_servers = [s for s in server_manager.get_all_servers() if s.enabled]

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
            "profile-web-page-url": SUPPORT_URL,
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
  .btn-secondary {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d; }}
  .btn-app {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d;
              display: inline-block; width: auto; margin: 6px; padding: 12px 20px;
              font-size: 14px; border-radius: 10px; }}
  .apps {{ margin-top: 16px; }}
  .hint {{ color: #8b949e; font-size: 13px; margin-top: 8px; }}
  .hidden {{ display: none; }}
  .or {{ color: #8b949e; font-size: 14px; margin: 10px 0; }}
</style>
</head>
<body>

<div class="logo">&#x26A1;</div>
<h2>SWAGA VPN</h2>
<p style="color:#8b949e; margin-top:4px;">Быстрое подключение</p>

<a class="btn btn-primary" id="openAppBtn" href="{deeplink}">
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
</div>

<input type="text" id="configData" value="{vless_link}" class="hidden">

<script>
function copyConfig() {{
  var config = document.getElementById('configData').value;
  var btn = document.getElementById('copyBtn');
  var hint = document.getElementById('copyHint');

  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(config).then(function() {{
      btn.innerHTML = '&#x2705; Скопировано!';
      hint.textContent = 'Откройте V2RayTun — он предложит импорт';
    }}).catch(fallbackCopy);
  }} else {{
    fallbackCopy();
  }}

  function fallbackCopy() {{
    var inp = document.getElementById('configData');
    inp.classList.remove('hidden');
    inp.select();
    try {{
      document.execCommand('copy');
      btn.innerHTML = '&#x2705; Скопировано!';
      hint.textContent = 'Откройте V2RayTun — он предложит импорт';
    }} catch(e) {{
      hint.textContent = 'Выделите текст ниже и скопируйте вручную';
    }}
  }}
}}
</script>
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

    # Получаем все включенные серверы
    enabled_servers = [s for s in server_manager.get_all_servers() if s.enabled]

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

    # Используем URL подписки для deeplink (V2RayTun автоматически загрузит все серверы)
    sub_url = f"{SUB_BASE_URL}{sub_id}"
    deeplink = f"v2raytun://import/{sub_url}"

    # Для ручного копирования показываем первую ссылку (пользователь может импортировать подписку через URL)
    first_vless_link = vless_links[0] if vless_links else ""

    html = CONNECT_HTML.format(vless_link=first_vless_link, sub_url=sub_url, deeplink=deeplink)

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
    """Обработка webhook от YooKassa."""
    try:
        body = await request.text()
        logger.info("YooKassa webhook received: %s", body[:500])

        from yookassa_payment import parse_webhook
        from database import get_payment, update_payment_status

        data = parse_webhook(body)
        if not data:
            logger.error("Failed to parse webhook")
            return web.Response(status=400, text="Invalid webhook")

        payment_id = data["payment_id"]
        event = data["event"]
        status = data["status"]

        logger.info(
            "Webhook: event=%s, payment_id=%s, status=%s, user=%s",
            event, payment_id, status, data.get("user_id")
        )

        # Проверяем, что платёж существует в нашей БД
        payment = await get_payment(payment_id)
        if not payment:
            logger.warning("Payment not found in DB: %s", payment_id)
            # Всё равно возвращаем 200, чтобы YooKassa не повторяла запрос
            return web.Response(status=200, text="OK")

        # Обновляем статус платежа
        if status == "succeeded":
            from datetime import datetime
            await update_payment_status(payment_id, "succeeded", datetime.utcnow().isoformat())

            # Вызываем callback для активации подписки
            if _payment_success_callback:
                await _payment_success_callback(
                    user_id=data["user_id"],
                    plan_key=data["plan_key"],
                    server_id=data["server_id"],
                    amount=data["amount"],
                )
            else:
                logger.warning("Payment success callback not set!")

        elif status == "canceled":
            await update_payment_status(payment_id, "canceled")

        return web.Response(status=200, text="OK")

    except Exception as e:
        logger.error("Error processing webhook: %s", e)
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
