#!/usr/bin/env python3
"""
Финальная настройка сервера us2 (31.57.38.104) - США 2
"""
import json
from datetime import datetime

def finalize_us2_config():
    # Создать бэкап
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open("servers.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(f"servers.json.backup.{timestamp}", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ Создан бэкап: servers.json.backup.{timestamp}")

    # Найти и полностью настроить us2
    us2_found = False
    for server in data["servers"]:
        if server["id"] == "us2":
            us2_found = True
            print(f"\n🔧 Финализирую настройку сервера {server['name']} ({server['host']})...")

            # Обновить все данные
            server["xui_port"] = 448
            server["xui_web_path"] = "/GfyuolnBsW3xxkwVtB"
            server["xui_username"] = "OSe2et4ceF"
            server["xui_password"] = "WcD40VPJUX"
            server["vpn_port"] = 52670
            server["reality_pbk"] = "V5bOJYzhgs3CcN_KBxqpk2fZywNb6CdBI6BqRb_fiTA"
            server["reality_sid"] = "fb7b"
            server["enabled"] = True  # Включить сервер!

            print(f"   ✅ Panel port: {server['xui_port']}")
            print(f"   ✅ Web path: {server['xui_web_path']}")
            print(f"   ✅ Username: {server['xui_username']}")
            print(f"   ✅ Password: {'*' * len(server['xui_password'])}")
            print(f"   ✅ VPN port: {server['vpn_port']}")
            print(f"   ✅ Reality publicKey: {server['reality_pbk'][:30]}...")
            print(f"   ✅ Reality shortId: {server['reality_sid']}")
            print(f"   ✅ Сервер ВКЛЮЧЕН (enabled: true)")

            break

    if not us2_found:
        print(f"\n❌ Сервер us2 не найден в конфигурации!")
        return

    # Сохранить обновленную конфигурацию
    with open("servers.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Конфигурация us2 ПОЛНОСТЬЮ настроена и готова к работе!")

    # Вывести итоговую информацию по всем US серверам
    print("\n" + "="*70)
    print("ВСЕ СЕРВЕРЫ США:")
    print("="*70)

    for server in data["servers"]:
        if server["location"] == "US":
            status_icon = "🟢" if server["enabled"] else "🔴"
            print(f"\n{status_icon} {server['name']} ({server['id']})")
            print(f"   Host: {server['host']}")
            print(f"   Panel: https://{server['xui_host']}:{server['xui_port']}{server['xui_web_path']}/")
            print(f"   Username: {server['xui_username']}")
            print(f"   Password: {server['xui_password']}")
            print(f"   VPN Port: {server['vpn_port']}")
            print(f"   Max Users: {server['max_users']}")
            print(f"   Priority: {server['priority']}")
            print(f"   Enabled: {server['enabled']}")

    print("\n" + "="*70)
    print("✅ Конфигурация готова!")
    print("🚀 Сервер us2 теперь активен и будет использоваться для создания пользователей.")
    print("="*70)

if __name__ == "__main__":
    finalize_us2_config()
