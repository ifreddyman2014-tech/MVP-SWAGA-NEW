"""
Lightweight subscription server for VPN clients (V2RayTun, v2rayN, etc.).

Serves base64-encoded VLESS links at /sub/{sub_id}.
Replaces 3X-UI's broken built-in subscription service that returns 127.0.0.1.
"""

import base64
import logging

from aiohttp import web

from config import (
    VPN_HOST, VPN_PORT, VPN_TRANSPORT, VPN_PATH,
    VPN_CAMOUFLAGE_HOST, VPN_XHTTP_MODE,
    REALITY_PUBLIC_KEY, REALITY_SHORT_ID, REALITY_FINGERPRINT,
    REALITY_SNI, REALITY_SPIDERX,
    SUB_LISTEN_PORT,
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
