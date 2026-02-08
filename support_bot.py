"""
SWAGA VPN Support Bot — FAQ и поддержка пользователей.
"""

import logging
import os
from aiogram import Bot, Dispatcher, types, executor
from aiogram.dispatcher.filters import Text

# ── Настройки ─────────────────────────────────────────────────────────────────

SUPPORT_BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "")
OPERATOR_CHAT_ID = os.getenv("OPERATOR_CHAT_ID", "")  # ID чата/группы операторов
MAIN_BOT_URL = "https://t.me/Swaga_vpnbot"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=SUPPORT_BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)


# ── FAQ Контент ───────────────────────────────────────────────────────────────

FAQ = {
    "connect": {
        "title": "📲 Как подключиться к VPN?",
        "text": """<b>📲 Как подключиться к VPN?</b>

<b>iPhone / Android:</b>
1. Скачайте приложение <b>V2RayTun</b>:
   • <a href="https://apps.apple.com/app/v2raytun/id6476628951">App Store (iOS)</a>
   • <a href="https://play.google.com/store/apps/details?id=com.v2raytun.android">Google Play (Android)</a>

2. В боте @Swaga_vpnbot нажмите <b>«Личный кабинет»</b>

3. Нажмите <b>«Быстрое подключение»</b> — конфигурация добавится автоматически

4. В приложении нажмите кнопку подключения ▶️

<b>Windows / macOS:</b>
1. Скачайте <b>v2rayN</b> (Windows) или <b>v2rayU</b> (macOS)
2. В Личном кабинете скопируйте VLESS-ссылку
3. В приложении: «Импорт из буфера обмена»
4. Подключитесь к серверу""",
    },
    "not_working": {
        "title": "🔧 VPN не работает",
        "text": """<b>🔧 VPN не работает, что делать?</b>

<b>Проверьте:</b>

1️⃣ <b>Активна ли подписка?</b>
   Зайдите в @Swaga_vpnbot → Личный кабинет

2️⃣ <b>Правильный ли конфиг?</b>
   Удалите старый конфиг в V2RayTun и добавьте заново через «Быстрое подключение»

3️⃣ <b>Попробуйте другой сервер</b>
   В боте: Тарифы → выберите другую страну

4️⃣ <b>Перезапустите приложение</b>
   Закройте V2RayTun полностью и откройте снова

5️⃣ <b>Проверьте интернет</b>
   Убедитесь, что интернет работает без VPN

<b>Всё ещё не работает?</b>
Напишите оператору — поможем разобраться!""",
    },
    "extend": {
        "title": "🔄 Как продлить подписку?",
        "text": """<b>🔄 Как продлить подписку?</b>

1. Откройте @Swaga_vpnbot

2. Нажмите <b>«Тарифы»</b>

3. Выберите нужный тариф:
   • 1 месяц — 130 ₽
   • 3 месяца — 330 ₽
   • 6 месяцев — 590 ₽
   • 12 месяцев — 990 ₽

4. Выберите сервер (если несколько)

5. Оплатите картой

✅ Подписка продлится автоматически — дни добавятся к текущему сроку.

💡 <b>Совет:</b> Приглашайте друзей по реферальной ссылке — получайте +7 дней за каждого!""",
    },
    "change_server": {
        "title": "🌍 Как сменить сервер?",
        "text": """<b>🌍 Как сменить сервер?</b>

1. Откройте @Swaga_vpnbot

2. Нажмите <b>«Тарифы»</b>

3. Выберите любой тариф

4. Выберите <b>новый сервер</b> (страну)

5. После оплаты/активации — новый конфиг появится в Личном кабинете

⚠️ <b>Важно:</b> При смене сервера создаётся новая подписка. Старая конфигурация перестанет работать.

💡 Рекомендуем выбирать сервер ближе к вам географически для лучшей скорости.""",
    },
    "refund": {
        "title": "💰 Возврат средств",
        "text": """<b>💰 Возврат средств</b>

Мы делаем возврат если:
• VPN не работает и мы не смогли решить проблему
• Ошибочная двойная оплата

<b>Для возврата:</b>
1. Напишите оператору (кнопка ниже)
2. Укажите причину возврата
3. Приложите скриншот оплаты

Возврат обрабатывается в течение 3 рабочих дней.

⚠️ Возврат не делается если:
• Подписка уже использовалась более 3 дней
• Нарушены правила использования""",
    },
    "ads": {
        "title": "📢 Реклама и сотрудничество",
        "text": """<b>📢 Реклама и сотрудничество</b>

Мы открыты к сотрудничеству!

<b>Предлагаем:</b>
• Партнёрская программа для блогеров
• Реферальная система с бонусами
• Интеграции и коллаборации

<b>Для связи:</b>
Напишите оператору с темой «Сотрудничество» — обсудим условия.""",
    },
}


# ── Клавиатуры ────────────────────────────────────────────────────────────────

def main_menu_kb() -> types.ReplyKeyboardMarkup:
    """Главное меню FAQ."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📲 Как подключиться?"))
    kb.add(types.KeyboardButton("🔧 VPN не работает"))
    kb.add(
        types.KeyboardButton("🔄 Продлить подписку"),
        types.KeyboardButton("🌍 Сменить сервер"),
    )
    kb.add(
        types.KeyboardButton("💰 Возврат средств"),
        types.KeyboardButton("📢 Сотрудничество"),
    )
    kb.add(types.KeyboardButton("👨‍💻 Связаться с оператором"))
    return kb


def back_kb() -> types.InlineKeyboardMarkup:
    """Кнопка возврата в меню."""
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")
    )


def operator_kb() -> types.InlineKeyboardMarkup:
    """Кнопки после FAQ — связь с оператором."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("👨‍💻 Написать оператору", callback_data="contact_operator"),
        types.InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu"),
    )
    return kb


# ── Обработчики ───────────────────────────────────────────────────────────────

LOGO_PATH = "/root/MVP-SWAGA-NEW/media/support_logo.png"


@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message) -> None:
    """Приветствие с логотипом."""
    import os
    caption = (
        "👋 <b>Добро пожаловать в поддержку SWAGA VPN!</b>\n\n"
        "Выберите тему вопроса из меню ниже.\n"
        "Если не нашли ответ — напишите оператору."
    )
    if os.path.exists(LOGO_PATH):
        with open(LOGO_PATH, "rb") as photo:
            await message.answer_photo(
                photo,
                caption=caption,
                reply_markup=main_menu_kb(),
            )
    else:
        await message.answer(caption, reply_markup=main_menu_kb())


@dp.callback_query_handler(lambda c: c.data == "main_menu")
async def cb_main_menu(callback: types.CallbackQuery) -> None:
    """Возврат в главное меню."""
    await callback.message.answer(
        "📋 <b>Главное меню</b>\n\nВыберите тему вопроса:",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@dp.message_handler(Text(equals="📲 Как подключиться?"))
async def faq_connect(message: types.Message) -> None:
    await message.answer(FAQ["connect"]["text"], reply_markup=operator_kb(), disable_web_page_preview=True)


@dp.message_handler(Text(equals="🔧 VPN не работает"))
async def faq_not_working(message: types.Message) -> None:
    await message.answer(FAQ["not_working"]["text"], reply_markup=operator_kb())


@dp.message_handler(Text(equals="🔄 Продлить подписку"))
async def faq_extend(message: types.Message) -> None:
    await message.answer(FAQ["extend"]["text"], reply_markup=operator_kb())


@dp.message_handler(Text(equals="🌍 Сменить сервер"))
async def faq_change_server(message: types.Message) -> None:
    await message.answer(FAQ["change_server"]["text"], reply_markup=operator_kb())


@dp.message_handler(Text(equals="💰 Возврат средств"))
async def faq_refund(message: types.Message) -> None:
    await message.answer(FAQ["refund"]["text"], reply_markup=operator_kb())


@dp.message_handler(Text(equals="📢 Сотрудничество"))
async def faq_ads(message: types.Message) -> None:
    await message.answer(FAQ["ads"]["text"], reply_markup=operator_kb())


@dp.message_handler(Text(equals="👨‍💻 Связаться с оператором"))
async def contact_operator_btn(message: types.Message) -> None:
    """Инструкция для связи с оператором."""
    await message.answer(
        "👨‍💻 <b>Связь с оператором</b>\n\n"
        "Опишите вашу проблему в следующем сообщении.\n"
        "Оператор ответит в ближайшее время.\n\n"
        "📝 <i>Укажите:</i>\n"
        "• Ваш username в Telegram\n"
        "• Суть проблемы\n"
        "• Скриншот (если есть)",
    )


@dp.callback_query_handler(lambda c: c.data == "contact_operator")
async def cb_contact_operator(callback: types.CallbackQuery) -> None:
    """Callback для связи с оператором."""
    await callback.message.answer(
        "👨‍💻 <b>Связь с оператором</b>\n\n"
        "Опишите вашу проблему в следующем сообщении.\n"
        "Оператор ответит в ближайшее время.\n\n"
        "📝 <i>Укажите:</i>\n"
        "• Ваш username в Telegram\n"
        "• Суть проблемы\n"
        "• Скриншот (если есть)",
    )
    await callback.answer()


@dp.message_handler(content_types=types.ContentTypes.ANY)
async def forward_to_operator(message: types.Message) -> None:
    """Пересылка сообщений оператору и ответы от оператора."""
    # Если сообщение от оператора — это ответ пользователю
    if OPERATOR_CHAT_ID and str(message.from_user.id) == str(OPERATOR_CHAT_ID):
        # Проверяем, что это reply на пересланное сообщение
        if message.reply_to_message and message.reply_to_message.forward_from:
            user_id = message.reply_to_message.forward_from.id
            try:
                # Отправляем ответ пользователю
                await bot.send_message(
                    user_id,
                    f"💬 <b>Ответ оператора:</b>\n\n{message.text or '(медиа)'}",
                )
                await message.reply("✅ Ответ отправлен пользователю")
            except Exception as e:
                await message.reply(f"❌ Не удалось отправить: {e}")
            return
        # Если это reply на info-сообщение с ID пользователя
        elif message.reply_to_message and message.reply_to_message.text:
            import re
            match = re.search(r'ID:\s*(\d+)', message.reply_to_message.text)
            if match:
                user_id = int(match.group(1))
                try:
                    await bot.send_message(
                        user_id,
                        f"💬 <b>Ответ оператора:</b>\n\n{message.text or '(медиа)'}",
                    )
                    await message.reply("✅ Ответ отправлен пользователю")
                except Exception as e:
                    await message.reply(f"❌ Не удалось отправить: {e}")
                return

    if not OPERATOR_CHAT_ID:
        await message.answer(
            "✅ Ваше сообщение получено!\n"
            "Оператор свяжется с вами в ближайшее время.",
            reply_markup=main_menu_kb(),
        )
        return

    # Пересылаем сообщение оператору
    try:
        user = message.from_user
        user_info = f"👤 <b>Новое обращение</b>\n\n"
        user_info += f"От: @{user.username}\n" if user.username else f"От: {user.full_name}\n"
        user_info += f"ID: <code>{user.id}</code>\n"
        user_info += "─" * 20
        user_info += "\n\n💡 <i>Ответьте reply на это сообщение</i>"

        await bot.send_message(OPERATOR_CHAT_ID, user_info)
        await message.forward(OPERATOR_CHAT_ID)

        await message.answer(
            "✅ Ваше сообщение отправлено оператору!\n"
            "Ожидайте ответа.",
            reply_markup=main_menu_kb(),
        )
    except Exception as e:
        logger.error("Ошибка пересылки оператору: %s", e)
        await message.answer(
            "✅ Ваше сообщение получено!\n"
            "Оператор свяжется с вами в ближайшее время.",
            reply_markup=main_menu_kb(),
        )


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not SUPPORT_BOT_TOKEN:
        print("❌ Укажите SUPPORT_BOT_TOKEN в переменных окружения!")
        exit(1)

    logger.info("🚀 Запуск SWAGA VPN Support Bot...")
    executor.start_polling(dp, skip_updates=True)
