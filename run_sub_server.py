#!/usr/bin/env python3
"""Запуск subscription server с детальным логированием"""

import asyncio
import logging
import sys

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)

logger = logging.getLogger(__name__)

async def main():
    logger.info("="*60)
    logger.info("Запуск subscription server...")
    logger.info("="*60)

    try:
        from sub_app import start_sub_server
        await start_sub_server()
        logger.info("✅ Subscription server запущен на http://127.0.0.1:8888")
        logger.info("🔗 Тестовые URL:")
        logger.info("   curl http://127.0.0.1:8888/sub/im8ccac3hknqi1ob")
        logger.info("   curl http://127.0.0.1:8888/sub/yiqgsr0kg92a5fgx")
        logger.info("   curl http://127.0.0.1:8888/sub/4dj2j16uvawqeb9r")
        logger.info("")
        logger.info("⏳ Сервер будет работать 10 минут...")

        # Держим сервер живым
        await asyncio.sleep(600)

    except Exception as e:
        logger.error(f"❌ Ошибка запуска: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
