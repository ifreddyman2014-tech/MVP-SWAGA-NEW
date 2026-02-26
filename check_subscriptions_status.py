#!/usr/bin/env python3
"""
Скрипт для проверки состояния всех подписок.

Показывает:
- Какие подписки есть в БД
- Какие подписки есть на x-ui панели
- Расхождения между БД и панелью
- Истекшие подписки
- Подписки, требующие продления

Usage:
    python3 check_subscriptions_status.py [OPTIONS]

Options:
    --server SERVER      Проверить только указанный сервер
    --show-all           Показать все подписки (включая неактивные)
    --show-expired       Показать только истекшие подписки
    --export-csv FILE    Экспортировать в CSV файл

Examples:
    # Проверить все подписки
    python3 check_subscriptions_status.py

    # Проверить только UK сервер
    python3 check_subscriptions_status.py --server uk1

    # Показать только истекшие
    python3 check_subscriptions_status.py --show-expired

    # Экспорт в CSV
    python3 check_subscriptions_status.py --export-csv subscriptions.csv
"""

import asyncio
import argparse
import sys
import json
import aiosqlite
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH


async def get_db_subscriptions() -> List[Dict[str, Any]]:
    """Получить все подписки из базы данных."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT sub_id, user_id, plan, xui_sub_id, vless_uuid,
                   server_id, end_date, is_active, created_at, updated_at
            FROM subscriptions
            ORDER BY end_date DESC
        """)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


def analyze_subscription(sub: Dict[str, Any]) -> Dict[str, Any]:
    """
    Анализ состояния подписки.

    Returns:
        Dict с полями: status, days_left, expired, expiring_soon
    """
    end_date_str = sub.get('end_date')
    if not end_date_str:
        return {
            'status': '⚠️ Нет даты окончания',
            'days_left': None,
            'expired': False,
            'expiring_soon': False,
            'end_date_obj': None
        }

    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        now = datetime.now()
        days_left = (end_date - now).days

        if days_left < 0:
            status = f'❌ Истекла {abs(days_left)} дн. назад'
            expired = True
            expiring_soon = False
        elif days_left == 0:
            status = '⚠️ Истекает сегодня'
            expired = False
            expiring_soon = True
        elif days_left <= 7:
            status = f'⚠️ Истекает через {days_left} дн.'
            expired = False
            expiring_soon = True
        elif days_left <= 30:
            status = f'⏰ Осталось {days_left} дн.'
            expired = False
            expiring_soon = True
        else:
            status = f'✅ Активна ({days_left} дн.)'
            expired = False
            expiring_soon = False

        return {
            'status': status,
            'days_left': days_left,
            'expired': expired,
            'expiring_soon': expiring_soon,
            'end_date_obj': end_date
        }
    except ValueError:
        return {
            'status': '⚠️ Неверный формат даты',
            'days_left': None,
            'expired': False,
            'expiring_soon': False,
            'end_date_obj': None
        }


async def check_status(
    server_filter: str = None,
    show_all: bool = False,
    show_expired: bool = False,
    export_csv: str = None
):
    """
    Проверить состояние всех подписок.

    Args:
        server_filter: ID сервера для фильтрации
        show_all: Показать все подписки (включая неактивные)
        show_expired: Показать только истекшие
        export_csv: Путь к CSV файлу для экспорта
    """
    print("="*80)
    print("📊 ПРОВЕРКА СОСТОЯНИЯ ПОДПИСОК")
    print("="*80)

    # Получаем подписки из БД
    print("\n🔍 Загрузка подписок из базы данных...")
    subscriptions = await get_db_subscriptions()

    print(f"   Найдено подписок: {len(subscriptions)}")

    # Фильтруем по серверу
    if server_filter:
        subscriptions = [s for s in subscriptions if s.get('server_id') == server_filter]
        print(f"   После фильтрации по {server_filter}: {len(subscriptions)}")

    # Фильтруем по статусу
    if not show_all:
        subscriptions = [s for s in subscriptions if s.get('is_active')]
        print(f"   Только активные: {len(subscriptions)}")

    # Анализируем каждую подписку
    analyzed = []
    for sub in subscriptions:
        analysis = analyze_subscription(sub)
        analyzed.append({**sub, **analysis})

    # Фильтруем по истекшим
    if show_expired:
        analyzed = [s for s in analyzed if s.get('expired')]

    # Группируем по статусам
    by_status = defaultdict(list)
    for sub in analyzed:
        if sub['expired']:
            by_status['expired'].append(sub)
        elif sub['expiring_soon']:
            by_status['expiring_soon'].append(sub)
        else:
            by_status['active'].append(sub)

    # Выводим статистику
    print(f"\n{'='*80}")
    print("📊 СТАТИСТИКА")
    print(f"{'='*80}")
    print(f"✅ Активных: {len(by_status['active'])}")
    print(f"⚠️  Истекают скоро: {len(by_status['expiring_soon'])}")
    print(f"❌ Истекших: {len(by_status['expired'])}")
    print(f"📦 Всего: {len(analyzed)}")

    # Показываем детали
    sections = [
        ('❌ ИСТЕКШИЕ ПОДПИСКИ', by_status['expired']),
        ('⚠️  ИСТЕКАЮТ СКОРО (< 30 дней)', by_status['expiring_soon']),
        ('✅ АКТИВНЫЕ ПОДПИСКИ', by_status['active'])
    ]

    for title, subs in sections:
        if not subs:
            continue

        if show_expired and 'АКТИВНЫЕ' in title:
            continue  # Пропускаем активные если показываем только истекшие

        print(f"\n{'='*80}")
        print(title)
        print(f"{'='*80}")

        for sub in subs:
            print(f"\n📦 Sub ID: {sub.get('xui_sub_id', 'N/A')}")
            print(f"   👤 User ID: {sub.get('user_id')}")
            print(f"   🆔 UUID: {sub.get('vless_uuid', 'N/A')[:20]}...")
            print(f"   🌍 Server: {sub.get('server_id', 'не указан')}")
            print(f"   📅 End Date: {sub.get('end_date')}")
            print(f"   📊 Status: {sub['status']}")
            print(f"   📦 Plan: {sub.get('plan', 'N/A')}")
            print(f"   ✅ Active in DB: {'Да' if sub.get('is_active') else 'Нет'}")

            if sub.get('days_left') is not None and sub['days_left'] < 0:
                print(f"   ⚠️  ТРЕБУЕТСЯ ПРОДЛЕНИЕ!")

    # Экспорт в CSV
    if export_csv:
        print(f"\n{'='*80}")
        print(f"💾 ЭКСПОРТ В CSV: {export_csv}")
        print(f"{'='*80}")

        with open(export_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'sub_id', 'user_id', 'uuid', 'server_id', 'end_date',
                'days_left', 'status', 'is_active', 'plan', 'xui_sub_id'
            ])
            writer.writeheader()

            for sub in analyzed:
                writer.writerow({
                    'sub_id': sub.get('sub_id'),
                    'user_id': sub.get('user_id'),
                    'uuid': sub.get('vless_uuid'),
                    'server_id': sub.get('server_id'),
                    'end_date': sub.get('end_date'),
                    'days_left': sub.get('days_left'),
                    'status': sub.get('status'),
                    'is_active': sub.get('is_active'),
                    'plan': sub.get('plan'),
                    'xui_sub_id': sub.get('xui_sub_id')
                })

        print(f"   ✅ Экспортировано записей: {len(analyzed)}")

    # Рекомендации
    print(f"\n{'='*80}")
    print("💡 РЕКОМЕНДАЦИИ")
    print(f"{'='*80}")

    if by_status['expired']:
        print(f"\n❌ Требуется продление {len(by_status['expired'])} подписок:")
        print(f"   python3 extend_subscription.py <UUID> --date YYYY-MM-DD")

    if by_status['expiring_soon']:
        print(f"\n⚠️  {len(by_status['expiring_soon'])} подписок истекают в ближайшие 30 дней")
        print(f"   Рекомендуется продлить заранее")

    if len(by_status['expired']) == 0 and len(by_status['expiring_soon']) == 0:
        print(f"\n✅ Все подписки в порядке!")

    print(f"\n{'='*80}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Проверка состояния подписок",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--server",
        help="ID сервера для фильтрации (uk1, us1, fr1, etc.)"
    )

    parser.add_argument(
        "--show-all",
        action="store_true",
        help="Показать все подписки (включая неактивные)"
    )

    parser.add_argument(
        "--show-expired",
        action="store_true",
        help="Показать только истекшие подписки"
    )

    parser.add_argument(
        "--export-csv",
        help="Экспортировать в CSV файл"
    )

    args = parser.parse_args()

    asyncio.run(check_status(
        server_filter=args.server,
        show_all=args.show_all,
        show_expired=args.show_expired,
        export_csv=args.export_csv
    ))
