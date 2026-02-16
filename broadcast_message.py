#!/usr/bin/env python3
"""
Скрипт для массовой рассылки сообщений всем пользователям бота.
"""

import asyncio
import aiosqlite
from aiogram import Bot
from config import BOT_TOKEN, DB_PATH

# Сообщение для рассылки
MESSAGE = """🔧 Уведомление о технических работах

Здравствуйте!

Сообщаем, что в данный момент наша система автоматической генерации и выдачи VPN-ключей находится на техническом обслуживании.

📌 Что это значит:
• Временно недоступна автоматическая выдача ключей
• Ссылки подписок могут не работать
• Оплата и выдача производятся в ручном режиме

✅ Как получить доступ к VPN:
1. Напишите в нашу службу поддержки: @swaga_support
2. Укажите, что вам нужен VPN-ключ
3. Мы вручную сгенерируем и отправим вам ключи для всех серверов

⏱ Сроки:
Мы активно работаем над восстановлением автоматической системы. Ожидаемое время устранения проблемы — в ближайшие часы.

Приносим извинения за временные неудобства и благодарим за терпение!

С уважением,
Команда SWAGA VPN 💜"""


async def get_all_users() -> list[int]:
    """Получить список всех user_id из базы данных."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def broadcast():
    """Отправить сообщение всем пользователям."""
    bot = Bot(token=BOT_TOKEN)

    print("🚀 Начинаем рассылку...")
    print(f"📊 Получаем список пользователей из {DB_PATH}")

    users = await get_all_users()
    total = len(users)

    print(f"✅ Найдено пользователей: {total}")
    print(f"📨 Начинаем отправку...\n")

    success = 0
    failed = 0
    blocked = 0

    for i, user_id in enumerate(users, 1):
        try:
            await bot.send_message(
                chat_id=user_id,
                text=MESSAGE,
                parse_mode=None
            )
            success += 1
            print(f"✅ [{i}/{total}] Отправлено пользователю {user_id}")

            # Небольшая задержка, чтобы не превысить лимиты Telegram API
            await asyncio.sleep(0.05)  # 50ms задержка между сообщениями

        except Exception as e:
            error_msg = str(e)

            # Пользователь заблокировал бота
            if "bot was blocked" in error_msg.lower() or "user is deactivated" in error_msg.lower():
                blocked += 1
                print(f"🚫 [{i}/{total}] Пользователь {user_id} заблокировал бота")
            else:
                failed += 1
                print(f"❌ [{i}/{total}] Ошибка отправки пользователю {user_id}: {error_msg}")

            await asyncio.sleep(0.05)

    # Итоговая статистика
    print("\n" + "="*60)
    print("📊 СТАТИСТИКА РАССЫЛКИ:")
    print(f"   Всего пользователей: {total}")
    print(f"   ✅ Успешно отправлено: {success}")
    print(f"   🚫 Заблокировали бота: {blocked}")
    print(f"   ❌ Ошибки отправки: {failed}")
    print("="*60)

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(broadcast())
