#!/usr/bin/env python3
"""
SWAGA VPN — Support Bot (@swagasupport_bot)
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SUPPORT_BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "")
ADMIN_CHAT_ID     = int(os.getenv("ADMIN_CHAT_ID", "0"))
MAIN_BOT_USERNAME = os.getenv("BOT_USERNAME", "Swaga_vpnbot")

if not SUPPORT_BOT_TOKEN:
    raise RuntimeError("SUPPORT_BOT_TOKEN не задан в .env")

router = Router()


# ── FSM ───────────────────────────────────────────────────────────────────────

class SupportState(StatesGroup):
    waiting_message = State()   # ждём сообщение для техподдержки


# ── Клавиатуры ────────────────────────────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Как подключиться",          callback_data="how_to_connect")],
        [InlineKeyboardButton(text="🔧 VPN не работает",           callback_data="vpn_not_working")],
        [InlineKeyboardButton(text="🔄 Продлить подписку",         callback_data="extend_sub")],
        [InlineKeyboardButton(text="🌍 Сменить сервер",            callback_data="change_server")],
        [InlineKeyboardButton(text="💸 Возврат средств",           callback_data="refund")],
        [InlineKeyboardButton(text="🤝 Сотрудничество",            callback_data="partnership")],
        [InlineKeyboardButton(text="💬 Связаться с техподдержкой", callback_data="contact_support")],
    ])


def back_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


def back_and_main(url: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if url:
        rows.append([InlineKeyboardButton(text="🚀 Перейти в основной бот", url=url)])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Добро пожаловать в поддержку SWAGA VPN!</b>\n\n"
        "Выберите тему вопроса из меню ниже.\n"
        "Если не нашли ответ — напишите оператору.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


# ── Назад ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back")
async def cb_back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "👋 <b>Добро пожаловать в поддержку SWAGA VPN!</b>\n\n"
        "Выберите тему вопроса из меню ниже.\n"
        "Если не нашли ответ — напишите оператору.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


# ── 1. Как подключиться ───────────────────────────────────────────────────────

@router.callback_query(F.data == "how_to_connect")
async def cb_how_to_connect(call: CallbackQuery):
    await call.message.edit_text(
        "📱 <b>Как подключиться к SWAGA VPN</b>\n\n"
        "<b>Шаг 1.</b> Установи приложение:\n"
        "• <b>iOS / macOS</b> — <a href='https://apps.apple.com/app/v2raytun/id6476628951'>V2RayTun</a>\n"
        "• <b>Android</b> — <a href='https://play.google.com/store/apps/details?id=com.v2raytun.android'>V2RayTun</a>\n"
        "• <b>Windows</b> — <a href='https://github.com/hiddify/hiddify-next/releases'>Hiddify</a>\n\n"
        "<b>Шаг 2.</b> Открой ссылку подключения из бота\n"
        f"(@{MAIN_BOT_USERNAME} → <i>Мой профиль</i>)\n\n"
        "<b>Шаг 3.</b> Нажми кнопку <b>«Подключить»</b> — конфиг импортируется автоматически\n\n"
        "<b>Шаг 4.</b> В приложении нажми кнопку подключения ✅\n\n"
        "❓ Всё ещё не получается? Обратись в техподдержку.",
        reply_markup=back_btn(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ── 2. VPN не работает ────────────────────────────────────────────────────────

@router.callback_query(F.data == "vpn_not_working")
async def cb_vpn_not_working(call: CallbackQuery):
    await call.message.edit_text(
        "🔧 <b>VPN не работает — что делать?</b>\n\n"
        "<b>Попробуй по порядку:</b>\n\n"
        "1️⃣ Отключись и подключись заново\n\n"
        "2️⃣ Смени сервер в приложении (если доступно несколько)\n\n"
        "3️⃣ Удали конфиг и импортируй заново — открой ссылку\n"
        f"   из @{MAIN_BOT_USERNAME} → <i>Мой профиль</i>\n\n"
        "4️⃣ Перезагрузи телефон\n\n"
        "5️⃣ Проверь, не истекла ли подписка в @{MAIN_BOT_USERNAME}\n\n"
        "Если ничего не помогло — напиши в техподдержку, "
        "укажи страну и устройство.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в техподдержку", callback_data="contact_support")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
        ]),
        parse_mode="HTML",
    )


# ── 3. Продлить подписку ─────────────────────────────────────────────────────

@router.callback_query(F.data == "extend_sub")
async def cb_extend_sub(call: CallbackQuery):
    main_bot_url = f"https://t.me/{MAIN_BOT_USERNAME}"
    await call.message.edit_text(
        "🔄 <b>Продление подписки</b>\n\n"
        f"Продлить подписку можно в основном боте @{MAIN_BOT_USERNAME}:\n\n"
        "➡️ Перейди в бот → нажми <b>«Купить подписку»</b>\n\n"
        "💡 Если у тебя активная подписка — новый период добавится к текущему сроку.",
        reply_markup=back_and_main(main_bot_url),
        parse_mode="HTML",
    )


# ── 4. Сменить сервер ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "change_server")
async def cb_change_server(call: CallbackQuery):
    main_bot_url = f"https://t.me/{MAIN_BOT_USERNAME}"
    await call.message.edit_text(
        "🌍 <b>Смена сервера</b>\n\n"
        "Твоя подписка включает <b>все доступные серверы</b> сразу:\n"
        "🇫🇷 Франция · 🇺🇸 США 1 · 🇺🇸 США 2 · 🇬🇧 Великобритания\n\n"
        "Чтобы переключить сервер:\n"
        "1. Открой приложение V2RayTun / Hiddify\n"
        "2. В списке конфигов выбери нужный сервер\n"
        "3. Нажми подключить\n\n"
        "Если серверов нет в приложении — обнови подписку через основной бот.",
        reply_markup=back_and_main(main_bot_url),
        parse_mode="HTML",
    )


# ── 5. Возврат средств ────────────────────────────────────────────────────────

@router.callback_query(F.data == "refund")
async def cb_refund(call: CallbackQuery):
    await call.message.edit_text(
        "💸 <b>Возврат средств</b>\n\n"
        "Мы рассматриваем возвраты в следующих случаях:\n"
        "• VPN не работает и техподдержка не помогла решить проблему\n"
        "• Оплата прошла, но подписка не активировалась\n\n"
        "Для оформления возврата напиши в техподдержку и укажи:\n"
        "— Дату оплаты и сумму\n"
        "— Описание проблемы\n\n"
        "⏱ Срок рассмотрения: до 3 рабочих дней.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в техподдержку", callback_data="contact_support")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
        ]),
        parse_mode="HTML",
    )


# ── 6. Сотрудничество ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "partnership")
async def cb_partnership(call: CallbackQuery):
    await call.message.edit_text(
        "🤝 <b>Сотрудничество</b>\n\n"
        "Мы открыты к партнёрству:\n\n"
        "• <b>Реферальная программа</b> — зарабатывай за приведённых пользователей\n"
        "• <b>Оптовые закупки</b> — скидки при покупке от 10 аккаунтов\n"
        "• <b>Рекламное размещение</b> — реклама в нашем боте\n"
        "• <b>Технические интеграции</b> — API и white-label решения\n\n"
        "Напиши нам — расскажи о своём предложении:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать предложение", callback_data="contact_support")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
        ]),
        parse_mode="HTML",
    )


# ── 7. Связаться с техподдержкой ─────────────────────────────────────────────

@router.callback_query(F.data == "contact_support")
async def cb_contact_support(call: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_message)
    await call.message.edit_text(
        "💬 <b>Техподдержка</b>\n\n"
        "Напиши своё сообщение — мы ответим в ближайшее время.\n\n"
        "Можешь прикрепить скриншот если нужно.",
        reply_markup=back_btn(),
        parse_mode="HTML",
    )


@router.message(StateFilter(SupportState.waiting_message))
async def handle_support_message(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    username = f"@{user.username}" if user.username else f"id{user.id}"
    header = (
        f"📩 <b>Новое обращение в поддержку</b>\n"
        f"👤 {user.full_name} ({username})\n"
        f"🆔 <code>{user.id}</code>\n"
        f"{'─' * 30}"
    )

    if ADMIN_CHAT_ID:
        try:
            await bot.send_message(ADMIN_CHAT_ID, header, parse_mode="HTML")
            await message.forward(ADMIN_CHAT_ID)
        except Exception as e:
            logger.error(f"Не удалось переслать сообщение админу: {e}")

    await state.clear()
    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "Мы ответим тебе здесь в ближайшее время.\n"
        "Среднее время ответа: <b>до 24 часов</b>.",
        reply_markup=back_btn(),
        parse_mode="HTML",
    )


# ── Ответ от админа пользователю ─────────────────────────────────────────────

@router.message(F.reply_to_message, F.chat.id == ADMIN_CHAT_ID)
async def admin_reply(message: Message, bot: Bot):
    """Когда админ отвечает на пересланное сообщение — ответ уходит пользователю."""
    replied = message.reply_to_message

    # Ищем ID пользователя в тексте header (строка "🆔 <code>ID</code>")
    if replied.text and "🆔" in replied.text:
        for line in replied.text.splitlines():
            if "🆔" in line:
                user_id_str = line.replace("🆔", "").strip().strip("<code>").strip("</code>")
                try:
                    target_id = int(user_id_str)
                    await bot.send_message(
                        target_id,
                        f"💬 <b>Ответ от поддержки:</b>\n\n{message.text}",
                        parse_mode="HTML",
                    )
                    await message.reply("✅ Ответ отправлен пользователю.")
                    return
                except (ValueError, Exception) as e:
                    logger.error(f"Не удалось отправить ответ: {e}")

    await message.reply("⚠️ Не удалось определить пользователя. Перешли сообщение вручную.")


# ── Запуск ────────────────────────────────────────────────────────────────────

async def main():
    bot = Bot(token=SUPPORT_BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Запуск SWAGA Support Bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
