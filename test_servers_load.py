#!/usr/bin/env python3
"""
Тестовый скрипт для проверки загрузки серверов из servers.json
"""

import os
import sys

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(__file__))

from servers import server_manager

def test_load_servers():
    """Тестируем загрузку серверов."""
    print("=" * 60)
    print("ТЕСТ ЗАГРУЗКИ СЕРВЕРОВ")
    print("=" * 60)

    # Проверяем наличие файла
    config_path = "./servers.json"
    if os.path.exists(config_path):
        print(f"✅ Файл {config_path} существует")
    else:
        print(f"❌ Файл {config_path} НЕ найден")
        return

    # Загружаем конфигурацию
    print("\n📥 Загружаем конфигурацию...")
    result = server_manager.load_config()

    if result:
        print("✅ Конфигурация загружена успешно")
    else:
        print("❌ Ошибка загрузки конфигурации")
        return

    # Выводим информацию о серверах
    print(f"\n📊 Всего серверов: {len(server_manager.servers)}")

    if not server_manager.servers:
        print("❌ Серверы не загружены!")
        return

    print("\n" + "=" * 60)
    print("СПИСОК СЕРВЕРОВ")
    print("=" * 60)

    for server_id, server in server_manager.servers.items():
        status = "✅ Включен" if server.enabled else "❌ Выключен"
        print(f"\nID: {server_id}")
        print(f"  Название: {server.name}")
        print(f"  Статус: {status}")
        print(f"  Хост: {server.host}")
        print(f"  Порт VPN: {server.vpn_port}")
        print(f"  Транспорт: {server.transport}")
        print(f"  Reality SNI: {server.reality_sni}")
        print(f"  Reality PBK: {server.reality_pbk[:20]}...")

    # Проверяем включенные серверы
    print("\n" + "=" * 60)
    print("ВКЛЮЧЕННЫЕ СЕРВЕРЫ")
    print("=" * 60)

    enabled = [s for s in server_manager.get_all_servers() if s.enabled]
    print(f"\n✅ Включенных серверов: {len(enabled)}")

    for srv in enabled:
        print(f"  - {srv.name} ({srv.id})")

    # Проверяем здоровые серверы
    print("\n" + "=" * 60)
    print("ЗДОРОВЫЕ СЕРВЕРЫ")
    print("=" * 60)

    healthy = server_manager.get_healthy_servers()
    print(f"\n✅ Здоровых серверов: {len(healthy)}")

    for srv in healthy:
        print(f"  - {srv.name} ({srv.id})")

    print("\n" + "=" * 60)
    print("✅ ТЕСТ ЗАВЕРШЕН")
    print("=" * 60)

if __name__ == "__main__":
    test_load_servers()
