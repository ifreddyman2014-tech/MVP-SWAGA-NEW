#!/usr/bin/env python3
"""
Одноразовый скрипт: добавляет всех активных клиентов из БД
во все включённые серверы (для миграции с xhttp на TCP).

Запуск:
    python3 sync_clients_to_servers.py --dry-run   # проверка без изменений
    python3 sync_clients_to_servers.py             # реальный запуск
"""

import argparse
import sqlite3
import sys
from datetime import datetime

from config import DB_PATH
from servers import server_manager
from xui_api import XUIAPI


def build_server_xui(server) -> XUIAPI:
    xui = XUIAPI()
    protocol = "https" if server.xui_host not in ("127.0.0.1", "localhost") else "http"
    xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
    return xui


def get_active_subscriptions():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT vless_uuid, xui_email, xui_sub_id, end_date
           FROM subscriptions
           WHERE is_active = 1
             AND end_date > datetime('now')
             AND vless_uuid IS NOT NULL
             AND vless_uuid != ''"""
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def ms_from_date(end_date: str) -> int:
    try:
        dt = datetime.fromisoformat(end_date)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def main(dry_run: bool):
    server_manager.load_config()
    enabled_servers = [s for s in server_manager.get_all_servers() if s.enabled]

    if not enabled_servers:
        print("❌ Нет включённых серверов")
        return 1

    print(f"Серверы: {', '.join(s.name for s in enabled_servers)}")

    subs = get_active_subscriptions()
    print(f"Активных подписок: {len(subs)}")
    if not subs:
        print("Нечего синхронизировать")
        return 0

    if dry_run:
        print("\n[DRY-RUN] Реальных изменений не будет\n")

    ok = fail = 0

    for server in enabled_servers:
        print(f"\n── {server.name} (inbound {server.inbound_id}) ──")
        xui = build_server_xui(server)

        try:
            resp = xui.session.post(
                f"{xui.base_url}/login",
                json={"username": server.xui_username, "password": server.xui_password},
                verify=False, timeout=10,
            )
            if not resp.json().get("success"):
                print(f"  ❌ Авторизация не удалась")
                fail += len(subs)
                continue
            xui._logged_in = True
        except Exception as e:
            print(f"  ❌ Ошибка подключения: {e}")
            fail += len(subs)
            continue

        for sub in subs:
            uuid = sub["vless_uuid"]
            email = sub.get("xui_email") or f"sync_{uuid[:8]}"
            sub_id = sub.get("xui_sub_id") or ""
            expiry_ms = ms_from_date(sub["end_date"])

            if dry_run:
                print(f"  [dry] {email}")
                ok += 1
                continue

            try:
                result = xui.add_client(
                    server.inbound_id, uuid, email,
                    sub_id=sub_id, expiry_time=expiry_ms,
                    flow=server.flow,
                )
                if result:
                    print(f"  ✅ {email}")
                    ok += 1
                else:
                    result2 = xui.update_client(
                        server.inbound_id, uuid, email,
                        sub_id=sub_id, expiry_time=expiry_ms,
                        flow=server.flow,
                    )
                    if result2:
                        print(f"  🔄 {email} (обновлён)")
                        ok += 1
                    else:
                        print(f"  ⚠️  {email} (не удалось)")
                        fail += 1
            except Exception as e:
                print(f"  ❌ {email}: {e}")
                fail += 1

    print(f"\n{'='*40}")
    print(f"Итого: ✅ {ok}  ❌ {fail}")
    if not dry_run and ok > 0:
        print("Готово! Пользователям нужно обновить подписку в V2RayTun.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.dry_run))
