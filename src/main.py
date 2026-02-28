"""
SWAGA VPN Bot - Main entry point.

Combines:
- Telegram bot (aiogram 3.x with polling)
- FastAPI webhook server for YooKassa payments
- Background tasks for subscription reminders
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from fastapi import FastAPI, HTTPException, Request, Depends
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
