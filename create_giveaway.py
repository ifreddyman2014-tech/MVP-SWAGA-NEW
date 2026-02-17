#!/usr/bin/env python3
"""
Создание гивевей-аккаунтов SWAGA VPN.
Запуск: python3 create_giveaway.py
Создаёт 5 аккаунтов на 1 месяц и 5 на 1 год, регистрирует в 3X-UI на всех серверах.
"""

import asyncio
import json
import sys
import urllib3
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
urllib3.disable_warnings()

import aiosqlite
from config import DB_PATH, SUB_BASE_URL
from utils import generate_uuid, generate_sub_id

GIVEAWAY_PLANS = [
    ("1m", 30,  5),   # (план, дней, количество)
    ("1y", 365, 5),
]

# Fake user_id диапазон для гивевей (не конфликтует с реальными Telegram ID)
GIVEAWAY_USER_ID_START = 9_000_000_000


async def get_next_giveaway_id(db) -> int:
    """Найти следующий свободный giveaway user_id."""
    cursor = await db.execute(
        "SELECT MAX(user_id) FROM users WHERE user_id >= ?", (GIVEAWAY_USER_ID_START,)
    )
    row = await cursor.fetchone()
    last = row[0] if row and row[0] else GIVEAWAY_USER_ID_START - 1
    return last + 1


def register_client_on_server(server, uuid_str: str, email: str,
                               sub_id: str, expiry_ms: int) -> bool:
    """Зарегистрировать клиента в 3X-UI на одном сервере (синхронно)."""
    import requests
    requests.packages.urllib3.disable_warnings()

    protocol = "https" if server.xui_host not in ("127.0.0.1", "localhost") else "http"
    base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"

    session = requests.Session()
    try:
        resp = session.post(
            f"{base_url}/login",
            json={"username": server.xui_username, "password": server.xui_password},
            verify=False, timeout=15,
        )
        if not resp.json().get("success"):
            print(f"  ⚠️  Auth failed on {server.name}")
            return False

        settings = json.dumps({"clients": [{
            "id": uuid_str,
            "email": email,
            "subId": sub_id,
            "expiryTime": expiry_ms,
            "enable": True,
            "flow": server.flow or "",
            "limitIp": 0,
            "totalGB": 0,
            "tgId": "",
            "reset": 0,
        }]})
        add_resp = session.post(
            f"{base_url}/panel/api/inbounds/addClient",
            json={"id": server.inbound_id, "settings": settings},
            verify=False, timeout=15,
        )
        result = add_resp.json()
        if result.get("success"):
            return True
        # Если дубликат — попробуем update
        session.post(
            f"{base_url}/panel/api/inbounds/updateClient/{uuid_str}",
            json={"id": server.inbound_id, "settings": settings},
            verify=False, timeout=15,
        )
        return True
    except Exception as e:
        print(f"  ⚠️  Error on {server.name}: {e}")
        return False


async def create_account(db, user_id: int, plan: str, days: int,
                         enabled_servers: list) -> dict | None:
    """Создать один гивевей аккаунт."""
    now = datetime.utcnow()
    end = now + timedelta(days=days)
    expiry_ms = int(end.timestamp() * 1000)

    uuid_str = generate_uuid()
    sub_id = generate_sub_id()
    email = f"giveaway_{user_id}"

    # Создаём пользователя в БД
    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, username, reg_date, trial_used) VALUES (?, ?, ?, ?)",
        (user_id, f"giveaway_{user_id}", now.isoformat(), 1),
    )

    # Создаём подписку
    await db.execute(
        """INSERT INTO subscriptions
           (user_id, plan, start_date, end_date, is_active, vless_uuid, xui_sub_id, server_id, xui_email)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)""",
        (user_id, plan, now.isoformat(), end.isoformat(),
         uuid_str, sub_id, "fr1", email),
    )
    await db.commit()

    # Регистрируем в 3X-UI на всех серверах
    ok_servers = []
    for server in enabled_servers:
        ok = register_client_on_server(server, uuid_str, email, sub_id, expiry_ms)
        if ok:
            ok_servers.append(server.name)

    return {
        "user_id": user_id,
        "plan": plan,
        "days": days,
        "end_date": end.strftime("%d.%m.%Y"),
        "sub_url": f"{SUB_BASE_URL}{sub_id}",
        "connect_url": SUB_BASE_URL.replace("/sub/", "/connect/") + sub_id,
        "uuid": uuid_str,
        "servers": ok_servers,
    }


async def main():
    from servers import server_manager
    server_manager.load_config()
    enabled_servers = [s for s in server_manager.get_all_servers() if s.enabled]

    if not enabled_servers:
        print("❌ Нет включённых серверов в servers.json")
        sys.exit(1)

    print(f"🌍 Серверы: {', '.join(s.name for s in enabled_servers)}\n")

    results = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        next_id = await get_next_giveaway_id(db)

        for plan, days, count in GIVEAWAY_PLANS:
            plan_name = "1 месяц" if plan == "1m" else "1 год"
            print(f"📦 Создаю {count} аккаунтов [{plan_name}]...")
            for i in range(count):
                user_id = next_id + i
                print(f"  [{i+1}/{count}] user_id={user_id} ...", end=" ", flush=True)
                acc = await create_account(db, user_id, plan, days, enabled_servers)
                if acc:
                    results.append(acc)
                    print(f"✅ {', '.join(acc['servers'])}")
                else:
                    print("❌ ошибка")
            next_id += count
            print()

    # Выводим итог
    print("\n" + "="*60)
    print("✅ ГОТОВЫЕ АККАУНТЫ ДЛЯ РАЗДАЧИ")
    print("="*60)

    for i, acc in enumerate(results, 1):
        plan_label = "1 месяц" if acc["plan"] == "1m" else "1 год"
        print(f"\n{'─'*50}")
        print(f"#{i} | {plan_label} | до {acc['end_date']}")
        print(f"🔗 Быстрое подключение:")
        print(f"   {acc['connect_url']}")
        print(f"📋 Ссылка на подписку (для приложений):")
        print(f"   {acc['sub_url']}")

    print(f"\n{'='*60}")
    print(f"Итого создано: {len(results)} аккаунтов")
    print(f"  • {sum(1 for a in results if a['plan']=='1m')} × 1 месяц")
    print(f"  • {sum(1 for a in results if a['plan']=='1y')} × 1 год")


if __name__ == "__main__":
    asyncio.run(main())
