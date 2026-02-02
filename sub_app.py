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
          border: none; max-width: 380px; width: 100%; }}
  .btn-copy {{ background: #238636; color: #fff; }}
  .btn-copy.done {{ background: #1a7f37; }}
  .btn-app {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d;
              display: inline-block; width: auto; margin: 6px; padding: 12px 20px;
              font-size: 14px; border-radius: 10px; }}
  .apps {{ margin-top: 16px; }}
  .hint {{ color: #8b949e; font-size: 13px; margin-top: 12px; }}
  .hidden {{ display: none; }}
</style>
</head>
<body>

<div class="logo">&#x26A1;</div>
<h2>SWAGA VPN</h2>
<p style="color:#8b949e; margin-top:4px;">Быстрое подключение</p>

<button class="btn btn-copy" id="copyBtn" onclick="copyConfig()">
  &#x1F4CB; Скопировать конфиг
</button>
<p class="hint" id="copyHint"></p>

<div class="step">
  <div class="step-row"><span class="step-num">1</span>
    <span class="step-text">Нажмите <b>«Скопировать конфиг»</b></span></div>
  <div class="step-row"><span class="step-num">2</span>
    <span class="step-text">Откройте <b>V2RayTun</b></span></div>
  <div class="step-row"><span class="step-num">3</span>
    <span class="step-text">Приложение предложит <b>импортировать</b> конфиг из буфера</span></div>
  <div class="step-row"><span class="step-num">4</span>
    <span class="step-text">Нажмите <b>подключиться</b></span></div>
</div>

<div class="apps">
  <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Скачать V2RayTun:</p>
  <a class="btn btn-app" href="https://apps.apple.com/app/v2raytun/id6476628951">iOS (App Store)</a>
  <a class="btn btn-app" href="https://play.google.com/store/apps/details?id=com.v2raytun.android">Android (Google Play)</a>
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
      btn.classList.add('done');
      hint.textContent = 'Теперь откройте V2RayTun';
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
      btn.classList.add('done');
      hint.textContent = 'Теперь откройте V2RayTun';
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
