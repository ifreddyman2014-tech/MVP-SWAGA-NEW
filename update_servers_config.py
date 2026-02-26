#!/usr/bin/env python3
"""
Скрипт для обновления конфигурации серверов в servers.json
"""
import json
from datetime import datetime

def update_servers_config():
    # Создать бэкап
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open("servers.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(f"servers.json.backup.{timestamp}", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ Создан бэкап: servers.json.backup.{timestamp}")

    # Обновить сервер us1 (США - 80.76.49.140)
    for server in data["servers"]:
        if server["id"] == "us1":
            print(f"\n🔧 Обновляю сервер {server['name']} ({server['host']})...")
            print(f"   Старый порт: {server['xui_port']} → Новый: 61753")
            print(f"   Старый username: {server['xui_username']} → Новый: FkrcdX0yCG")
            print(f"   Обновление пароля...")

            server["xui_port"] = 61753
            server["xui_username"] = "FkrcdX0yCG"
            server["xui_password"] = "IOBwHAvUm6D7LiwOTz"

            print(f"   ✅ Сервер us1 обновлён")
            break

    # Добавить новый сервер us2 (США 2 - 31.57.38.104)
    us2_exists = any(s["id"] == "us2" for s in data["servers"])

    if not us2_exists:
        print(f"\n➕ Добавляю новый сервер США 2 (31.57.38.104)...")

        new_server = {
            "id": "us2",
            "name": "США 2",
            "host": "31.57.38.104",
            "xui_host": "31.57.38.104",
            "xui_port": 61753,  # Стандартный порт, нужно проверить
            "xui_web_path": "/PLACEHOLDER",  # ТРЕБУЕТСЯ ОБНОВЛЕНИЕ
            "xui_username": "PLACEHOLDER",    # ТРЕБУЕТСЯ ОБНОВЛЕНИЕ
            "xui_password": "PLACEHOLDER",    # ТРЕБУЕТСЯ ОБНОВЛЕНИЕ
            "vpn_port": 443,
            "inbound_id": 1,
            "max_users": 150,
            "priority": 10,
            "enabled": False,  # Отключен до настройки
            "location": "US",
            "transport": "tcp",
            "flow": "xtls-rprx-vision",
            "reality_pbk": "PLACEHOLDER",     # ТРЕБУЕТСЯ ОБНОВЛЕНИЕ
            "reality_sid": "PLACEHOLDER",     # ТРЕБУЕТСЯ ОБНОВЛЕНИЕ
            "reality_sni": "www.cloudflare.com",
            "reality_fp": "chrome"
        }

        data["servers"].append(new_server)
        print(f"   ⚠️  Сервер us2 добавлен с PLACEHOLDER значениями")
        print(f"   ⚠️  Требуется SSH на 31.57.38.104 и выполнить: x-ui settings")
    else:
        print(f"\n⚠️  Сервер us2 уже существует, пропускаю добавление")

    # Сохранить обновленную конфигурацию
    with open("servers.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Конфигурация обновлена в servers.json")

    # Вывести итоговую информацию
    print("\n" + "="*70)
    print("ИТОГОВАЯ КОНФИГУРАЦИЯ СЕРВЕРОВ США:")
    print("="*70)

    for server in data["servers"]:
        if server["location"] == "US":
            print(f"\n🇺🇸 {server['name']} ({server['id']})")
            print(f"   Host: {server['host']}")
            print(f"   Panel: https://{server['xui_host']}:{server['xui_port']}{server['xui_web_path']}/")
            print(f"   Username: {server['xui_username']}")
            print(f"   Password: {server['xui_password']}")
            print(f"   Enabled: {server['enabled']}")

            if "PLACEHOLDER" in str(server.values()):
                print(f"   ⚠️  ТРЕБУЕТСЯ НАСТРОЙКА!")

    print("\n" + "="*70)
    print("\nДЛЯ НАСТРОЙКИ НОВОГО СЕРВЕРА us2:")
    print("1. SSH на сервер: ssh root@31.57.38.104")
    print("2. Выполнить: x-ui settings")
    print("3. Обновить PLACEHOLDER значения в servers.json")
    print("4. Установить enabled: true когда всё готово")
    print("="*70)

if __name__ == "__main__":
    update_servers_config()
