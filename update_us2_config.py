#!/usr/bin/env python3
"""
Скрипт для обновления конфигурации сервера us2 (31.57.38.104)
"""
import json
from datetime import datetime

def update_us2_config():
    # Создать бэкап
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open("servers.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(f"servers.json.backup.{timestamp}", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ Создан бэкап: servers.json.backup.{timestamp}")

    # Найти и обновить сервер us2
    us2_found = False
    for server in data["servers"]:
        if server["id"] == "us2":
            us2_found = True
            print(f"\n🔧 Обновляю сервер {server['name']} ({server['host']})...")

            # Обновить данные из x-ui settings
            server["xui_port"] = 448
            server["xui_web_path"] = "/GfyuolnBsW3xxkwVtB"
            server["vpn_port"] = 52670  # Из netstat/ss вывода

            print(f"   ✅ Panel port: {server['xui_port']}")
            print(f"   ✅ Web path: {server['xui_web_path']}")
            print(f"   ✅ VPN port: {server['vpn_port']}")

            # Проверить какие данные еще PLACEHOLDER
            needs_config = []
            if server["xui_username"] == "PLACEHOLDER":
                needs_config.append("xui_username")
            if server["xui_password"] == "PLACEHOLDER":
                needs_config.append("xui_password")
            if server["reality_pbk"] == "PLACEHOLDER":
                needs_config.append("reality_pbk")
            if server["reality_sid"] == "PLACEHOLDER":
                needs_config.append("reality_sid")

            if needs_config:
                print(f"\n   ⚠️  Требуется ввести следующие данные:")
                for field in needs_config:
                    print(f"      - {field}")

                print(f"\n   📝 Для получения учетных данных x-ui:")
                print(f"      ssh root@31.57.38.104")
                print(f"      Посмотреть в ~/.x-ui/ или в логах первой установки")

                print(f"\n   📝 Для получения Reality ключей:")
                print(f"      1. Зайти в панель: https://31.57.38.104:448/GfyuolnBsW3xxkwVtB/")
                print(f"      2. Inbounds → Найти активный inbound → Settings")
                print(f"      3. Скопировать publicKey и shortId")

            break

    if not us2_found:
        print(f"\n❌ Сервер us2 не найден в конфигурации!")
        return

    # Сохранить обновленную конфигурацию
    with open("servers.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Конфигурация us2 частично обновлена")

    # Вывести итоговую информацию
    print("\n" + "="*70)
    print("КОНФИГУРАЦИЯ СЕРВЕРА США 2 (us2):")
    print("="*70)

    for server in data["servers"]:
        if server["id"] == "us2":
            print(f"\n🇺🇸 {server['name']}")
            print(f"   Host: {server['host']}")
            print(f"   Panel: https://{server['xui_host']}:{server['xui_port']}{server['xui_web_path']}/")
            print(f"   Panel Port: {server['xui_port']} ✅")
            print(f"   VPN Port: {server['vpn_port']} ✅")
            print(f"   Username: {server['xui_username']} {'⚠️' if server['xui_username'] == 'PLACEHOLDER' else '✅'}")
            print(f"   Password: {server['xui_password']} {'⚠️' if server['xui_password'] == 'PLACEHOLDER' else '✅'}")
            print(f"   Reality PBK: {server['reality_pbk'][:20]}... {'⚠️' if server['reality_pbk'] == 'PLACEHOLDER' else '✅'}")
            print(f"   Reality SID: {server['reality_sid']} {'⚠️' if server['reality_sid'] == 'PLACEHOLDER' else '✅'}")
            print(f"   Enabled: {server['enabled']}")

    print("\n" + "="*70)

if __name__ == "__main__":
    update_us2_config()
