#!/usr/bin/env python3
"""Инициализация БД с тестовыми подписками"""

import sqlite3

DB_PATH = "vpn_bot.db"

# Тестовые UUID для VLESS (случайные, но валидные)
TEST_UUIDS = {
    'im8ccac3hknqi1ob': 'a1b2c3d4-e5f6-4789-a1b2-c3d4e5f67890',
    'yiqgsr0kg92a5fgx': 'b2c3d4e5-f6a7-4890-b2c3-d4e5f6a78901',
    '4dj2j16uvawqeb9r': 'c3d4e5f6-a7b8-4901-c3d4-e5f6a7b89012',
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Создаем таблицу subscriptions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            sub_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            xui_sub_id TEXT UNIQUE NOT NULL,
            vless_uuid TEXT NOT NULL,
            server_id TEXT,
            is_active INTEGER DEFAULT 1,
            end_date TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # Добавляем 3 тестовые подписки
    test_subs = [
        (24, 6130546533, '1m', 'im8ccac3hknqi1ob', TEST_UUIDS['im8ccac3hknqi1ob'], '', 1, '2026-03-16'),
        (25, 6219793117, 'trial', 'yiqgsr0kg92a5fgx', TEST_UUIDS['yiqgsr0kg92a5fgx'], '', 1, '2026-02-19'),
        (26, 1355248417, 'trial', '4dj2j16uvawqeb9r', TEST_UUIDS['4dj2j16uvawqeb9r'], '', 1, '2026-02-19'),
    ]

    for sub in test_subs:
        cursor.execute("""
            INSERT OR REPLACE INTO subscriptions
            (sub_id, user_id, plan, xui_sub_id, vless_uuid, server_id, is_active, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, sub)

    conn.commit()

    # Проверяем
    cursor.execute("SELECT sub_id, user_id, plan, xui_sub_id FROM subscriptions WHERE is_active=1")
    rows = cursor.fetchall()

    print("✅ База данных инициализирована!")
    print(f"📊 Добавлено {len(rows)} активных подписок:")
    for row in rows:
        print(f"   - sub_id={row[0]}, user_id={row[1]}, plan={row[2]}, xui_sub_id={row[3]}")

    conn.close()

if __name__ == "__main__":
    init_db()
