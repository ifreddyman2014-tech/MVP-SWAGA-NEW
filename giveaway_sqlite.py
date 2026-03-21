#!/usr/bin/env python3
"""
Создание гивевей-аккаунтов SWAGA VPN (SQLite-версия).
Работает со старой БД бота (vpn_bot.db) и servers.json.

Запуск: venv/bin/python3 giveaway_sqlite.py

Создаёт 5 аккаунтов на 1 месяц и 5 на 1 год.
"""
import asyncio
import json
import os
import random
import string
import sys
import uuid
from datetime import datetime, timedelta

import aiosqlite
import requests
import urllib3

urllib3.disable_warnings()

# ── Настройки ──────────────────────────────────────────────────────────────────

DB_PATH       = os.getenv("DATABASE_PATH", "./vpn_bot.db")
SERVERS_JSON  = os.getenv("SERVERS_JSON",  "./servers.json")
SUB_BASE_URL  = os.getenv("SUB_BASE_URL",  "")   # например: https://sub.swaga-vpn.ru/sub/

GIVEAWAY_PLANS = [
    ("1m",  30,  5),
    ("1y", 365,  5),
]

GIVEAWAY_USER_ID_START = 9_000_000_000


# ── Утилиты ────────────────────────────────────────────────────────────────────

def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_sub_id() -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=16))


# ── Работа с servers.json ──────────────────────────────────────────────────────

def load_servers() -> list[dict]:
    """Загрузить активные серверы из servers.json."""
    if not os.path.exists(SERVERS_JSON):
        print(f"❌ Файл {SERVERS_JSON} не найден.")
        sys.exit(1)
    with open(SERVERS_JSON) as f:
        data = json.load(f)
    servers = data if isinstance(data, list) else data.get("servers", [])
    active = [s for s in servers if s.get("enabled", True)]
    return active


# ── Регистрация в 3X-UI ────────────────────────────────────────────────────────

def register_on_server(server: dict, uuid_str: str, email: str,
                        sub_id: str, expiry_ms: int) -> bool:
    """Зарегистрировать клиента в 3X-UI (синхронно)."""
    host     = server.get("xui_host") or server.get("host", "")
    port     = server.get("xui_port") or server.get("panel_port", 2053)
    path     = server.get("xui_web_path") or server.get("web_path", "")
    username = server.get("xui_username") or server.get("panel_user", "admin")
    password = server.get("xui_password") or server.get("panel_pass", "")
    inbound  = server.get("inbound_id", 1)
    flow     = server.get("flow", "xtls-rprx-vision")

    protocol = "https" if host not in ("127.0.0.1", "localhost") else "http"
    base_url = f"{protocol}://{host}:{port}{path}"

    sess = requests.Session()
    try:
        r = sess.post(f"{base_url}/login",
                      json={"username": username, "password": password},
                      verify=False, timeout=15)
        if not r.json().get("success"):
            print(f"    ⚠️  Auth failed: {server.get('name')}")
            return False

        client_obj = {
            "id": uuid_str,
            "email": email,
            "subId": sub_id,
            "expiryTime": expiry_ms,
            "enable": True,
            "flow": flow,
            "limitIp": 0,
            "totalGB": 0,
            "tgId": "",
            "reset": 0,
        }
        settings_str = json.dumps({"clients": [client_obj]})
        payload = {"id": inbound, "settings": settings_str}

        add = sess.post(f"{base_url}/panel/api/inbounds/addClient",
                        json=payload, verify=False, timeout=15)
        result = add.json()
        if result.get("success"):
            return True

        # Дубликат — обновим
        sess.post(f"{base_url}/panel/api/inbounds/updateClient/{uuid_str}",
                  json=payload, verify=False, timeout=15)
        return True

    except Exception as e:
        print(f"    ⚠️  {server.get('name')}: {e}")
        return False


# ── БД ────────────────────────────────────────────────────────────────────────

async def get_next_giveaway_id(db) -> int:
    cur = await db.execute(
        "SELECT MAX(user_id) FROM users WHERE user_id >= ?",
        (GIVEAWAY_USER_ID_START,)
    )
    row = await cur.fetchone()
    last = row[0] if row and row[0] else GIVEAWAY_USER_ID_START - 1
    return last + 1


async def create_account(db, user_id: int, plan: str, days: int,
                          servers: list[dict]) -> dict | None:
    now      = datetime.utcnow()
    end      = now + timedelta(days=days)
    expiry_ms = int(end.timestamp() * 1000)

    uuid_str = generate_uuid()
    sub_id   = generate_sub_id()
    email    = f"giveaway_{user_id}"

    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, username, reg_date, trial_used) "
        "VALUES (?, ?, ?, ?)",
        (user_id, f"giveaway_{user_id}", now.isoformat(), 1),
    )

    # Пробуем обе схемы таблицы subscriptions (старая и более новая)
    try:
        await db.execute(
            "INSERT INTO subscriptions "
            "(user_id, plan, start_date, end_date, is_active, "
            " vless_uuid, xui_sub_id, server_id, xui_email) "
            "VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (user_id, plan, now.isoformat(), end.isoformat(),
             uuid_str, sub_id, "fr1", email),
        )
    except Exception:
        # Запасной вариант — минимальная схема
        await db.execute(
            "INSERT INTO subscriptions "
            "(user_id, plan, start_date, end_date, is_active, vless_uuid, xui_sub_id) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (user_id, plan, now.isoformat(), end.isoformat(), uuid_str, sub_id),
        )

    await db.commit()

    ok_servers = []
    for srv in servers:
        ok = register_on_server(srv, uuid_str, email, sub_id, expiry_ms)
        if ok:
            ok_servers.append(srv.get("name", "?"))

    sub_url     = f"{SUB_BASE_URL}{sub_id}" if SUB_BASE_URL else f"(sub_id: {sub_id})"
    connect_url = SUB_BASE_URL.replace("/sub/", "/connect/") + sub_id if SUB_BASE_URL else ""

    return {
        "user_id":     user_id,
        "plan":        plan,
        "days":        days,
        "end_date":    end.strftime("%d.%m.%Y"),
        "sub_url":     sub_url,
        "connect_url": connect_url,
        "uuid":        uuid_str,
        "servers":     ok_servers,
    }


# ── main ───────────────────────────────────────────────────────────────────────

async def main():
    print("🚀 SWAGA VPN — Создание гивевей-аккаунтов\n")

    servers = load_servers()
    if not servers:
        print("❌ Нет активных серверов в servers.json")
        sys.exit(1)
    print(f"🌍 Серверы: {', '.join(s.get('name', '?') for s in servers)}\n")

    if not SUB_BASE_URL:
        print("⚠️  SUB_BASE_URL не задан в .env — ссылки будут без домена\n")

    results = []

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        next_id = await get_next_giveaway_id(db)

        for plan, days, count in GIVEAWAY_PLANS:
            label = "1 месяц" if plan == "1m" else "1 год"
            print(f"📦 Создаю {count} аккаунтов [{label}]...")

            for i in range(count):
                uid = next_id + i
                print(f"  [{i+1}/{count}] user_id={uid} ...", end=" ", flush=True)
                acc = await create_account(db, uid, plan, days, servers)
                if acc:
                    results.append(acc)
                    synced = ", ".join(acc["servers"]) or "нет"
                    print(f"✅ [{synced}]")
                else:
                    print("❌ ошибка")

            next_id += count
            print()

    print("\n" + "=" * 60)
    print("✅ ГОТОВЫЕ АККАУНТЫ ДЛЯ РАЗДАЧИ")
    print("=" * 60)

    for i, acc in enumerate(results, 1):
        label = "1 месяц" if acc["plan"] == "1m" else "1 год"
        print(f"\n{'─' * 50}")
        print(f"#{i} | {label} | до {acc['end_date']}")
        if acc["connect_url"]:
            print(f"🔗 Быстрое подключение:\n   {acc['connect_url']}")
        print(f"📋 Ссылка на подписку:\n   {acc['sub_url']}")

    print(f"\n{'=' * 60}")
    print(f"Итого создано: {len(results)} аккаунтов")
    print(f"  • {sum(1 for a in results if a['plan'] == '1m')} × 1 месяц")
    print(f"  • {sum(1 for a in results if a['plan'] == '1y')} × 1 год")


if __name__ == "__main__":
    asyncio.run(main())
