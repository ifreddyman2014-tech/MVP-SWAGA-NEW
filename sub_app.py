"""
Lightweight subscription server for VPN clients (V2RayTun, v2rayN, etc.).

Serves base64-encoded VLESS links at /sub/{sub_id}.
Replaces 3X-UI's broken built-in subscription service that returns 127.0.0.1.
"""

import base64
import logging
from urllib.parse import quote

from aiohttp import web

from config import (
    VPN_HOST, VPN_PORT, VPN_TRANSPORT, VPN_PATH,
    VPN_CAMOUFLAGE_HOST, VPN_XHTTP_MODE,
    REALITY_PUBLIC_KEY, REALITY_SHORT_ID, REALITY_FINGERPRINT,
    REALITY_SNI, REALITY_SPIDERX,
    SUB_LISTEN_PORT, SUB_BASE_URL,
)
from database import get_sub_by_xui_id
from utils import build_vless_link

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.get("/sub/{sub_id}")
async def handle_subscription(request: web.Request) -> web.Response:
    """Return base64-encoded VLESS link for the given subscription ID."""
    sub_id = request.match_info["sub_id"]

    sub = await get_sub_by_xui_id(sub_id)
    if not sub or not sub.get("vless_uuid"):
        return web.Response(status=404, text="subscription not found")

    if not sub.get("is_active"):
        return web.Response(status=403, text="subscription expired")

    vless_link = build_vless_link(
        uuid_str=sub["vless_uuid"],
        host=VPN_HOST,
        port=VPN_PORT,
        transport=VPN_TRANSPORT,
        path=VPN_PATH,
        camouflage_host=VPN_CAMOUFLAGE_HOST,
        xhttp_mode=VPN_XHTTP_MODE,
        reality_pbk=REALITY_PUBLIC_KEY,
        reality_sid=REALITY_SHORT_ID,
        reality_fp=REALITY_FINGERPRINT,
        reality_sni=REALITY_SNI,
        reality_spx=REALITY_SPIDERX,
    )

    encoded = base64.b64encode(vless_link.encode()).decode()

    return web.Response(
        text=encoded,
        content_type="text/plain",
        headers={
            "subscription-userinfo": f"upload=0; download=0; total=0; expire=0",
            "profile-update-interval": "12",
            "content-disposition": "attachment; filename=VPN-SWAGA",
        },
    )


CONNECT_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SWAGA VPN — Подключение</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
         text-align: center; padding: 40px 20px; background: #0d1117; color: #e6edf3; }}
  h2 {{ margin-bottom: 10px; }}
  .status {{ color: #58a6ff; font-size: 18px; margin: 20px 0; }}
  .btn {{ display: inline-block; margin: 8px; padding: 14px 28px; border-radius: 12px;
          text-decoration: none; font-size: 16px; font-weight: 600; }}
  .btn-primary {{ background: #238636; color: #fff; }}
  .btn-secondary {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d; }}
  .sub-url {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
              padding: 12px; margin: 20px auto; max-width: 400px; word-break: break-all;
              font-family: monospace; font-size: 13px; color: #7ee787; }}
  .hint {{ color: #8b949e; font-size: 14px; margin-top: 20px; }}
</style>
</head>
<body>
<h2>SWAGA VPN</h2>
<p class="status">Открываем приложение...</p>

<div>
  <a class="btn btn-primary" href="{vless_link}">Импорт конфига напрямую</a>
</div>

<p class="hint">Если приложение не открылось, скачайте его:</p>
<div>
  <a class="btn btn-secondary" href="https://apps.apple.com/app/v2raytun/id6476628951">V2RayTun (iOS)</a>
  <a class="btn btn-secondary" href="https://play.google.com/store/apps/details?id=com.v2raytun.android">V2RayTun (Android)</a>
</div>

<p class="hint">Или добавьте подписку вручную:</p>
<div class="sub-url">{sub_url}</div>
<p class="hint">Скопируйте ссылку выше → Откройте V2RayTun → Подписка → Вставить</p>

<script>
// Попробовать открыть VLESS-ссылку напрямую (работает если приложение установлено)
setTimeout(function() {{
    window.location.href = "{vless_link}";
}}, 500);
</script>
</body>
</html>"""


@routes.get("/connect/{sub_id}")
async def handle_connect(request: web.Request) -> web.Response:
    """HTML page that auto-opens V2RayTun with the VLESS config."""
    sub_id = request.match_info["sub_id"]

    sub = await get_sub_by_xui_id(sub_id)
    if not sub or not sub.get("vless_uuid"):
        return web.Response(status=404, text="subscription not found")

    if not sub.get("is_active"):
        return web.Response(status=403, text="subscription expired")

    vless_link = build_vless_link(
        uuid_str=sub["vless_uuid"],
        host=VPN_HOST,
        port=VPN_PORT,
        transport=VPN_TRANSPORT,
        path=VPN_PATH,
        camouflage_host=VPN_CAMOUFLAGE_HOST,
        xhttp_mode=VPN_XHTTP_MODE,
        reality_pbk=REALITY_PUBLIC_KEY,
        reality_sid=REALITY_SHORT_ID,
        reality_fp=REALITY_FINGERPRINT,
        reality_sni=REALITY_SNI,
        reality_spx=REALITY_SPIDERX,
    )

    sub_url = f"{SUB_BASE_URL}{sub_id}"
    html = CONNECT_HTML.format(vless_link=vless_link, sub_url=sub_url)

    return web.Response(text=html, content_type="text/html")


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
