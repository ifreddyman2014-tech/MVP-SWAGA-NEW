#!/usr/bin/env python3
"""
Скрипт для массового продления подписок.

Автоматически продлевает подписки которые:
- Уже истекли
- Истекают в ближайшие N дней
- Соответствуют указанным фильтрам

Usage:
    python3 bulk_extend_subscriptions.py [OPTIONS]

Options:
    --days-before N       Продлить подписки, истекающие в ближайшие N дней (по умолчанию: 7)
    --extend-days N       На сколько дней продлить (по умолчанию: 30)
    --server SERVER       Продлить только на указанном сервере
    --plan PLAN           Продлить только указанный план (trial, 1m, 3m, 6m, 12m)
    --include-expired     Включить истекшие подписки
    --dry-run             Показать что будет сделано, но не выполнять
    --update-panel        Обновить даты на x-ui панели (требует доступа)

Examples:
    # Продлить все подписки, истекающие в ближайшие 7 дней, на 30 дней
    python3 bulk_extend_subscriptions.py

    # Продлить все истекшие подписки на 90 дней
    python3 bulk_extend_subscriptions.py --include-expired --extend-days 90

    # Продлить только UK сервер
    python3 bulk_extend_subscriptions.py --server uk1 --extend-days 365

    # Показать что будет сделано
    python3 bulk_extend_subscriptions.py --dry-run

    # Продлить в БД и на панели
    python3 bulk_extend_subscriptions.py --update-panel --extend-days 30
"""

import asyncio
import argparse
import sys
import json
import aiosqlite
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent))

from src.services.xui import ThreeXUIClient
from config import DB_PATH


async def get_subscriptions_to_extend(
    days_before: int = 7,
    server_filter: str = None,
    plan_filter: str = None,
    include_expired: bool = False
) -> List[Dict[str, Any]]:
    """
    Получить подписки, требующие продления.

    Args:
        days_before: Продлить подписки, истекающие в ближайшие N дней
        server_filter: Фильтр по серверу
        plan_filter: Фильтр по плану
        include_expired: Включить истекшие подписки

    Returns:
        Список подписок для продления
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Вычисляем пороговую дату
        threshold_date = (datetime.now() + timedelta(days=days_before)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')

        # Формируем запрос
        query = """
            SELECT sub_id, user_id, plan, xui_sub_id, vless_uuid,
                   server_id, end_date, is_active
            FROM subscriptions
            WHERE is_active = 1
        """
        params = []

        if include_expired:
            # Включаем истекшие и истекающие
            query += " AND end_date <= ?"
            params.append(threshold_date)
        else:
            # Только истекающие в ближайшие дни (но не истекшие)
            query += " AND end_date > ? AND end_date <= ?"
            params.extend([today, threshold_date])

        if server_filter:
            query += " AND server_id = ?"
            params.append(server_filter)

        if plan_filter:
            query += " AND plan = ?"
            params.append(plan_filter)

        query += " ORDER BY end_date ASC"

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def extend_subscription_in_db(
    sub_id: int,
    new_end_date: str
) -> bool:
    """
    Продлить подписку в базе данных.

    Args:
        sub_id: ID подписки
        new_end_date: Новая дата окончания (YYYY-MM-DD)

    Returns:
        True если успешно
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE subscriptions
               SET end_date = ?, updated_at = ?
               WHERE sub_id = ?""",
            (new_end_date, datetime.now().isoformat(), sub_id)
        )
        await db.commit()
        return True


async def extend_subscription_on_panel(
    uuid: str,
    new_end_date: str,
    server_id: str
) -> bool:
    """
    Продлить подписку на x-ui панели.

    Args:
        uuid: UUID клиента
        new_end_date: Новая дата окончания (YYYY-MM-DD)
        server_id: ID сервера

    Returns:
        True если успешно
    """
    # Загружаем конфигурацию серверов
    servers_file = Path(__file__).parent / "servers.json"
    with open(servers_file, "r", encoding="utf-8") as f:
        servers_data = json.load(f)

    # Находим сервер
    server = None
    for srv in servers_data.get("servers", []):
        if srv.get("id") == server_id:
            server = srv
            break

    if not server:
        print(f"   ⚠️  Сервер {server_id} не найден")
        return False

    # Формируем URL панели
    base_url = f"https://{server['xui_host']}:{server['xui_port']}{server['xui_web_path']}"

    # Конвертируем дату в timestamp
    end_dt = datetime.strptime(new_end_date, "%Y-%m-%d")
    end_dt = end_dt.replace(hour=23, minute=59, second=59)
    expiry_ms = int(end_dt.timestamp() * 1000)

    # Создаём клиент x-ui
    client = ThreeXUIClient(
        base_url=base_url,
        username=server['xui_username'],
        password=server['xui_password'],
        inbound_id=server['inbound_id']
    )

    try:
        async with client.session():
            # Находим клиента
            found_client = await client.find_client_by_uuid(uuid, server['inbound_id'])
            if not found_client:
                print(f"   ⚠️  UUID не найден на панели")
                return False

            email = found_client.get('email', '')

            # Обновляем срок
            success = await client.update_client_expiry(
                uuid=uuid,
                expiry_ms=expiry_ms,
                email=email,
                inbound_id=server['inbound_id']
            )

            return success

    except Exception as e:
        print(f"   ⚠️  Ошибка на панели: {e}")
        return False
    finally:
        await client.close()


async def bulk_extend(
    days_before: int = 7,
    extend_days: int = 30,
    server_filter: str = None,
    plan_filter: str = None,
    include_expired: bool = False,
    update_panel: bool = False,
    dry_run: bool = False
):
    """
    Массовое продление подписок.

    Args:
        days_before: Продлить подписки, истекающие в ближайшие N дней
        extend_days: На сколько дней продлить
        server_filter: Фильтр по серверу
        plan_filter: Фильтр по плану
        include_expired: Включить истекшие
        update_panel: Обновить на x-ui панели
        dry_run: Только показать, не выполнять
    """
    print("="*80)
    print("🔄 МАССОВОЕ ПРОДЛЕНИЕ ПОДПИСОК")
    print("="*80)

    if dry_run:
        print("⚠️  DRY RUN MODE: Изменения НЕ будут применены")
        print("="*80)

    print(f"\n📊 Параметры:")
    print(f"   Продлить истекающие в ближайшие: {days_before} дн.")
    print(f"   Продлить на: {extend_days} дн.")
    if server_filter:
        print(f"   Сервер: {server_filter}")
    if plan_filter:
        print(f"   План: {plan_filter}")
    if include_expired:
        print(f"   Включая истекшие: Да")
    if update_panel:
        print(f"   Обновление панели: Да")

    # Получаем подписки для продления
    print(f"\n🔍 Поиск подписок для продления...")
    subscriptions = await get_subscriptions_to_extend(
        days_before=days_before,
        server_filter=server_filter,
        plan_filter=plan_filter,
        include_expired=include_expired
    )

    print(f"   Найдено подписок: {len(subscriptions)}")

    if not subscriptions:
        print("\n✅ Нет подписок, требующих продления")
        return

    # Статистика
    stats = {
        'total': len(subscriptions),
        'db_updated': 0,
        'panel_updated': 0,
        'failed': 0
    }

    # Продлеваем каждую подписку
    print(f"\n{'='*80}")
    print("🔄 ПРОДЛЕНИЕ ПОДПИСОК")
    print(f"{'='*80}")

    for i, sub in enumerate(subscriptions, 1):
        current_end_date = sub.get('end_date')
        uuid = sub.get('vless_uuid')
        server_id = sub.get('server_id', '')
        user_id = sub.get('user_id')
        xui_sub_id = sub.get('xui_sub_id')

        # Вычисляем новую дату
        current_dt = datetime.strptime(current_end_date, '%Y-%m-%d')
        # Если подписка истекла, продлеваем от сегодня
        if current_dt < datetime.now():
            new_dt = datetime.now() + timedelta(days=extend_days)
        else:
            # Если ещё активна, продлеваем от даты окончания
            new_dt = current_dt + timedelta(days=extend_days)

        new_end_date = new_dt.strftime('%Y-%m-%d')

        print(f"\n[{i}/{len(subscriptions)}] 📦 Sub ID: {xui_sub_id}")
        print(f"   👤 User: {user_id}")
        print(f"   🆔 UUID: {uuid[:20] if uuid else 'N/A'}...")
        print(f"   🌍 Server: {server_id}")
        print(f"   📅 Текущая дата: {current_end_date}")
        print(f"   📅 Новая дата: {new_end_date}")

        if dry_run:
            print(f"   ℹ️  DRY RUN: Пропуск")
            continue

        # Обновляем в БД
        try:
            await extend_subscription_in_db(sub['sub_id'], new_end_date)
            print(f"   ✅ БД обновлена")
            stats['db_updated'] += 1
        except Exception as e:
            print(f"   ❌ Ошибка БД: {e}")
            stats['failed'] += 1
            continue

        # Обновляем на панели (опционально)
        if update_panel and server_id and uuid:
            try:
                success = await extend_subscription_on_panel(uuid, new_end_date, server_id)
                if success:
                    print(f"   ✅ Панель обновлена")
                    stats['panel_updated'] += 1
                else:
                    print(f"   ⚠️  Панель не обновлена")
            except Exception as e:
                print(f"   ⚠️  Ошибка панели: {e}")

    # Итоговая статистика
    print(f"\n{'='*80}")
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print(f"{'='*80}")
    print(f"📦 Всего подписок: {stats['total']}")
    print(f"✅ Обновлено в БД: {stats['db_updated']}")
    if update_panel:
        print(f"✅ Обновлено на панели: {stats['panel_updated']}")
    if stats['failed']:
        print(f"❌ Ошибок: {stats['failed']}")
    print(f"{'='*80}")

    if dry_run:
        print("\nℹ️  Это был DRY RUN. Запустите без --dry-run для применения изменений.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Массовое продление подписок",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--days-before",
        type=int,
        default=7,
        help="Продлить подписки, истекающие в ближайшие N дней (по умолчанию: 7)"
    )

    parser.add_argument(
        "--extend-days",
        type=int,
        default=30,
        help="На сколько дней продлить (по умолчанию: 30)"
    )

    parser.add_argument(
        "--server",
        help="ID сервера (uk1, us1, fr1, etc.)"
    )

    parser.add_argument(
        "--plan",
        help="Тип плана (trial, 1m, 3m, 6m, 12m)"
    )

    parser.add_argument(
        "--include-expired",
        action="store_true",
        help="Включить истекшие подписки"
    )

    parser.add_argument(
        "--update-panel",
        action="store_true",
        help="Обновить даты на x-ui панели (требует доступа)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать что будет сделано, но не выполнять"
    )

    args = parser.parse_args()

    asyncio.run(bulk_extend(
        days_before=args.days_before,
        extend_days=args.extend_days,
        server_filter=args.server,
        plan_filter=args.plan,
        include_expired=args.include_expired,
        update_panel=args.update_panel,
        dry_run=args.dry_run
    ))
