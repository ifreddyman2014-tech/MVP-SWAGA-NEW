"""
SWAGA VPN Bot - Main entry point.

Combines:
- Telegram bot (aiogram 3.x with polling)
- FastAPI webhook server for YooKassa payments
- Background tasks for subscription reminders
"""

import asyncio
import base64
import logging
import sys
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import Response, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uvicorn

from .bot.handlers.admin import router as admin_router
from .bot.handlers.user import router as user_router
from .config import settings
from .database import init_db, close_db, get_session
from .services.payment import YooKassaService

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", mode="a"),
    ],
)

# Reduce noise from libraries
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.INFO)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ============== Aiogram DB Middleware ==============

class DbSessionMiddleware(BaseMiddleware):
    """Inject AsyncSession into every aiogram handler as 'session'."""

    async def __call__(self, handler, event, data):
        from .database import get_session
        async for session in get_session():
            data["session"] = session
            return await handler(event, data)


# Global bot instance
bot: Bot = None
dp: Dispatcher = None


# ============== FastAPI App ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager."""
    logger.info("Starting SWAGA VPN Bot...")

    # Initialize database
    await init_db()

    # Initialize bot
    global bot, dp
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(DbSessionMiddleware())
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Set bot commands
    await setup_bot_commands(bot)

    # Start background tasks
    asyncio.create_task(run_bot_polling())
    asyncio.create_task(subscription_reminder_loop())

    logger.info("SWAGA VPN Bot started successfully")

    yield

    # Cleanup
    logger.info("Shutting down SWAGA VPN Bot...")
    await bot.session.close()
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="SWAGA VPN Bot",
    description="Telegram VPN bot with YooKassa payment integration",
    version="2.0.0",
    lifespan=lifespan,
)


# ============== Middleware for Database Session ==============

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """Add database session to request state."""
    async for session in get_session():
        request.state.db = session
        response = await call_next(request)
        return response


# Dependency injection for session
async def get_db_session(request: Request) -> AsyncSession:
    """Get database session from request state."""
    return request.state.db


# ============== Webhook Endpoints ==============

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "swaga-vpn-bot"}


@app.get("/sub/{sub_token}")
async def subscription_feed(sub_token: str, session: AsyncSession = Depends(get_db_session)):
    """
    Subscription endpoint for V2RayTun, Happ, FlClashX, etc.

    Returns base64-encoded VLESS links with profile headers.
    V2RayTun displays profile-web-page-url as a clickable link under the subscription name.
    """
    from .database.models import Subscription, Key, Server

    result = await session.execute(
        select(Subscription).where(Subscription.sub_token == sub_token)
    )
    subscription = result.scalar_one_or_none()

    if not subscription or not subscription.is_active:
        raise HTTPException(status_code=404, detail="Subscription not found or inactive")

    # Get all keys with their servers
    result = await session.execute(
        select(Key, Server)
        .join(Server, Key.server_id == Server.id)
        .where(Key.subscription_id == subscription.id)
        .where(Server.is_active == True)
    )
    keys_servers = result.all()

    if not keys_servers:
        raise HTTPException(status_code=404, detail="No active keys found")

    # Build VLESS links
    from .bot.handlers.user import build_vless_link
    vless_links = [build_vless_link(key.key_uuid, server) for key, server in keys_servers]

    # Base64 encode
    content = base64.b64encode("\n".join(vless_links).encode()).decode()

    # Expiry as unix timestamp
    expire_ts = int(subscription.expiry_date.timestamp())

    headers = {
        "profile-title": "SWAGA VPN",
        "profile-web-page-url": f"https://t.me/{settings.bot_username}",
        "profile-update-interval": "12",
        "content-disposition": 'attachment; filename="SWAGA-VPN"',
        "subscription-userinfo": f"upload=0; download=0; total=0; expire={expire_ts}",
    }

    return Response(content=content, media_type="text/plain; charset=utf-8", headers=headers)


@app.get("/connect/{sub_token}", response_class=HTMLResponse)
async def connect_page(sub_token: str, session: AsyncSession = Depends(get_db_session)):
    """Web page for end users — subscription info + install instructions."""
    from datetime import datetime
    from .database.models import Subscription, User

    result = await session.execute(
        select(Subscription, User)
        .join(User, Subscription.user_id == User.id)
        .where(Subscription.sub_token == sub_token)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription, user = row
    sub_url = f"{settings.webhook_base_url}/sub/{sub_token}"
    import urllib.parse
    import_link = f"v2raytun://import/{urllib.parse.quote(sub_url, safe='')}"

    now = datetime.utcnow()
    is_active = subscription.is_active and subscription.expiry_date > now
    status_label = "Активна" if is_active else "Истекла"
    status_color = "#4caf50" if is_active else "#f44336"
    days_left = max((subscription.expiry_date - now).days, 0) if is_active else 0
    expiry_str = subscription.expiry_date.strftime("%d.%m.%Y")
    username_display = user.username or str(user.telegram_id)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SWAGA VPN</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f0f13;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;padding:16px}}
  .wrap{{max-width:480px;margin:0 auto}}
  header{{display:flex;align-items:center;justify-content:space-between;padding:20px 0 24px}}
  .logo{{font-size:20px;font-weight:700;color:#fff;letter-spacing:.5px}}
  .tg-link{{color:#64b5f6;text-decoration:none;font-size:14px;display:flex;align-items:center;gap:6px}}
  .card{{background:#1c1c24;border-radius:16px;padding:20px;margin-bottom:16px}}
  .card-header{{display:flex;align-items:center;gap:12px;margin-bottom:16px}}
  .status-dot{{width:10px;height:10px;border-radius:50%;background:{status_color};flex-shrink:0}}
  .card-title{{font-size:16px;font-weight:600;color:#fff}}
  .card-sub{{font-size:13px;color:#888;margin-top:2px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
  .info-box{{background:#252530;border-radius:10px;padding:14px}}
  .info-label{{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}}
  .info-value{{font-size:14px;font-weight:600;color:#e0e0e0}}
  .info-value.green{{color:{status_color}}}
  h2{{font-size:15px;font-weight:600;color:#fff;margin-bottom:14px}}
  .btn{{display:block;width:100%;padding:14px;border-radius:12px;font-size:15px;font-weight:600;text-align:center;text-decoration:none;cursor:pointer;border:none;margin-bottom:10px}}
  .btn-primary{{background:#1976d2;color:#fff}}
  .btn-outline{{background:transparent;color:#64b5f6;border:1px solid #1976d2}}
  .copy-wrap{{position:relative}}
  .copy-input{{width:100%;background:#1c1c24;border:1px solid #333;border-radius:10px;padding:12px 44px 12px 12px;color:#aaa;font-size:12px;font-family:monospace;word-break:break-all;outline:none}}
  .copy-btn{{position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;color:#64b5f6;cursor:pointer;font-size:18px;padding:4px}}
  .section{{background:#1c1c24;border-radius:16px;padding:20px;margin-bottom:16px}}
  .hint{{font-size:12px;color:#666;margin-top:8px;line-height:1.5}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="logo">&#x1F5A7; SWAGA VPN</span>
    <a class="tg-link" href="https://t.me/{settings.bot_username}" target="_blank">
      &#9992; @{settings.bot_username}
    </a>
  </header>

  <div class="card">
    <div class="card-header">
      <div class="status-dot"></div>
      <div>
        <div class="card-title">{username_display}</div>
        <div class="card-sub">Истекает через {days_left} дн.</div>
      </div>
    </div>
    <div class="grid">
      <div class="info-box">
        <div class="info-label">Имя пользователя</div>
        <div class="info-value">{username_display}</div>
      </div>
      <div class="info-box">
        <div class="info-label">Статус</div>
        <div class="info-value green">{status_label}</div>
      </div>
      <div class="info-box">
        <div class="info-label">Истекает</div>
        <div class="info-value">{expiry_str}</div>
      </div>
      <div class="info-box">
        <div class="info-label">Трафик</div>
        <div class="info-value">∞</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Установка</h2>
    <a class="btn btn-primary" href="{import_link}">+ Добавить подписку</a>
    <div class="copy-wrap">
      <input class="copy-input" id="sub-url" readonly value="{sub_url}">
      <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('sub-url').value).then(()=>this.textContent='✓')" title="Скопировать">&#x2398;</button>
    </div>
    <p class="hint">Если кнопка не сработала — скопируй ссылку и добавь вручную в настройках приложения (раздел «Подписки»).</p>
  </div>
</div>
</body>
</html>"""

    return HTMLResponse(content=html)


@app.post(settings.webhook_path)
async def yookassa_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    YooKassa payment webhook endpoint.

    Handles payment.succeeded events for automatic subscription activation.
    """
    try:
        # Get raw body for signature validation
        body = await request.body()
        body_str = body.decode("utf-8")

        # Get event data
        event_data = await request.json()

        logger.info(f"Webhook received: {event_data.get('event')}")

        # Validate signature (if configured)
        payment_service = YooKassaService()
        signature = request.headers.get("X-Webhook-Signature", "")

        if not payment_service.validate_webhook_signature(body_str, signature):
            logger.warning("Invalid webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Process webhook
        await payment_service.handle_webhook(event_data, session)

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============== Bot Setup ==============

async def setup_bot_commands(bot: Bot):
    """Set bot command menu."""
    from aiogram.types import BotCommandScopeChat

    user_commands = [
        BotCommand(command="start", description="Перезапустить"),
        BotCommand(command="buy", description="Купить подписку"),
        BotCommand(command="support", description="Поддержка"),
        BotCommand(command="rules", description="Правила пользования"),
    ]
    await bot.set_my_commands(user_commands)

    admin_commands = user_commands + [
        BotCommand(command="giveaccess", description="Выдать доступ [user_id] [days]"),
        BotCommand(command="user_extend", description="Продлить подписку [user_id] [days]"),
        BotCommand(command="user_info", description="Инфо о пользователе [user_id]"),
        BotCommand(command="servers", description="Статус серверов"),
        BotCommand(command="broadcast", description="Рассылка [текст]"),
        BotCommand(command="keygen", description="Создать гивевей-ключ [7/30/90/365]"),
    ]
    for admin_id in settings.admin_id_list:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            logger.warning(f"Could not set admin commands for {admin_id}: {e}")

    logger.info("Bot commands set successfully")


async def run_bot_polling():
    """Run bot polling in background."""
    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Bot polling error: {e}", exc_info=True)


# ============== Background Tasks ==============

async def subscription_reminder_loop():
    """
    Background task to send subscription expiry reminders.

    Checks every 15 minutes for:
    - 24h before expiry
    - Day of expiry
    - Expired subscriptions (deactivate)
    """
    from datetime import datetime, timedelta
    from sqlalchemy import select, and_

    from .database.models import Subscription, User

    logger.info("Starting subscription reminder loop...")

    while True:
        try:
            await asyncio.sleep(900)  # 15 minutes

            now = datetime.utcnow()
            tomorrow = now + timedelta(days=1)

            async for session in get_session():
                # Find subscriptions expiring in 24h
                result = await session.execute(
                    select(Subscription, User)
                    .join(User, Subscription.user_id == User.id)
                    .where(
                        and_(
                            Subscription.is_active == True,
                            Subscription.expiry_date > now,
                            Subscription.expiry_date <= tomorrow,
                            Subscription.notified_24h == False,
                        )
                    )
                )
                expiring_soon = result.all()

                for subscription, user in expiring_soon:
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            "⏰ Напоминание: завтра истекает ваша подписка SWAGA VPN.\n"
                            "Чтобы не терять доступ, продлите подписку в разделе «🔑 Ключ доступа».",
                        )
                        subscription.notified_24h = True
                        await session.commit()
                        logger.info(f"Sent 24h reminder to user {user.telegram_id}")
                    except Exception as e:
                        logger.error(f"Failed to send 24h reminder to {user.telegram_id}: {e}")

                # Find subscriptions expiring today
                today_end = now.replace(hour=23, minute=59, second=59)
                result = await session.execute(
                    select(Subscription, User)
                    .join(User, Subscription.user_id == User.id)
                    .where(
                        and_(
                            Subscription.is_active == True,
                            Subscription.expiry_date > now,
                            Subscription.expiry_date <= today_end,
                            Subscription.notified_0h == False,
                        )
                    )
                )
                expiring_today = result.all()

                for subscription, user in expiring_today:
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            "⚠️ Сегодня заканчивается ваша подписка SWAGA VPN.\n"
                            "Продлите подписку, чтобы продолжить пользоваться VPN:",
                        )
                        subscription.notified_0h = True
                        await session.commit()
                        logger.info(f"Sent expiry day reminder to user {user.telegram_id}")
                    except Exception as e:
                        logger.error(f"Failed to send expiry reminder to {user.telegram_id}: {e}")

                # Find expired subscriptions
                result = await session.execute(
                    select(Subscription, User)
                    .join(User, Subscription.user_id == User.id)
                    .where(
                        and_(
                            Subscription.is_active == True,
                            Subscription.expiry_date <= now,
                            Subscription.expired_handled == False,
                        )
                    )
                )
                expired = result.all()

                for subscription, user in expired:
                    try:
                        # Deactivate subscription
                        subscription.is_active = False
                        subscription.expired_handled = True
                        await session.commit()

                        # Notify user
                        await bot.send_message(
                            user.telegram_id,
                            "🔒 Ваша подписка SWAGA VPN завершена.\n"
                            "Хотите продолжить — оформите новую подписку в разделе «🔑 Ключ доступа».",
                        )

                        logger.info(f"Deactivated expired subscription for user {user.telegram_id}")

                        # TODO: Optionally delete keys from 3X-UI panels

                    except Exception as e:
                        logger.error(f"Failed to handle expired subscription for {user.telegram_id}: {e}")

        except Exception as e:
            logger.error(f"Subscription reminder loop error: {e}", exc_info=True)


# ============== Main Entry Point ==============

def main():
    """Run the application."""
    logger.info(f"Starting SWAGA VPN Bot v2.0.0")
    logger.info(f"Webhook URL: {settings.webhook_full_url}")
    logger.info(f"Database: {settings.database_url.split('@')[1] if '@' in settings.database_url else 'configured'}")

    uvicorn.run(
        app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
