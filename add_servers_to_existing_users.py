#!/usr/bin/env python3
"""
Скрипт для добавления новых серверов в подписки существующих пользователей.

Создаёт конфигурации для всех активных пользователей на новых серверах:
- us1 (80.76.49.140) - обновлённые учетные данные
- us2 (31.57.38.104) - новый сервер США 2

Usage:
    python3 add_servers_to_existing_users.py [OPTIONS]

Options:
    --dry-run          Показать что будет сделано, но не выполнять
    --server SERVER    Добавить только на конкретный сервер (us1, us2)
    --user-id USER_ID  Обработать только конкретного пользователя

Examples:
    # Добавить всех пользователей на оба новых сервера
    python3 add_servers_to_existing_users.py

    # Показать что будет сделано (без изменений)
    python3 add_servers_to_existing_users.py --dry-run

    # Добавить только на us2
    python3 add_servers_to_existing_users.py --server us2

    # Обработать только одного пользователя
    python3 add_servers_to_existing_users.py --user-id 364044145
"""

import asyncio
import argparse
import sys
import json
import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

from src.services.xui import ThreeXUIClient
from config import DB_PATH


async def get_active_users() -> List[Dict[str, Any]]:
    """
    Получить всех пользователей с активными подписками.

    Returns:
        Список пользователей с их подписками
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT DISTINCT
                   user_id,
                   vless_uuid,
                   end_date,
                   server_id,
                   xui_sub_id,
                   plan
               FROM subscriptions
               WHERE is_active = 1
               ORDER BY user_id"""
        )
        rows = await cursor.fetchall()
        users = []
        for r in rows:
            user_dict = dict(r)
            # Добавляем username для отображения
            user_dict['username'] = f"user_{user_dict['user_id']}"
            users.append(user_dict)
        return users


async def add_client_to_server(
    server: Dict[str, Any],
    user: Dict[str, Any],
    dry_run: bool = False
) -> bool:
    """
    Создать конфигурацию пользователя на сервере.

    Args:
        server: Данные сервера из servers.json
        user: Данные пользователя из БД
        dry_run: Только показать, не выполнять

    Returns:
        True если успешно, False в случае ошибки
    """
    base_url = f"https://{server['xui_host']}:{server['xui_port']}{server['xui_web_path']}"

    # Формируем email для клиента
    email = f"tg_{user['user_id']}_{user['xui_sub_id']}"

    # Конвертируем end_date в timestamp (миллисекунды)
    try:
        end_date_str = user['end_date']
        # Поддержка разных форматов даты
        if 'T' in end_date_str:
            # ISO формат с временем: 2026-03-05T12:13:22.949983
            end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
        else:
            # Простой формат: 2026-03-05
            end_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
        expiry_ms = int(end_dt.timestamp() * 1000)
    except Exception as e:
        print(f"      ❌ Ошибка парсинга даты: {e}")
        return False

    print(f"      📧 Email: {email}")
    print(f"      🆔 UUID: {user['vless_uuid']}")
    print(f"      📅 Expiry: {user['end_date']} ({expiry_ms})")

    if dry_run:
        print(f"      ℹ️  DRY RUN: Создание клиента пропущено")
        return True

    client = ThreeXUIClient(
        base_url=base_url,
        username=server['xui_username'],
        password=server['xui_password'],
        inbound_id=server['inbound_id'],
        verify_ssl=False
    )

    try:
        async with client.session():
            print(f"      ✅ Авторизация успешна")

            # Попробуем получить список всех inbound'ов для диагностики
            try:
                inbounds = await client.list_inbounds()
                inbound_ids = [ib.get('id') for ib in inbounds]
                print(f"      📋 Доступные inbound ID: {inbound_ids}")

                # Проверяем существует ли нужный inbound
                if server['inbound_id'] not in inbound_ids:
                    print(f"      ⚠️  Inbound {server['inbound_id']} не найден! Используем первый доступный.")
                    if inbound_ids:
                        server['inbound_id'] = inbound_ids[0]
                        print(f"      🔄 Переключились на inbound {server['inbound_id']}")
            except Exception as e:
                print(f"      ⚠️  Не удалось получить список inbound'ов: {e}")

            # Проверяем существует ли клиент
            existing = await client.find_client_by_email(email, server['inbound_id'])
            if existing:
                print(f"      ⏭️  Клиент уже существует на {server['name']}")
                return True

            # Создаём клиента
            await client.add_client(
                uuid=user['vless_uuid'],
                email=email,
                expiry_ms=expiry_ms,
                inbound_id=server['inbound_id'],
                flow=server.get('flow', '')
            )

            print(f"      ✅ Клиент создан на {server['name']}")
            return True

    except Exception as e:
        print(f"      ❌ Ошибка: {e}")
        import traceback
        print(f"      📝 Детали: {traceback.format_exc()}")
        return False
    finally:
        await client.close()


async def save_user_server_mapping(
    user_id: int,
    server_id: str,
    dry_run: bool = False
) -> None:
    """
    Сохранить информацию о добавлении пользователя на сервер.

    Args:
        user_id: ID пользователя
        server_id: ID сервера
        dry_run: Только показать, не выполнять
    """
    if dry_run:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем существует ли таблица user_servers
        cursor = await db.execute(
            """SELECT name FROM sqlite_master
               WHERE type='table' AND name='user_servers'"""
        )
        table_exists = await cursor.fetchone()

        if not table_exists:
            # Создаём таблицу для отслеживания серверов пользователей
            await db.execute(
                """CREATE TABLE IF NOT EXISTS user_servers (
                    user_id INTEGER NOT NULL,
                    server_id TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, server_id)
                )"""
            )
            await db.commit()

        # Добавляем запись
        await db.execute(
            """INSERT OR IGNORE INTO user_servers (user_id, server_id, added_at)
               VALUES (?, ?, ?)""",
            (user_id, server_id, datetime.now().isoformat())
        )
        await db.commit()


async def main(
    server_filter: Optional[str] = None,
    user_id_filter: Optional[int] = None,
    dry_run: bool = False
):
    """
    Главная функция добавления серверов.

    Args:
        server_filter: ID сервера для фильтрации (us1, us2)
        user_id_filter: ID пользователя для фильтрации
        dry_run: Только показать, не выполнять
    """
    print("="*80)
    print("🌍 ДОБАВЛЕНИЕ НОВЫХ СЕРВЕРОВ В ПОДПИСКИ ПОЛЬЗОВАТЕЛЕЙ")
    print("="*80)

    if dry_run:
        print("⚠️  DRY RUN MODE: Изменения НЕ будут применены")
        print("="*80)

    # Загружаем конфигурацию серверов
    servers_file = Path(__file__).parent / "servers.json"
    with open(servers_file, "r", encoding="utf-8") as f:
        servers_data = json.load(f)

    # Фильтруем серверы - только us1 и us2
    target_servers = ['us1', 'us2']
    if server_filter:
        if server_filter not in target_servers:
            print(f"❌ Неверный сервер {server_filter}. Используйте: us1, us2")
            return
        target_servers = [server_filter]

    servers = [s for s in servers_data.get("servers", [])
               if s.get('id') in target_servers and s.get('enabled')]

    if not servers:
        print("❌ Не найдено включённых серверов us1/us2!")
        return

    print(f"\n📋 Целевые серверы:")
    for server in servers:
        print(f"   🇺🇸 {server['name']} ({server['id']}) - {server['host']}")

    # Получаем всех активных пользователей
    print(f"\n{'='*80}")
    print("👥 ПОЛУЧЕНИЕ АКТИВНЫХ ПОЛЬЗОВАТЕЛЕЙ")
    print(f"{'='*80}")

    users = await get_active_users()

    if user_id_filter:
        users = [u for u in users if u['user_id'] == user_id_filter]
        if not users:
            print(f"❌ Пользователь {user_id_filter} не найден или неактивен!")
            return

    print(f"   📊 Найдено активных пользователей: {len(users)}")

    # Группируем пользователей по user_id (т.к. могут быть несколько подписок)
    users_by_id = {}
    for user in users:
        uid = user['user_id']
        if uid not in users_by_id:
            users_by_id[uid] = user
        else:
            # Берём подписку с самой поздней датой окончания
            if user['end_date'] > users_by_id[uid]['end_date']:
                users_by_id[uid] = user

    unique_users = list(users_by_id.values())
    print(f"   📊 Уникальных пользователей: {len(unique_users)}")

    # Обрабатываем каждого пользователя
    print(f"\n{'='*80}")
    print("🚀 ДОБАВЛЕНИЕ ПОЛЬЗОВАТЕЛЕЙ НА СЕРВЕРЫ")
    print(f"{'='*80}")

    stats = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'skipped': 0
    }

    for i, user in enumerate(unique_users, 1):
        print(f"\n[{i}/{len(unique_users)}] 👤 Пользователь: {user['username']} (ID: {user['user_id']})")
        print(f"   📅 Подписка до: {user['end_date']}")
        print(f"   🌍 Текущий сервер: {user['server_id']}")

        for server in servers:
            # Пропускаем если пользователь уже на этом сервере
            if server['id'] == user['server_id']:
                print(f"   ⏭️  Пользователь уже на {server['name']}")
                stats['skipped'] += 1
                continue

            print(f"\n   🔧 Добавление на {server['name']} ({server['id']})...")
            stats['total'] += 1

            success = await add_client_to_server(server, user, dry_run)

            if success:
                stats['success'] += 1
                await save_user_server_mapping(user['user_id'], server['id'], dry_run)
            else:
                stats['failed'] += 1

        # Небольшая задержка между пользователями
        if i < len(unique_users):
            await asyncio.sleep(0.5)

    # Итоговая статистика
    print(f"\n{'='*80}")
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print(f"{'='*80}")
    print(f"👥 Обработано пользователей: {len(unique_users)}")
    print(f"🌍 Целевых серверов: {len(servers)}")
    print(f"✅ Успешно добавлено: {stats['success']}")
    print(f"❌ Ошибок: {stats['failed']}")
    print(f"⏭️  Пропущено (уже существуют): {stats['skipped']}")
    print(f"📦 Всего операций: {stats['total']}")
    print(f"{'='*80}")

    if dry_run:
        print("\nℹ️  Это был DRY RUN. Запустите без --dry-run для применения изменений.")
    else:
        print("\n✅ Готово! Все пользователи добавлены на новые серверы.")
        print("📱 Подписки автоматически обновятся при следующем запросе subscription URL.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Добавление новых серверов в подписки существующих пользователей",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--server",
        help="ID сервера для добавления (us1, us2)"
    )

    parser.add_argument(
        "--user-id",
        type=int,
        help="ID пользователя для обработки (только один пользователь)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать что будет сделано, но не выполнять"
    )

    args = parser.parse_args()

    asyncio.run(main(
        server_filter=args.server,
        user_id_filter=args.user_id,
        dry_run=args.dry_run
    ))
