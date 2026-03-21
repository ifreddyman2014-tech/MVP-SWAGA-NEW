#!/usr/bin/env python3
"""
SWAGA VPN — Support Bot (@swagasupport_bot)
aiogram 2.x
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SUPPORT_BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "")
ADMIN_CHAT_ID     = int(os.getenv("ADMIN_CHAT_ID", "0"))
MAIN_BOT_USERNAME = os.getenv("BOT_USERNAME", "Swaga_vpnbot")

if not SUPPORT_BOT_TOKEN:
    raise RuntimeError("SUPPORT_BOT_TOKEN не задан в .env")

bot     = Bot(token=SUPPORT_BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp      = Dispatcher(bot, storage=storage)


# ── FSM ───────────────────────────────────────────────────────────────────────

class SupportState(StatesGroup):
    waiting_message = State()


# ── Клавиатуры ────────────────────────────────────────────────────────────────

def main_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("📱 Как подключиться",          callback_data="how_to_connect"),
        types.InlineKeyboardButton("🔧 VPN не работает",           callback_data="vpn_not_working"),
        types.InlineKeyboardButton("🔄 Продлить подписку",         callback_data="extend_sub"),
        types.InlineKeyboardButton("🌍 Сменить сервер",            callback_data="change_server"),
        types.InlineKeyboardButton("💸 Возврат средств",           callback_data="refund"),
        types.InlineKeyboardButton("🤝 Сотрудничество",            callback_data="partnership"),
        types.InlineKeyboardButton("💬 Связаться с техподдержкой", callback_data="contact_support"),
    )
    return kb


def back_btn() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def back_and_main(url: str = None) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    if url:
        kb.add(types.InlineKeyboardButton("🚀 Перейти в основной бот", url=url))
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def support_and_back() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("💬 Написать в техподдержку", callback_data="contact_support"),
        types.InlineKeyboardButton("◀️ Назад", callback_data="back"),
    )
    return kb


INSTRUCTION_VIDEO = os.path.join(os.path.dirname(__file__), "media", "instruction.mp4")
SUPPORT_LOGO = os.path.join(os.path.dirname(__file__), "media", "support_logo.png")

WELCOME_TEXT = (
    "👋 <b>Добро пожаловать в поддержку SWAGA VPN!</b>\n\n"
    "Выберите тему вопроса из меню ниже.\n"
    "Если не нашли ответ — напишите оператору."
)


# ── /start ────────────────────────────────────────────────────────────────────

@dp.message_handler(commands=["start"], state="*")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    if os.path.exists(SUPPORT_LOGO):
        with open(SUPPORT_LOGO, "rb") as photo:
            await message.answer_photo(photo, caption=WELCOME_TEXT, reply_markup=main_menu())
    else:
        await message.answer(WELCOME_TEXT, reply_markup=main_menu())


# ── Назад ─────────────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "back", state="*")
async def cb_back(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.message.delete()
    if os.path.exists(SUPPORT_LOGO):
        with open(SUPPORT_LOGO, "rb") as photo:
            await call.message.answer_photo(photo, caption=WELCOME_TEXT, reply_markup=main_menu())
    else:
        await call.message.answer(WELCOME_TEXT, reply_markup=main_menu())
    await call.answer()


# ── 1. Как подключиться ───────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "how_to_connect")
async def cb_how_to_connect(call: types.CallbackQuery):
    await call.message.edit_text(
        "📱 <b>Как подключиться к SWAGA VPN</b>\n\n"
        "<b>Шаг 1.</b> Установи приложение:\n"
        "• <b>iOS / macOS</b> — <a href='https://apps.apple.com/app/v2raytun/id6476628951'>V2RayTun</a>\n"
        "• <b>Android</b> — <a href='https://play.google.com/store/apps/details?id=com.v2raytun.android'>V2RayTun</a>\n"
        "• <b>Windows</b> — <a href='https://github.com/2dust/v2rayn/releases'>V2RayN</a>\n\n"
        f"<b>Шаг 2.</b> Открой ссылку подключения из @{MAIN_BOT_USERNAME}\n"
        "(<i>Мой профиль → Подключить</i>)\n\n"
        "<b>Шаг 3.</b> Нажми <b>«Подключить»</b> — конфиг импортируется автоматически\n\n"
        "<b>Шаг 4.</b> В приложении нажми кнопку подключения ✅\n\n"
        "❓ Всё ещё не получается? Обратись в техподдержку.",
        reply_markup=back_btn(),
        disable_web_page_preview=True,
    )
    # Отправляем видео-инструкцию если файл есть
    if os.path.exists(INSTRUCTION_VIDEO):
        with open(INSTRUCTION_VIDEO, "rb") as video:
            await call.message.answer_video(
                video,
                caption="🎬 <b>Видео-инструкция по подключению с компьютера (Windows)</b>",
            )
    await call.answer()


# ── 2. VPN не работает ────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "vpn_not_working")
async def cb_vpn_not_working(call: types.CallbackQuery):
    await call.message.edit_text(
        "🔧 <b>VPN не работает — что делать?</b>\n\n"
        "1️⃣ Отключись и подключись заново\n\n"
        "2️⃣ Смени сервер в приложении\n\n"
        "3️⃣ Удали конфиг и импортируй заново через ссылку\n"
        f"   из @{MAIN_BOT_USERNAME} → <i>Мой профиль</i>\n\n"
        "4️⃣ Перезагрузи телефон\n\n"
        f"5️⃣ Проверь, не истекла ли подписка в @{MAIN_BOT_USERNAME}\n\n"
        "Если ничего не помогло — напиши в техподдержку, укажи страну и устройство.",
        reply_markup=support_and_back(),
    )
    await call.answer()


# ── 3. Продлить подписку ─────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "extend_sub")
async def cb_extend_sub(call: types.CallbackQuery):
    await call.message.edit_text(
        "🔄 <b>Продление подписки</b>\n\n"
        f"Продлить подписку можно в основном боте @{MAIN_BOT_USERNAME}:\n\n"
        "➡️ Перейди в бот → нажми <b>«Купить подписку»</b>\n\n"
        "💡 Если у тебя активная подписка — новый период добавится к текущему сроку.",
        reply_markup=back_and_main(f"https://t.me/{MAIN_BOT_USERNAME}"),
    )
    await call.answer()


# ── 4. Сменить сервер ─────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "change_server")
async def cb_change_server(call: types.CallbackQuery):
    await call.message.edit_text(
        "🌍 <b>Смена сервера</b>\n\n"
        "Твоя подписка включает <b>все доступные серверы</b> сразу:\n"
        "🇫🇷 Франция · 🇺🇸 США 1 · 🇺🇸 США 2 · 🇬🇧 Великобритания\n\n"
        "Как переключить сервер:\n"
        "1. Открой V2RayTun / Hiddify\n"
        "2. В списке конфигов выбери нужный сервер\n"
        "3. Нажми подключить\n\n"
        "Если серверов нет в приложении — обнови подписку через основной бот.",
        reply_markup=back_and_main(f"https://t.me/{MAIN_BOT_USERNAME}"),
    )
    await call.answer()


# ── 5. Возврат средств ────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "refund")
async def cb_refund(call: types.CallbackQuery):
    await call.message.edit_text(
        "💸 <b>Возврат средств</b>\n\n"
        "Мы рассматриваем возвраты если:\n"
        "• VPN не работает и техподдержка не помогла\n"
        "• Оплата прошла, но подписка не активировалась\n\n"
        "Для оформления напиши в техподдержку и укажи:\n"
        "— Дату оплаты и сумму\n"
        "— Описание проблемы\n\n"
        "⏱ Срок рассмотрения: до 3 рабочих дней.",
        reply_markup=support_and_back(),
    )
    await call.answer()


# ── 6. Сотрудничество ─────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "partnership")
async def cb_partnership(call: types.CallbackQuery):
    await call.message.edit_text(
        "🤝 <b>Сотрудничество</b>\n\n"
        "Мы открыты к партнёрству:\n\n"
        "• <b>Реферальная программа</b> — зарабатывай за приведённых пользователей\n"
        "• <b>Оптовые закупки</b> — скидки при покупке от 10 аккаунтов\n"
        "• <b>Рекламное размещение</b> — реклама в нашем боте\n"
        "• <b>Технические интеграции</b> — API и white-label решения\n\n"
        "Напиши нам — расскажи о своём предложении:",
        reply_markup=support_and_back(),
    )
    await call.answer()


# ── 7. Связаться с техподдержкой ─────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "contact_support")
async def cb_contact_support(call: types.CallbackQuery):
    await SupportState.waiting_message.set()
    await call.message.edit_text(
        "💬 <b>Техподдержка</b>\n\n"
        "Напиши своё сообщение — мы ответим в ближайшее время.\n"
        "Можешь прикрепить скриншот.",
        reply_markup=back_btn(),
    )
    await call.answer()


@dp.message_handler(state=SupportState.waiting_message, content_types=types.ContentTypes.ANY)
async def handle_support_message(message: types.Message, state: FSMContext):
    user = message.from_user
    username = f"@{user.username}" if user.username else f"id{user.id}"

    if ADMIN_CHAT_ID:
        try:
            header = (
                f"📩 <b>Новое обращение в поддержку</b>\n"
                f"👤 {user.full_name} ({username})\n"
                f"🆔 <code>{user.id}</code>\n"
                f"{'─' * 30}"
            )
            await bot.send_message(ADMIN_CHAT_ID, header)
            await message.forward(ADMIN_CHAT_ID)
        except Exception as e:
            logger.error(f"Не удалось переслать сообщение админу: {e}")

    await state.finish()
    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "Мы ответим тебе здесь в ближайшее время.\n"
        "Среднее время ответа: <b>до 24 часов</b>.",
        reply_markup=back_btn(),
    )


# ── Ответ от админа пользователю ─────────────────────────────────────────────

@dp.message_handler(lambda m: m.chat.id == ADMIN_CHAT_ID and m.reply_to_message)
async def admin_reply(message: types.Message):
    replied = message.reply_to_message
    if not replied or not replied.text:
        return

    for line in replied.text.splitlines():
        if "🆔" in line:
            uid_str = line.replace("🆔", "").strip()
            try:
                target_id = int(uid_str)
                await bot.send_message(
                    target_id,
                    f"💬 <b>Ответ от поддержки:</b>\n\n{message.text}",
                )
                await message.reply("✅ Ответ отправлен пользователю.")
                return
            except Exception as e:
                logger.error(f"Не удалось отправить ответ: {e}")

    await message.reply("⚠️ Не удалось определить пользователя.")


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Запуск SWAGA Support Bot...")
    executor.start_polling(dp, skip_updates=True)
