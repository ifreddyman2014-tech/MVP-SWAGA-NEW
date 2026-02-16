#!/usr/bin/env python3
"""Тестовый запуск subscription server без бота"""

import asyncio
import logging
from sub_app import start_sub_server

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

async def main():
    # Запускаем subscription server
    await start_sub_server()
    print("✅ Subscription server запущен на http://127.0.0.1:8889")
    print("🔗 Тестовые URL:")
    print("   http://127.0.0.1:8889/sub/im8ccac3hknqi1ob")
    print("   http://127.0.0.1:8889/sub/yiqgsr0kg92a5fgx")
    print("   http://127.0.0.1:8889/sub/4dj2j16uvawqeb9r")
    print("\n⌨️  Нажмите Ctrl+C для остановки")

    # Держим сервер запущенным
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Остановка сервера...")

if __name__ == "__main__":
    asyncio.run(main())
