#!/usr/bin/env python3
"""
Скрипт для массовой синхронизации всех подписок с x-ui панели в базу данных.

Получает все подписки со всех серверов и синхронизирует их с базой данных бота.

Usage:
    python3 sync_all_subscriptions.py [OPTIONS]

Options:
    --server SERVER    Синхронизировать только указанный сервер (uk1, us1, fr1, etc.)
    --dry-run          Показать что будет сделано, но не выполнять
    --update-existing  Обновлять существующие подписки в БД

Examples:
    # Синхронизировать все серверы
    python3 sync_all_subscriptions.py

    # Синхронизировать только Великобританию
    python3 sync_all_subscriptions.py --server uk1

    # Показать что будет сделано (без изменений)
    python3 sync_all_subscriptions.py --dry-run

    # Обновить существующие подписки
    python3 sync_all_subscriptions.py --update-existing
"""

import asyncio
import argparse
import sys
import json
import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent))

from src.services.xui import ThreeXUIClient
from config import DB_PATH


async def get_server_clients(
    server: Dict[str, Any],
    dry_run: bool = False
) -> List[Dict[str, Any]]:
    """
    Получить всех клиентов с сервера.

    Args:
        server: Данные сервера из servers.json
        dry_run: Только показать, не выполнять

    Returns:
        Список клиентов
    """
    base_url = f"https://{server['xui_host']}:{server['xui_port']}{server['xui_web_path']}"

    print(f"\n{'='*80}")
    print(f"🌍 Сервер: {server['name']} ({server['id']})")
    print(f"🔗 Панель: {base_url}")
    print(f"{'='*80}")

    if dry_run:
        print("   ℹ️  DRY RUN: Подключение пропущено")
        return []

    client = ThreeXUIClient(
        base_url=base_url,
        username=server['xui_username'],
        password=server['xui_password'],
        inbound_id=server['inbound_id']
    )

    try:
        async with client.session():
            print("   ✅ Авторизация успешна!")

            clients = await client.list_clients(server['inbound_id'])
            print(f"   📊 Найдено клиентов: {len(clients)}")

            # Добавляем информацию о сервере к каждому клиенту
            for c in clients:
                c['_server_id'] = server['id']
                c['_server_name'] = server['name']

            return clients

    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return []
    finally:
        await client.close()


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


async def sync_clients_to_db(
    clients: List[Dict[str, Any]],
    update_existing: bool = False,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Синхронизировать клиентов с базой данных.

    Args:
        clients: Список клиентов с x-ui панели
        update_existing: Обновлять существующие записи
        dry_run: Только показать, не выполнять

    Returns:
        Статистика: {'added': N, 'updated': N, 'skipped': N}
    """
    stats = {'added': 0, 'updated': 0, 'skipped': 0}

    if dry_run:
        print(f"\n{'='*80}")
        print("ℹ️  DRY RUN: Изменения в БД не будут выполнены")
        print(f"{'='*80}")

    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем существование таблицы users
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        users_table_exists = await cursor.fetchone()

        for client in clients:
            uuid = client.get('id') or client.get('uuid')
            email = client.get('email', '')
            expiry = client.get('expiryTime', 0)
            enabled = client.get('enable', False)
            sub_id = client.get('subId', '')
            server_id = client.get('_server_id', '')
            server_name = client.get('_server_name', '')

            # Извлекаем user_id
            user_id = extract_user_id(email)
            if user_id == 0:
                print(f"\n⚠️  Пропуск: не удалось извлечь user_id из {email}")
                stats['skipped'] += 1
                continue

            # Конвертируем expiry timestamp
            end_date = None
            if expiry > 0:
                end_dt = datetime.fromtimestamp(expiry / 1000)
                end_date = end_dt.strftime('%Y-%m-%d')
            else:
                # Бессрочная подписка - ставим год вперёд
                end_date = (datetime.now().replace(year=datetime.now().year + 1)).strftime('%Y-%m-%d')

            print(f"\n📦 {email}")
            print(f"   🆔 UUID: {uuid}")
            print(f"   👤 User ID: {user_id}")
            print(f"   📅 End Date: {end_date}")
            print(f"   ✅ Enabled: {enabled}")
            print(f"   🌍 Server: {server_name} ({server_id})")

            if dry_run:
                print(f"   ℹ️  DRY RUN: Пропуск синхронизации")
                continue

            # Проверяем существование в БД
            cursor = await db.execute(
                "SELECT sub_id, end_date FROM subscriptions WHERE vless_uuid = ?",
                (uuid,)
            )
            existing = await cursor.fetchone()

            if existing:
                if update_existing:
                    print(f"   🔄 Обновление существующей подписки...")
                    await db.execute(
                        """UPDATE subscriptions
                           SET end_date = ?,
                               is_active = ?,
                               server_id = ?,
                               xui_sub_id = CASE WHEN ? != '' THEN ? ELSE xui_sub_id END,
                               updated_at = ?
                           WHERE vless_uuid = ?""",
                        (end_date, 1 if enabled else 0, server_id, sub_id, sub_id,
                         datetime.now().isoformat(), uuid)
                    )
                    await db.commit()
                    stats['updated'] += 1
                    print(f"   ✅ Обновлено")
                else:
                    print(f"   ⏭️  Уже существует (используйте --update-existing для обновления)")
                    stats['skipped'] += 1
            else:
                # Создаём пользователя если нужно
                if users_table_exists:
                    cursor = await db.execute(
                        "SELECT user_id FROM users WHERE user_id = ?",
                        (user_id,)
                    )
                    user_exists = await cursor.fetchone()

                    if not user_exists:
                        await db.execute(
                            """INSERT INTO users (user_id, username, reg_date, trial_used)
                               VALUES (?, ?, ?, 0)""",
                            (user_id, f"user_{user_id}", datetime.now().isoformat())
                        )
                        await db.commit()

                # Генерируем sub_id если нет
                if not sub_id:
                    import random
                    import string
                    sub_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

                # Создаём подписку
                print(f"   📝 Создание новой подписки...")
                await db.execute(
                    """INSERT INTO subscriptions
                       (user_id, plan, xui_sub_id, vless_uuid, server_id,
                        is_active, end_date, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, "imported", sub_id, uuid, server_id,
                     1 if enabled else 0, end_date,
                     datetime.now().isoformat(), datetime.now().isoformat())
                )
                await db.commit()
                stats['added'] += 1
                print(f"   ✅ Добавлено")

    return stats


async def main(
    server_filter: str = None,
    update_existing: bool = False,
    dry_run: bool = False
):
    """
    Главная функция синхронизации.

    Args:
        server_filter: ID сервера для фильтрации (uk1, us1, etc.)
        update_existing: Обновлять существующие записи
        dry_run: Только показать, не выполнять
    """
    print("="*80)
    print("🔄 МАССОВАЯ СИНХРОНИЗАЦИЯ ПОДПИСОК")
    print("="*80)

    if dry_run:
        print("⚠️  DRY RUN MODE: Изменения НЕ будут применены")
        print("="*80)

    # Загружаем конфигурацию серверов
    servers_file = Path(__file__).parent / "servers.json"
    with open(servers_file, "r", encoding="utf-8") as f:
        servers_data = json.load(f)

    servers = servers_data.get("servers", [])

    # Фильтруем серверы
    if server_filter:
        servers = [s for s in servers if s.get('id') == server_filter]
        if not servers:
            print(f"❌ Сервер {server_filter} не найден!")
            return

    # Собираем всех клиентов со всех серверов
    all_clients = []
    for server in servers:
        clients = await get_server_clients(server, dry_run)
        all_clients.extend(clients)

    if not all_clients:
        print("\n⚠️  Клиенты не найдены или ошибка подключения")
        return

    print(f"\n{'='*80}")
    print(f"📊 ВСЕГО КЛИЕНТОВ: {len(all_clients)}")
    print(f"{'='*80}")

    # Синхронизируем с БД
    print(f"\n{'='*80}")
    print("💾 СИНХРОНИЗАЦИЯ С БАЗОЙ ДАННЫХ")
    print(f"{'='*80}")

    stats = await sync_clients_to_db(all_clients, update_existing, dry_run)

    # Итоговая статистика
    print(f"\n{'='*80}")
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print(f"{'='*80}")
    print(f"✅ Добавлено: {stats['added']}")
    print(f"🔄 Обновлено: {stats['updated']}")
    print(f"⏭️  Пропущено: {stats['skipped']}")
    print(f"📦 Всего обработано: {sum(stats.values())}")
    print(f"{'='*80}")

    if dry_run:
        print("\nℹ️  Это был DRY RUN. Запустите без --dry-run для применения изменений.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Массовая синхронизация подписок с x-ui панели",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--server",
        help="ID сервера для синхронизации (uk1, us1, fr1, etc.)"
    )

    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Обновлять существующие подписки в БД"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать что будет сделано, но не выполнять"
    )

    args = parser.parse_args()

    asyncio.run(main(
        server_filter=args.server,
        update_existing=args.update_existing,
        dry_run=args.dry_run
    ))
