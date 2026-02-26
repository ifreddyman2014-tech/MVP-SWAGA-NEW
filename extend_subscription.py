#!/usr/bin/env python3
"""
Скрипт для продления подписки на x-ui панели и синхронизации с базой данных.

Usage:
    python3 extend_subscription.py <uuid> [--date YYYY-MM-DD] [--add-to-db]

Examples:
    # Продлить до 05.07.2026
    python3 extend_subscription.py 6c23242d-2d76-4479-9c58-0d53f8153afc --date 2026-07-05

    # Продлить и добавить в базу данных бота
    python3 extend_subscription.py 6c23242d-2d76-4479-9c58-0d53f8153afc --date 2026-07-05 --add-to-db
"""

import asyncio
import argparse
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

# Добавляем путь к модулям проекта
sys.path.insert(0, str(Path(__file__).parent))

from src.services.xui import ThreeXUIClient


async def extend_subscription(
    uuid: str,
    expiry_date: str,
    server_id: str = "uk1",
    add_to_db: bool = False
):
    """
    Продлить подписку на x-ui панели.

    Args:
        uuid: UUID клиента для продления
        expiry_date: Дата окончания в формате YYYY-MM-DD
        server_id: ID сервера из servers.json (по умолчанию uk1 - Великобритания)
        add_to_db: Добавить запись в базу данных бота
    """

    # Загружаем конфигурацию серверов
    servers_file = Path(__file__).parent / "servers.json"
    with open(servers_file, "r", encoding="utf-8") as f:
        servers_data = json.load(f)

    # Находим нужный сервер
    server = None
    for srv in servers_data.get("servers", []):
        if srv.get("id") == server_id:
            server = srv
            break

    if not server:
        print(f"❌ Сервер {server_id} не найден в servers.json")
        return False

    # Формируем URL панели
    base_url = f"https://{server['xui_host']}:{server['xui_port']}{server['xui_web_path']}"
    username = server['xui_username']
    password = server['xui_password']
    inbound_id = server['inbound_id']

    print("="*80)
    print(f"🔧 ПРОДЛЕНИЕ ПОДПИСКИ")
    print("="*80)
    print(f"🌍 Сервер: {server['name']} ({server['host']})")
    print(f"🔗 Панель: {base_url}")
    print(f"🆔 UUID: {uuid}")
    print(f"📅 Новая дата окончания: {expiry_date}")
    print("="*80)

    # Парсим дату и конвертируем в timestamp
    try:
        expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d")
        expiry_dt = expiry_dt.replace(hour=23, minute=59, second=59)
        expiry_ms = int(expiry_dt.timestamp() * 1000)
        print(f"⏰ Timestamp: {expiry_ms}")
    except ValueError as e:
        print(f"❌ Неверный формат даты: {e}")
        return False

    # Создаём клиент x-ui
    client = ThreeXUIClient(
        base_url=base_url,
        username=username,
        password=password,
        inbound_id=inbound_id
    )

    try:
        async with client.session():
            print("\n✅ Авторизация успешна!")

            # Находим клиента по UUID
            print(f"\n🔍 Поиск клиента с UUID: {uuid}...")
            found_client = await client.find_client_by_uuid(uuid, inbound_id)

            if not found_client:
                print(f"❌ Клиент с UUID {uuid} не найден на сервере!")
                return False

            email = found_client.get('email', '')
            current_expiry = found_client.get('expiryTime', 0)
            enabled = found_client.get('enable', False)

            print(f"✅ Клиент найден!")
            print(f"   📧 Email: {email}")
            print(f"   ✅ Enabled: {enabled}")

            if current_expiry > 0:
                current_dt = datetime.fromtimestamp(current_expiry / 1000)
                print(f"   📅 Текущая дата окончания: {current_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"   📅 Текущая дата: Бессрочно")

            # Обновляем срок действия
            print(f"\n🔄 Обновление срока действия...")
            success = await client.update_client_expiry(
                uuid=uuid,
                expiry_ms=expiry_ms,
                email=email,
                inbound_id=inbound_id
            )

            if success:
                print(f"✅ Срок действия успешно обновлён!")
                print(f"📅 Новая дата окончания: {expiry_dt.strftime('%Y-%m-%d %H:%M:%S')}")

                # Проверяем обновление
                print(f"\n🔍 Проверка обновления...")
                await asyncio.sleep(1)
                updated_client = await client.find_client_by_uuid(uuid, inbound_id)

                if updated_client:
                    new_expiry = updated_client.get('expiryTime', 0)
                    if new_expiry > 0:
                        new_dt = datetime.fromtimestamp(new_expiry / 1000)
                        print(f"✅ Подтверждено! Новая дата: {new_dt.strftime('%Y-%m-%d %H:%M:%S')}")

                # Добавляем в базу данных бота (опционально)
                if add_to_db:
                    print(f"\n💾 Добавление в базу данных бота...")
                    await add_to_database(
                        user_id=extract_user_id(email),
                        uuid=uuid,
                        xui_sub_id=found_client.get('subId', ''),
                        end_date=expiry_date,
                        server_id=server_id
                    )

                return True
            else:
                print(f"❌ Не удалось обновить срок действия!")
                return False

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await client.close()


async def add_to_database(user_id: int, uuid: str, xui_sub_id: str, end_date: str, server_id: str):
    """Добавить подписку в базу данных бота."""
    import aiosqlite
    from config import DB_PATH

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Проверяем, существует ли пользователь
            cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            user_exists = await cursor.fetchone()

            if not user_exists:
                print(f"   ⚠️  Пользователь {user_id} не найден, создаём...")
                await db.execute(
                    "INSERT INTO users (user_id, username, reg_date) VALUES (?, ?, ?)",
                    (user_id, f"user_{user_id}", datetime.now().isoformat())
                )

            # Проверяем, существует ли подписка с таким UUID
            cursor = await db.execute(
                "SELECT sub_id FROM subscriptions WHERE vless_uuid = ?",
                (uuid,)
            )
            existing_sub = await cursor.fetchone()

            if existing_sub:
                print(f"   ⚠️  Подписка с UUID {uuid} уже существует, обновляем...")
                await db.execute(
                    """UPDATE subscriptions
                       SET end_date = ?, is_active = 1, server_id = ?, updated_at = ?
                       WHERE vless_uuid = ?""",
                    (end_date, server_id, datetime.now().isoformat(), uuid)
                )
            else:
                print(f"   📝 Создаём новую подписку...")
                await db.execute(
                    """INSERT INTO subscriptions
                       (user_id, plan, xui_sub_id, vless_uuid, server_id,
                        is_active, end_date, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (user_id, "manual", xui_sub_id, uuid, server_id,
                     end_date, datetime.now().isoformat(), datetime.now().isoformat())
                )

            await db.commit()
            print(f"   ✅ Подписка добавлена в базу данных!")

    except Exception as e:
        print(f"   ❌ Ошибка при добавлении в БД: {e}")


def extract_user_id(email: str) -> int:
    """Извлечь user_id из email формата tg_364044145_1771431227."""
    try:
        if email.startswith("tg_"):
            parts = email.split("_")
            if len(parts) >= 2:
                return int(parts[1])
    except (ValueError, IndexError):
        pass
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Продление подписки на x-ui панели",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "uuid",
        help="UUID клиента для продления"
    )

    parser.add_argument(
        "--date",
        default=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
        help="Дата окончания в формате YYYY-MM-DD (по умолчанию: +1 год)"
    )

    parser.add_argument(
        "--server",
        default="uk1",
        help="ID сервера из servers.json (по умолчанию: uk1)"
    )

    parser.add_argument(
        "--add-to-db",
        action="store_true",
        help="Добавить подписку в базу данных бота"
    )

    args = parser.parse_args()

    # Запускаем async функцию
    success = asyncio.run(extend_subscription(
        uuid=args.uuid,
        expiry_date=args.date,
        server_id=args.server,
        add_to_db=args.add_to_db
    ))

    if success:
        print("\n" + "="*80)
        print("🎉 УСПЕХ! Подписка успешно продлена!")
        print("="*80)
        sys.exit(0)
    else:
        print("\n" + "="*80)
        print("❌ ОШИБКА! Не удалось продлить подписку")
        print("="*80)
        sys.exit(1)


if __name__ == "__main__":
    main()
