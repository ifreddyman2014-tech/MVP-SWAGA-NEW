"""
Admin handlers for SWAGA VPN bot.

All commands require the caller to be in settings.admin_id_list.

Commands:
    /giveaccess USER_ID DAYS    — Create or extend subscription for a user
    /user_extend USER_ID DAYS   — Extend existing subscription
    /user_info USER_ID          — Show user info and subscription status
    /servers                    — List all servers with status
    /broadcast TEXT             — Send a message to all active subscribers
    /keygen DAYS                — Create giveaway key (7/30/90/365) and return subscription link
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

GIVEAWAY_ID_BASE = 9_000_000_000
KEYGEN_ALLOWED_DAYS = {7, 30, 90, 365}

from ...config import settings
from ...database.models import Key, Server, Subscription, User
from ...services.xui import ThreeXUIClient
from .user import generate_keys_for_subscription

logger = logging.getLogger(__name__)

router = Router(name="admin_router")


# ============== Admin guard ==============

def is_admin(telegram_id: int) -> bool:
    """Return True if the user is an admin."""
    return telegram_id in settings.admin_id_list


# ============== /giveaccess ==============

@router.message(Command("giveaccess"))
async def cmd_giveaccess(message: Message, session: AsyncSession):
    """
    /giveaccess USER_ID DAYS

    Give (or extend) a subscription for USER_ID.
    - If user has an active subscription → extend expiry_date by DAYS.
    - If no subscription → create a new paid_admin one and sync keys to all servers.
    """
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 3 or not parts[1].lstrip("-").isdigit() or not parts[2].isdigit():
        await message.answer(
            "⚠️ Использование: <code>/giveaccess USER_ID DAYS</code>\n"
            "Пример: <code>/giveaccess 123456789 30</code>"
        )
        return

    target_id = int(parts[1])
    days = int(parts[2])

    if days <= 0:
        await message.answer("❌ Количество дней должно быть больше 0.")
        return

    # Find or create user
    result = await session.execute(select(User).where(User.telegram_id == target_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(telegram_id=target_id, username=None)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info(f"Admin created new user: {target_id}")

    # Check for active subscription
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .where(Subscription.is_active == True)
        .where(Subscription.expiry_date > datetime.utcnow())
        .order_by(Subscription.expiry_date.desc())
    )
    sub = result.scalar_one_or_none()

    if sub:
        # Extend existing subscription
        old_expiry = sub.expiry_date
        new_expiry = old_expiry + timedelta(days=days)
        sub.expiry_date = new_expiry
        await session.commit()
        await session.refresh(sub)

        # Update expiry on all panels
        expiry_ms = int(new_expiry.timestamp() * 1000)
        await _update_keys_expiry(user, sub, expiry_ms, session)

        await message.answer(
            f"✅ <b>Подписка продлена</b>\n\n"
            f"👤 User ID: <code>{target_id}</code>\n"
            f"📅 Было до: <b>{old_expiry.strftime('%d.%m.%Y')}</b>\n"
            f"📅 Стало до: <b>{new_expiry.strftime('%d.%m.%Y')}</b>\n"
            f"➕ Добавлено: <b>{days} дн.</b>"
        )
        logger.info(f"Admin extended sub for user {target_id} by {days} days")

        # Notify user
        try:
            from ...main import bot as tg_bot
            await tg_bot.send_message(
                target_id,
                f"🎁 <b>Ваша подписка SwagaVPN продлена!</b>\n\n"
                f"✅ Активна до: <b>{new_expiry.strftime('%d.%m.%Y')}</b>"
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_id}: {e}")

    else:
        # Create new subscription
        new_expiry = datetime.utcnow() + timedelta(days=days)
        sub = Subscription(
            user_id=user.id,
            is_active=True,
            expiry_date=new_expiry,
            plan_type="paid_admin",
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)

        # Generate keys on all servers
        await message.answer("⏳ Создаю ключи на серверах...")
        try:
            vless_links = await generate_keys_for_subscription(user, sub, new_expiry, session)
            keys_count = len(vless_links)
        except Exception as e:
            logger.error(f"Failed to generate keys for {target_id}: {e}")
            await message.answer(f"⚠️ Подписка создана, но ключи не сгенерированы: {e}")
            keys_count = 0

        await message.answer(
            f"✅ <b>Подписка создана</b>\n\n"
            f"👤 User ID: <code>{target_id}</code>\n"
            f"📅 Активна до: <b>{new_expiry.strftime('%d.%m.%Y')}</b>\n"
            f"⏱ Дней: <b>{days}</b>\n"
            f"🔑 Ключей создано: <b>{keys_count}</b>"
        )
        logger.info(f"Admin gave access to user {target_id} for {days} days, {keys_count} keys")

        # Notify user
        try:
            from ...main import bot as tg_bot
            await tg_bot.send_message(
                target_id,
                f"🎁 <b>Вам выдан доступ к SwagaVPN!</b>\n\n"
                f"✅ Активен до: <b>{new_expiry.strftime('%d.%m.%Y')}</b>\n\n"
                f"Нажми /start чтобы получить свои ключи."
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_id}: {e}")


# ============== /user_extend ==============

@router.message(Command("user_extend"))
async def cmd_user_extend(message: Message, session: AsyncSession):
    """
    /user_extend USER_ID DAYS

    Extend an existing active subscription by DAYS.
    """
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 3 or not parts[1].lstrip("-").isdigit() or not parts[2].isdigit():
        await message.answer(
            "⚠️ Использование: <code>/user_extend USER_ID DAYS</code>\n"
            "Пример: <code>/user_extend 123456789 30</code>"
        )
        return

    target_id = int(parts[1])
    days = int(parts[2])

    result = await session.execute(select(User).where(User.telegram_id == target_id))
    user = result.scalar_one_or_none()
    if not user:
        await message.answer(f"❌ Пользователь <code>{target_id}</code> не найден.")
        return

    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .where(Subscription.is_active == True)
        .order_by(Subscription.expiry_date.desc())
    )
    sub = result.scalar_one_or_none()
    if not sub:
        await message.answer(
            f"❌ У пользователя <code>{target_id}</code> нет активной подписки.\n"
            "Используй /giveaccess для создания."
        )
        return

    old_expiry = sub.expiry_date
    new_expiry = max(old_expiry, datetime.utcnow()) + timedelta(days=days)
    sub.expiry_date = new_expiry
    await session.commit()
    await session.refresh(sub)

    expiry_ms = int(new_expiry.timestamp() * 1000)
    await _update_keys_expiry(user, sub, expiry_ms, session)

    await message.answer(
        f"✅ <b>Подписка продлена</b>\n\n"
        f"👤 User ID: <code>{target_id}</code>\n"
        f"📅 Было до: <b>{old_expiry.strftime('%d.%m.%Y')}</b>\n"
        f"📅 Стало до: <b>{new_expiry.strftime('%d.%m.%Y')}</b>"
    )

    try:
        from ...main import bot as tg_bot
        await tg_bot.send_message(
            target_id,
            f"🎁 <b>Ваша подписка SwagaVPN продлена!</b>\n\n"
            f"✅ Активна до: <b>{new_expiry.strftime('%d.%m.%Y')}</b>"
        )
    except Exception as e:
        logger.warning(f"Could not notify user {target_id}: {e}")


# ============== /user_info ==============

@router.message(Command("user_info"))
async def cmd_user_info(message: Message, session: AsyncSession):
    """
    /user_info USER_ID

    Show information about a user and their subscription.
    """
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer(
            "⚠️ Использование: <code>/user_info USER_ID</code>"
        )
        return

    target_id = int(parts[1])

    result = await session.execute(select(User).where(User.telegram_id == target_id))
    user = result.scalar_one_or_none()
    if not user:
        await message.answer(f"❌ Пользователь <code>{target_id}</code> не найден.")
        return

    # Get all subscriptions
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc())
    )
    subs = result.scalars().all()

    active_sub = next(
        (s for s in subs if s.is_active and s.expiry_date > datetime.utcnow()),
        None
    )

    lines = [
        f"👤 <b>Пользователь</b>",
        f"ID: <code>{user.telegram_id}</code>",
        f"Username: @{user.username}" if user.username else "Username: —",
        f"UUID: <code>{user.user_uuid}</code>",
        f"Триал использован: {'✅' if user.trial_used else '❌'}",
        f"Зарегистрирован: {user.created_at.strftime('%d.%m.%Y')}",
        "",
    ]

    if active_sub:
        days_left = max((active_sub.expiry_date - datetime.utcnow()).days, 0)
        lines += [
            f"📋 <b>Активная подписка</b>",
            f"Тариф: {active_sub.plan_type}",
            f"Истекает: {active_sub.expiry_date.strftime('%d.%m.%Y')}",
            f"Осталось: {days_left} дн.",
        ]
    else:
        lines.append("📋 <b>Активной подписки нет</b>")

    lines += ["", f"📦 Всего подписок: {len(subs)}"]

    await message.answer("\n".join(lines))


# ============== /servers ==============

@router.message(Command("servers"))
async def cmd_servers(message: Message, session: AsyncSession):
    """
    /servers

    List all servers with their current status.
    """
    if not is_admin(message.from_user.id):
        return

    result = await session.execute(select(Server).order_by(Server.id))
    servers = result.scalars().all()

    if not servers:
        await message.answer("❌ Серверов не найдено.")
        return

    lines = ["🖥 <b>Серверы</b>\n"]
    for server in servers:
        status = "🟢 Активен" if server.is_active else "🔴 Отключён"
        lines.append(
            f"<b>{server.name}</b> (ID: {server.id})\n"
            f"  {status}\n"
            f"  Host: {server.host}:{server.port}\n"
            f"  Panel: {server.api_url}\n"
            f"  Inbound: {server.inbound_id}\n"
        )

    await message.answer("\n".join(lines))


# ============== /broadcast ==============

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, session: AsyncSession):
    """
    /broadcast TEXT

    Send TEXT to all users with an active subscription.
    """
    if not is_admin(message.from_user.id):
        return

    # Everything after the command word is the broadcast text
    text = message.text.partition(" ")[2].strip()
    if not text:
        await message.answer(
            "⚠️ Использование: <code>/broadcast Текст сообщения</code>"
        )
        return

    # Get all active subscribers
    result = await session.execute(
        select(User)
        .join(Subscription, Subscription.user_id == User.id)
        .where(Subscription.is_active == True)
        .where(Subscription.expiry_date > datetime.utcnow())
        .distinct()
    )
    users = result.scalars().all()

    await message.answer(f"📤 Начинаю рассылку для {len(users)} пользователей...")

    sent = 0
    failed = 0

    try:
        from ...main import bot as tg_bot
        for user in users:
            try:
                await tg_bot.send_message(user.telegram_id, text)
                sent += 1
            except Exception as e:
                logger.warning(f"Broadcast failed for {user.telegram_id}: {e}")
                failed += 1
    except Exception as e:
        await message.answer(f"❌ Ошибка рассылки: {e}")
        return

    await message.answer(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"✔️ Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}"
    )


# ============== /keygen ==============

@router.message(Command("keygen"))
async def cmd_keygen(message: Message, session: AsyncSession):
    """
    /keygen DAYS

    Create a giveaway account with a subscription for DAYS days (7/30/90/365).
    Returns a ready-to-use subscription link — no real Telegram user needed.
    """
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "⚠️ Использование: <code>/keygen DAYS</code>\n"
            "Допустимые значения: <b>7, 30, 90, 365</b>\n"
            "Пример: <code>/keygen 30</code>"
        )
        return

    days = int(parts[1])
    if days not in KEYGEN_ALLOWED_DAYS:
        await message.answer(
            f"❌ Недопустимое количество дней: <b>{days}</b>\n"
            "Разрешено: <b>7, 30, 90, 365</b>"
        )
        return

    # Find next giveaway user_id
    result = await session.execute(
        select(func.max(User.telegram_id)).where(User.telegram_id >= GIVEAWAY_ID_BASE)
    )
    last_id = result.scalar() or (GIVEAWAY_ID_BASE - 1)
    giveaway_tg_id = last_id + 1

    # Create giveaway user
    user = User(
        telegram_id=giveaway_tg_id,
        username=f"giveaway_{giveaway_tg_id}",
        trial_used=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Create subscription
    expiry = datetime.utcnow() + timedelta(days=days)
    sub = Subscription(
        user_id=user.id,
        is_active=True,
        expiry_date=expiry,
        plan_type=f"giveaway_{days}d",
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)

    # Generate keys on all servers
    await message.answer("⏳ Создаю ключи на серверах...")
    try:
        await generate_keys_for_subscription(user, sub, expiry, session)
    except Exception as e:
        logger.error(f"keygen: failed to generate keys: {e}")
        await message.answer(f"❌ Ошибка генерации ключей: {e}")
        return

    sub_url = f"{settings.webhook_base_url}/sub/{sub.sub_token}"
    connect_url = f"{settings.webhook_base_url}/connect/{sub.sub_token}"

    await message.answer(
        f"✅ <b>Гивевей-ключ создан</b>\n\n"
        f"⏱ Дней: <b>{days}</b>\n"
        f"📅 Действует до: <b>{expiry.strftime('%d.%m.%Y')}</b>\n\n"
        f"🔗 <b>Быстрое подключение:</b>\n{connect_url}\n\n"
        f"📋 <b>Ссылка на подписку:</b>\n<code>{sub_url}</code>",
        disable_web_page_preview=True,
    )
    logger.info(f"Admin {message.from_user.id} created giveaway key for {days} days, tg_id={giveaway_tg_id}")


# ============== Helper: update keys expiry on all panels ==============

async def _update_keys_expiry(
    user: User,
    sub: Subscription,
    expiry_ms: int,
    session: AsyncSession,
) -> None:
    """Update expiry time for all keys belonging to this subscription on each panel."""
    result = await session.execute(
        select(Key, Server)
        .join(Server, Key.server_id == Server.id)
        .where(Key.subscription_id == sub.id)
    )
    keys_servers = result.all()

    for key, server in keys_servers:
        try:
            xui_client = ThreeXUIClient(
                base_url=server.api_url,
                username=server.username,
                password=server.password,
                inbound_id=server.inbound_id,
                flow=server.flow,
            )
            async with xui_client.session():
                await xui_client.ensure_client(
                    uuid=key.key_uuid,
                    email=key.email,
                    expiry_ms=expiry_ms,
                )
            key.last_sync_at = datetime.utcnow()
            key.sync_error = None
            await session.commit()
            logger.info(f"Updated expiry on server {server.name} for user {user.telegram_id}")
        except Exception as e:
            logger.error(f"Failed to update expiry on {server.name} for {user.telegram_id}: {e}")
            key.sync_error = str(e)[:500]
            await session.commit()
