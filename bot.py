"""
Основной модуль Telegram VPN-бота SWAGA.
aiogram v2 + asyncio scheduler для проверок подписок и бэкапов.
"""

import asyncio
import logging
import traceback
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher.filters import Text

from config import BOT_TOKEN, ADMIN_IDS, PLANS, INBOUND_ID, VPN_HOST, VPN_PORT, VPN_PATH
from database import (
    init_db,
    get_user,
    create_user,
    mark_trial_used,
    reset_trial,
    get_active_sub,
    create_subscription,
    deactivate_subscription,
    deactivate_user_subs,
    list_expiring,
    list_expired,
)
from xui_api import XUIAPI
from payment import process_payment
from backup import backup_now
from utils import generate_uuid, format_date, build_vless_link
from keyboards import (
    main_menu_kb,
    plans_kb,
    instruction_kb,
    quick_connect_kb,
    cabinet_kb,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Bot & Dispatcher ──────────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)
xui = XUIAPI()


# ── Уведомления админам ──────────────────────────────────────────────────────

async def notify_admins(text: str) -> None:
    """Отправить сообщение всем администраторам."""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=types.ParseMode.HTML)
        except Exception as e:
            logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def notify_error(context: str, error: Exception) -> None:
    """Отправить админам уведомление об ошибке."""
    tb = traceback.format_exception(type(error), error, error.__traceback__)
    short_tb = "".join(tb[-3:])[:500]
    text = (
        f"<b>SWAGA VPN Bot — ошибка</b>\n\n"
        f"<b>Контекст:</b> {context}\n"
        f"<b>Ошибка:</b> <code>{type(error).__name__}: {error}</code>\n\n"
        f"<pre>{short_tb}</pre>"
    )
    await notify_admins(text)


# ── Текстовые константы ──────────────────────────────────────────────────────
WELCOME_TEXT = (
    "👋 <b>Добро пожаловать в SWAGA VPN!</b>\n\n"
    "Быстрый и безопасный VPN на базе VLESS.\n"
    "Выберите действие из меню ниже."
)

INSTRUCTION_TEXT = (
    "📖 <b>Инструкция по подключению</b>\n\n"
    "<b>📱 Android / iOS:</b>\n"
    "1. Скачайте приложение <b>V2RayTun</b> из магазина приложений.\n"
    "2. Нажмите кнопку «Быстрое подключение» в Личном кабинете.\n"
    "3. Конфигурация импортируется автоматически.\n\n"
    "<b>💻 Windows / macOS / Linux:</b>\n"
    "1. Скачайте <b>v2rayN</b> (Windows) или <b>v2rayU</b> (macOS).\n"
    "2. Скопируйте VLESS-ссылку из Личного кабинета.\n"
    "3. Добавьте сервер через «Импорт из буфера обмена».\n\n"
    "При проблемах — обратитесь в техподдержку."
)

NO_ACTIVE_SUB_TEXT = (
    "😔 У вас нет активной подписки.\n"
    "Нажмите «Получить доступ», чтобы выбрать тариф."
)


# ══════════════════════════════════════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message) -> None:
    """Регистрация пользователя и вывод главного меню."""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or ""
    await create_user(user_id, username)
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@dp.message_handler(Text(equals="🔐 Получить доступ"))
async def handle_get_access(message: types.Message) -> None:
    """Показать доступные тарифные планы."""
    user = await get_user(message.from_user.id)
    trial_used = bool(user and user["trial_used"])
    await message.answer(
        "📋 <b>Выберите тарифный план:</b>",
        reply_markup=plans_kb(trial_used),
    )


@dp.message_handler(Text(equals="📖 Инструкция"))
async def handle_instruction(message: types.Message) -> None:
    """Показать инструкцию по подключению."""
    await message.answer(INSTRUCTION_TEXT, reply_markup=instruction_kb())


@dp.message_handler(Text(equals="👤 Личный кабинет"))
async def handle_cabinet(message: types.Message) -> None:
    """Личный кабинет: статус подписки, конфиг, быстрое подключение."""
    user_id = message.from_user.id
    sub = await get_active_sub(user_id)

    if not sub:
        await message.answer(NO_ACTIVE_SUB_TEXT, reply_markup=cabinet_kb())
        return

    vless_link = build_vless_link(
        uuid_str=sub["vless_uuid"],
        ip=VPN_HOST,
        port=VPN_PORT,
        host=VPN_HOST,
        path=VPN_PATH,
    )

    plan_name = PLANS.get(sub["plan"], {}).get("name", sub["plan"])
    end_date = format_date(sub["end_date"])

    text = (
        "👤 <b>Личный кабинет</b>\n\n"
        f"📦 Тариф: <b>{plan_name}</b>\n"
        f"📅 Активна до: <b>{end_date}</b>\n\n"
        f"🔑 <b>Ваш конфиг:</b>\n"
        f"<code>{vless_link}</code>\n\n"
        "Скопируйте ссылку или нажмите кнопку ниже для быстрого подключения."
    )
    await message.answer(text, reply_markup=quick_connect_kb(vless_link))


@dp.message_handler(commands=["reset_me"])
async def cmd_reset_me(message: types.Message) -> None:
    """
    Сброс пробного периода и удаление текущей подписки (только для админов).
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    # Деактивировать текущую подписку и удалить клиента из 3X-UI
    sub = await get_active_sub(user_id)
    if sub and sub["vless_uuid"]:
        try:
            xui.delete_client(INBOUND_ID, sub["vless_uuid"])
        except Exception as e:
            logger.warning("Ошибка удаления клиента при reset: %s", e)

    await deactivate_user_subs(user_id)
    await reset_trial(user_id)

    await message.answer(
        "✅ Сброс выполнен:\n"
        "— Пробный период восстановлен\n"
        "— Текущая подписка деактивирована\n"
        "— VPN-конфиг удалён из панели"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

@dp.callback_query_handler(lambda c: c.data == "get_access")
async def cb_get_access(callback: types.CallbackQuery) -> None:
    """Inline-кнопка 'Получить доступ' (из инструкции/кабинета)."""
    user = await get_user(callback.from_user.id)
    trial_used = bool(user and user["trial_used"])
    await callback.message.answer(
        "📋 <b>Выберите тарифный план:</b>",
        reply_markup=plans_kb(trial_used),
    )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("plan_"))
async def cb_plan_selected(callback: types.CallbackQuery) -> None:
    """Обработка выбора тарифного плана."""
    user_id = callback.from_user.id
    plan_key = callback.data.replace("plan_", "")  # trial, 1m, 3m, 1y

    if plan_key not in PLANS:
        await callback.answer("❌ Неизвестный тарифный план.", show_alert=True)
        return

    plan = PLANS[plan_key]
    user = await get_user(user_id)

    if not user:
        await create_user(user_id, callback.from_user.username or "")
        user = await get_user(user_id)

    # ── Пробный период ────────────────────────────────────────────────────
    if plan_key == "trial":
        if user["trial_used"]:
            await callback.answer(
                "⚠️ Пробный период уже использован.", show_alert=True,
            )
            return
        await mark_trial_used(user_id)

    # ── Платный тариф ─────────────────────────────────────────────────────
    if plan["price"] > 0:
        payment_ok = await process_payment(user_id, plan["price"], plan_key)
        if not payment_ok:
            await callback.message.answer(
                "❌ Ошибка при обработке платежа. Попробуйте позже."
            )
            await callback.answer()
            return

    # ── Создание VPN-клиента ──────────────────────────────────────────────
    new_uuid = generate_uuid()
    email = f"tg_{user_id}_{plan_key}"
    now = datetime.utcnow()
    end = now + timedelta(days=plan["days"])

    try:
        success = xui.add_client(INBOUND_ID, new_uuid, email)
        if not success:
            raise RuntimeError("3X-UI add_client вернул False")
    except Exception as e:
        logger.error("Ошибка создания VPN-клиента: %s", e)
        await notify_error("Создание VPN-клиента", e)
        await callback.message.answer(
            "❌ Не удалось создать VPN-конфиг. Обратитесь в поддержку."
        )
        await callback.answer()
        return

    # ── Сохранение подписки в БД ──────────────────────────────────────────
    # Деактивируем старые подписки перед созданием новой
    await deactivate_user_subs(user_id)
    await create_subscription(
        user_id=user_id,
        plan=plan_key,
        start_date=now.isoformat(),
        end_date=end.isoformat(),
        vless_uuid=new_uuid,
    )

    # ── Формирование ответа ───────────────────────────────────────────────
    vless_link = build_vless_link(
        uuid_str=new_uuid,
        ip=VPN_HOST,
        port=VPN_PORT,
        host=VPN_HOST,
        path=VPN_PATH,
    )

    text = (
        "✅ <b>Подписка активирована!</b>\n\n"
        f"📦 Тариф: <b>{plan['name']}</b>\n"
        f"📅 Действует до: <b>{format_date(end)}</b>\n\n"
        f"🔑 <b>Ваш конфиг:</b>\n"
        f"<code>{vless_link}</code>\n\n"
        "Скопируйте ссылку или нажмите кнопку ниже для быстрого подключения."
    )
    await callback.message.answer(text, reply_markup=quick_connect_kb(vless_link))
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEDULER (asyncio tasks)
# ══════════════════════════════════════════════════════════════════════════════

async def _scheduler_expiration_check() -> None:
    """
    Ежедневная проверка подписок (00:00 UTC):
    — За 3 дня до окончания: напоминание.
    — Истекшие: удаление клиента, деактивация, уведомление.
    """
    while True:
        now = datetime.utcnow()
        # Ждём до 00:00 UTC
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        wait_seconds = (tomorrow - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        logger.info("Scheduler: проверка подписок")

        # Напоминания (за 3 дня)
        try:
            expiring = await list_expiring(days=3)
            for sub in expiring:
                try:
                    end_str = format_date(sub["end_date"])
                    await bot.send_message(
                        sub["user_id"],
                        f"⏳ Ваша подписка истекает <b>{end_str}</b>.\n"
                        "Продлите её, чтобы не потерять доступ!",
                        parse_mode=types.ParseMode.HTML,
                    )
                except Exception as e:
                    logger.warning("Не удалось отправить напоминание user=%s: %s", sub["user_id"], e)
        except Exception as e:
            logger.error("Ошибка при выборке expiring subs: %s", e)
            await notify_error("Scheduler: проверка expiring", e)

        # Истекшие подписки
        try:
            expired = await list_expired()
            for sub in expired:
                # Удалить клиента из 3X-UI
                if sub["vless_uuid"]:
                    try:
                        xui.delete_client(INBOUND_ID, sub["vless_uuid"])
                    except Exception as e:
                        logger.warning("Ошибка удаления клиента %s: %s", sub["vless_uuid"], e)

                # Деактивировать подписку
                await deactivate_subscription(sub["sub_id"])

                # Уведомить пользователя
                try:
                    await bot.send_message(
                        sub["user_id"],
                        "😔 Ваша подписка истекла.\n"
                        "Нажмите «Получить доступ», чтобы выбрать новый тариф.",
                        parse_mode=types.ParseMode.HTML,
                    )
                except Exception as e:
                    logger.warning("Не удалось уведомить user=%s: %s", sub["user_id"], e)

            if expired:
                await notify_admins(
                    f"📊 <b>Scheduler:</b> обработано {len(expired)} истёкших подписок."
                )
        except Exception as e:
            logger.error("Ошибка при обработке expired subs: %s", e)
            await notify_error("Scheduler: обработка expired", e)


async def _scheduler_backup() -> None:
    """Ежедневный бэкап в 03:00 UTC."""
    while True:
        now = datetime.utcnow()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        logger.info("Scheduler: создание бэкапа")
        result = backup_now()
        if result:
            await notify_admins(f"💾 Бэкап создан: <code>{result}</code>")
        else:
            await notify_admins("⚠️ Ошибка при создании бэкапа! Проверьте логи.")


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP / SHUTDOWN
# ══════════════════════════════════════════════════════════════════════════════

async def on_startup(_dp: Dispatcher) -> None:
    """Инициализация при запуске бота."""
    await init_db()
    logger.info("База данных инициализирована")

    # Запуск фоновых задач
    asyncio.create_task(_scheduler_expiration_check())
    asyncio.create_task(_scheduler_backup())
    logger.info("Фоновые задачи запущены")

    # Уведомление админам
    now_str = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
    await notify_admins(
        f"✅ <b>SWAGA VPN Bot запущен</b>\n"
        f"🕐 {now_str}\n"
        f"📊 Scheduler и бэкапы активны."
    )


async def on_shutdown(_dp: Dispatcher) -> None:
    """Действия при остановке бота."""
    logger.info("Бот остановлен")
    await notify_admins("🛑 <b>SWAGA VPN Bot остановлен.</b>")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    executor.start_polling(
        dp,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
    )
