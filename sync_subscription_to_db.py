#!/usr/bin/env python3
"""
Скрипт для добавления/обновления подписки в базе данных бота.

Используйте этот скрипт если вы вручную продлили подписку в x-ui панели
и хотите синхронизировать её с базой данных бота.

Usage:
    python3 sync_subscription_to_db.py <user_id> <uuid> <end_date> [--sub-id SUB_ID] [--server SERVER]

Examples:
    python3 sync_subscription_to_db.py 364044145 6c23242d-2d76-4479-9c58-0d53f8153afc 2026-07-05
    python3 sync_subscription_to_db.py 364044145 6c23242d-2d76-4479-9c58-0d53f8153afc 2026-07-05 --sub-id l1ml1zsf3rm7hrt7 --server uk1
"""

import asyncio
import argparse
import sys
import aiosqlite
from datetime import datetime
from pathlib import Path

# Добавляем путь к модулям проекта
sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH


async def sync_subscription(
    user_id: int,
    uuid: str,
    end_date: str,
    xui_sub_id: str = "",
    server_id: str = "uk1",
    plan: str = "manual"
):
    """
    Добавить или обновить подписку в базе данных.

    Args:
        user_id: Telegram user ID
        uuid: VLESS UUID клиента
        end_date: Дата окончания в формате YYYY-MM-DD
        xui_sub_id: XUI subscription ID (опционально)
        server_id: ID сервера из servers.json
        plan: Тип плана (manual, trial, 1m, 3m, 6m, 12m)
    """

    print("="*80)
    print("💾 СИНХРОНИЗАЦИЯ ПОДПИСКИ С БАЗОЙ ДАННЫХ")
    print("="*80)
    print(f"👤 User ID: {user_id}")
    print(f"🆔 UUID: {uuid}")
    print(f"📅 Дата окончания: {end_date}")
    print(f"🔑 XUI Sub ID: {xui_sub_id if xui_sub_id else 'не указан'}")
    print(f"🌍 Server ID: {server_id}")
    print(f"📦 Plan: {plan}")
    print("="*80)

    # Проверяем формат даты
    try:
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        print(f"❌ Неверный формат даты! Используйте YYYY-MM-DD")
        return False

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # 1. Проверяем существование таблицы users (опционально)
            print(f"\n1️⃣ Проверка базы данных...")
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
            )
            users_table_exists = await cursor.fetchone()

            if users_table_exists:
                cursor = await db.execute(
                    "SELECT user_id, username FROM users WHERE user_id = ?",
                    (user_id,)
                )
                user = await cursor.fetchone()

                if not user:
                    print(f"   ⚠️  Пользователь {user_id} не найден, создаём...")
                    await db.execute(
                        """INSERT INTO users (user_id, username, reg_date, trial_used)
                           VALUES (?, ?, ?, 0)""",
                        (user_id, f"user_{user_id}", datetime.now().isoformat())
                    )
                    await db.commit()
                    print(f"   ✅ Пользователь создан")
                else:
                    print(f"   ✅ Пользователь найден: {user[1] or f'user_{user_id}'}")
            else:
                print(f"   ℹ️  Таблица users не существует (работаем только с subscriptions)")

            # 2. Проверяем существование подписки
            print(f"\n2️⃣ Проверка подписки...")
            cursor = await db.execute(
                "SELECT sub_id, end_date, is_active FROM subscriptions WHERE vless_uuid = ?",
                (uuid,)
            )
            existing_sub = await cursor.fetchone()

            if existing_sub:
                print(f"   ⚠️  Подписка с UUID {uuid} уже существует")
                print(f"   Старая дата окончания: {existing_sub[1]}")
                print(f"   Статус: {'активна' if existing_sub[2] else 'неактивна'}")
                print(f"\n   🔄 Обновляем подписку...")

                await db.execute(
                    """UPDATE subscriptions
                       SET end_date = ?,
                           is_active = 1,
                           server_id = ?,
                           xui_sub_id = CASE WHEN ? != '' THEN ? ELSE xui_sub_id END,
                           updated_at = ?
                       WHERE vless_uuid = ?""",
                    (end_date, server_id, xui_sub_id, xui_sub_id,
                     datetime.now().isoformat(), uuid)
                )
                await db.commit()
                print(f"   ✅ Подписка обновлена!")

            else:
                print(f"   📝 Подписка не найдена, создаём новую...")

                # Генерируем xui_sub_id если не указан
                if not xui_sub_id:
                    import random
                    import string
                    xui_sub_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
                    print(f"   🔑 Сгенерирован XUI Sub ID: {xui_sub_id}")

                await db.execute(
                    """INSERT INTO subscriptions
                       (user_id, plan, xui_sub_id, vless_uuid, server_id,
                        is_active, end_date, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (user_id, plan, xui_sub_id, uuid, server_id, end_date,
                     datetime.now().isoformat(), datetime.now().isoformat())
                )
                await db.commit()
                print(f"   ✅ Подписка создана!")

            # 3. Показываем итоговое состояние
            print(f"\n3️⃣ Проверка результата...")
            cursor = await db.execute(
                """SELECT sub_id, user_id, plan, xui_sub_id, vless_uuid,
                          server_id, end_date, is_active
                   FROM subscriptions
                   WHERE vless_uuid = ?""",
                (uuid,)
            )
            final_sub = await cursor.fetchone()

            if final_sub:
                print(f"\n" + "="*80)
                print(f"✅ ПОДПИСКА В БАЗЕ ДАННЫХ:")
                print(f"="*80)
                print(f"📦 Sub ID: {final_sub[0]}")
                print(f"👤 User ID: {final_sub[1]}")
                print(f"📋 Plan: {final_sub[2]}")
                print(f"🔑 XUI Sub ID: {final_sub[3]}")
                print(f"🆔 UUID: {final_sub[4]}")
                print(f"🌍 Server ID: {final_sub[5]}")
                print(f"📅 End Date: {final_sub[6]}")
                print(f"✅ Active: {'ДА' if final_sub[7] else 'НЕТ'}")
                print(f"="*80)

                # Показываем subscription URL
                if final_sub[3]:
                    from config import SUB_BASE_URL
                    sub_url = f"{SUB_BASE_URL}{final_sub[3]}"
                    print(f"\n🔗 Subscription URL:")
                    print(f"   {sub_url}")
                    print(f"\n🔗 Connect URL:")
                    connect_url = sub_url.replace('/sub/', '/connect/')
                    print(f"   {connect_url}")

                return True

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Синхронизация подписки с базой данных бота",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "user_id",
        type=int,
        help="Telegram User ID"
    )

    parser.add_argument(
        "uuid",
        help="VLESS UUID клиента"
    )

    parser.add_argument(
        "end_date",
        help="Дата окончания в формате YYYY-MM-DD"
    )

    parser.add_argument(
        "--sub-id",
        default="",
        help="XUI Subscription ID (опционально, будет сгенерирован автоматически)"
    )

    parser.add_argument(
        "--server",
        default="uk1",
        help="ID сервера из servers.json (по умолчанию: uk1)"
    )

    parser.add_argument(
        "--plan",
        default="manual",
        choices=["manual", "trial", "1m", "3m", "6m", "12m"],
        help="Тип плана (по умолчанию: manual)"
    )

    args = parser.parse_args()

    # Запускаем async функцию
    success = asyncio.run(sync_subscription(
        user_id=args.user_id,
        uuid=args.uuid,
        end_date=args.end_date,
        xui_sub_id=args.sub_id,
        server_id=args.server,
        plan=args.plan
    ))

    if success:
        print("\n" + "="*80)
        print("🎉 УСПЕХ! Подписка синхронизирована с базой данных!")
        print("="*80)
        sys.exit(0)
    else:
        print("\n" + "="*80)
        print("❌ ОШИБКА! Не удалось синхронизировать подписку")
        print("="*80)
        sys.exit(1)


if __name__ == "__main__":
    main()
