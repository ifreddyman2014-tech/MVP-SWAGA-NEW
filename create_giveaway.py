#!/usr/bin/env python3
"""
Создание гивевей-аккаунтов SWAGA VPN (новая архитектура: PostgreSQL + SQLAlchemy).

Запуск из корня репозитория:
    python3 create_giveaway.py

Создаёт 5 аккаунтов на 1 месяц и 5 на 1 год.
Регистрирует в 3X-UI на всех активных серверах.
"""

import asyncio
import hashlib
import sys
import os
from datetime import datetime, timedelta

# Добавляем src в путь для импортов
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.database.models import Base, User, Subscription, Key, Server
from src.services.xui import ThreeXUIClient


# ── Планы гивевея ──────────────────────────────────────────────────────────────
GIVEAWAY_PLANS = [
    ("giveaway_1m",  30,  5),   # (plan_type, дней, количество)
    ("giveaway_1y", 365,  5),
]

# Фейковые Telegram ID для гивевей-аккаунтов (не конфликтуют с реальными)
GIVEAWAY_USER_ID_START = 9_000_000_000


# ── Вспомогательные функции ────────────────────────────────────────────────────

def make_email(user_uuid: str, server_id: int) -> str:
    """Непрозрачный email для 3X-UI: SHA-256(uuid:server_id)[:16]."""
    raw = f"{user_uuid}:{server_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


async def get_next_giveaway_telegram_id(session: AsyncSession) -> int:
    """Найти следующий свободный фейковый Telegram ID."""
    result = await session.execute(
        select(User.telegram_id)
        .where(User.telegram_id >= GIVEAWAY_USER_ID_START)
        .order_by(User.telegram_id.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    return (last + 1) if last else GIVEAWAY_USER_ID_START


async def create_account(
    session: AsyncSession,
    telegram_id: int,
    plan_type: str,
    days: int,
    active_servers: list[Server],
) -> dict | None:
    """Создать один гивевей-аккаунт: User + Subscription + Keys на всех серверах."""
    now = datetime.utcnow()
    expiry = now + timedelta(days=days)
    expiry_ms = int(expiry.timestamp() * 1000)

    # Создаём пользователя
    user = User(
        telegram_id=telegram_id,
        username=f"giveaway_{telegram_id}",
        trial_used=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Создаём подписку
    sub = Subscription(
        user_id=user.id,
        is_active=True,
        expiry_date=expiry,
        plan_type=plan_type,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)

    # Регистрируем на каждом сервере
    ok_servers = []
    for server in active_servers:
        email = make_email(user.user_uuid, server.id)

        # Запись в БД
        key = Key(
            subscription_id=sub.id,
            server_id=server.id,
            key_uuid=user.user_uuid,
            email=email,
        )
        session.add(key)
        await session.commit()
        await session.refresh(key)

        # Синхронизация с 3X-UI панелью
        try:
            xui = ThreeXUIClient(
                base_url=server.api_url,
                username=server.username,
                password=server.password,
                inbound_id=server.inbound_id,
                flow=server.flow,
            )
            async with xui.session():
                await xui.ensure_client(
                    uuid=user.user_uuid,
                    email=email,
                    expiry_ms=expiry_ms,
                )
            key.synced_to_panel = True
            key.last_sync_at = datetime.utcnow()
            await session.commit()
            ok_servers.append(server.name)
        except Exception as e:
            key.sync_error = str(e)[:500]
            await session.commit()
            print(f"    ⚠️  {server.name}: {e}")

    base = settings.webhook_base_url
    return {
        "telegram_id": telegram_id,
        "plan":        plan_type,
        "days":        days,
        "end_date":    expiry.strftime("%d.%m.%Y"),
        "sub_url":     f"{base}/sub/{sub.sub_token}",
        "connect_url": f"{base}/connect/{sub.sub_token}",
        "servers":     ok_servers,
    }


# ── main ───────────────────────────────────────────────────────────────────────

async def main():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Получаем активные серверы
        result = await session.execute(
            select(Server).where(Server.is_active == True).order_by(Server.id)
        )
        active_servers = result.scalars().all()

        if not active_servers:
            print("❌ Нет активных серверов в БД. Добавь серверы через migrate_legacy.py или вручную.")
            await engine.dispose()
            sys.exit(1)

        print(f"🌍 Серверы: {', '.join(s.name for s in active_servers)}\n")

        next_id = await get_next_giveaway_telegram_id(session)
        results = []

        for plan_type, days, count in GIVEAWAY_PLANS:
            label = "1 месяц" if days == 30 else "1 год"
            print(f"📦 Создаю {count} аккаунтов [{label}]...")

            for i in range(count):
                tid = next_id + i
                print(f"  [{i+1}/{count}] telegram_id={tid} ...", end=" ", flush=True)
                acc = await create_account(session, tid, plan_type, days, active_servers)
                if acc:
                    results.append(acc)
                    synced = ", ".join(acc["servers"]) or "нет"
                    print(f"✅ [{synced}]")
                else:
                    print("❌ ошибка")

            next_id += count
            print()

    await engine.dispose()

    # ── Итог ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("✅ ГОТОВЫЕ АККАУНТЫ ДЛЯ РАЗДАЧИ")
    print("=" * 60)

    for i, acc in enumerate(results, 1):
        label = "1 месяц" if acc["days"] == 30 else "1 год"
        print(f"\n{'─' * 50}")
        print(f"#{i} | {label} | до {acc['end_date']}")
        print(f"🔗 Быстрое подключение:")
        print(f"   {acc['connect_url']}")
        print(f"📋 Ссылка на подписку (для приложений):")
        print(f"   {acc['sub_url']}")

    print(f"\n{'=' * 60}")
    print(f"Итого создано: {len(results)} аккаунтов")
    print(f"  • {sum(1 for a in results if a['days'] == 30)} × 1 месяц")
    print(f"  • {sum(1 for a in results if a['days'] == 365)} × 1 год")


if __name__ == "__main__":
    asyncio.run(main())
