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

from config import (
    BOT_TOKEN, ADMIN_IDS, PLANS, INBOUND_ID, SUPPORT_URL, SUB_BASE_URL,
    VPN_HOST, VPN_PORT, VPN_TRANSPORT, VPN_PATH, VPN_CAMOUFLAGE_HOST, VPN_XHTTP_MODE,
    REALITY_PUBLIC_KEY, REALITY_SHORT_ID, REALITY_FINGERPRINT, REALITY_SNI, REALITY_SPIDERX,
)
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
    get_subs_for_reminder,
    mark_reminder_sent,
    set_referrer,
    get_referral_stats,
    process_referral_bonus,
    extend_subscription,
    count_users,
    REFERRAL_BONUS_DAYS,
)
from xui_api import XUIAPI
from payment import process_payment
from backup import backup_now
from utils import generate_uuid, generate_sub_id, format_date, build_vless_link
from sub_app import start_sub_server, stop_sub_server
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
    "👋 <b>Добро пожаловать в SWAGA.</b>\n"
    "Ваш персональный инструмент для профессиональной работы в сети. "
    "Мы обеспечиваем стабильность и приватность там, где другие пасуют. "
    "Никакой лишней информации — только высокая скорость и ваша безопасность.\n\n"
    "<b>Наши приоритеты:</b>\n\n"
    "⚡️ <b>High-Speed Traffic:</b> Оптимизированные маршруты для работы с любым контентом. "
    "Забудьте о паузах и долгой загрузке — мы предоставляем максимальную пропускную способность.\n\n"
    "🛡 <b>Защищенный периметр:</b> Мы шифруем ваш трафик в любой точке подключения. "
    "Мобильные сети или внешние узлы — вы всегда находитесь внутри защищенного канала, "
    "недоступного для перехвата и анализа.\n\n"
    "🕶 <b>Приватный режим:</b> Ваше присутствие в сети остается строго конфиденциальным. "
    "Мы гарантируем чистоту цифрового следа и защиту вашей частной жизни "
    "от сторонних систем сбора данных.\n\n"
    "Сервис настроен и готов к работе. Всё, что вам нужно — один клик для старта.\n\n"
    "👇 <b>Выберите подходящий формат доступа:</b>"
)

INSTRUCTION_TEXT = (
    "📖 <b>Инструкция по подключению</b>\n\n"
    "<b>📱 Android / iOS:</b>\n"
    "1. Скачайте <b>V2RayTun</b> (кнопки ниже)\n"
    "2. Нажмите «Личный кабинет» → «Быстрое подключение»\n"
    "3. Конфигурация импортируется автоматически\n\n"
    "<b>💻 Windows / macOS:</b>\n"
    "1. Скачайте <b>v2rayN</b> (Win) или <b>v2rayU</b> (Mac)\n"
    "2. В Личном кабинете скопируйте VLESS-ссылку\n"
    "3. «Импорт из буфера обмена» в приложении\n\n"
    "❓ Проблемы? Нажмите «Техподдержка»"
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
    """Регистрация пользователя и вывод главного меню. Обработка реферальных ссылок."""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or ""

    # Проверяем, новый ли пользователь
    existing_user = await get_user(user_id)
    await create_user(user_id, username)

    # Обработка реферальной ссылки: /start ref_123456
    args = message.get_args()
    if args and args.startswith("ref_") and not existing_user:
        try:
            referrer_id = int(args[4:])
            if await set_referrer(user_id, referrer_id):
                logger.info("Реферал: user=%s привёл user=%s", referrer_id, user_id)
        except (ValueError, TypeError):
            pass  # Невалидный ID

    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@dp.message_handler(Text(equals="Получить доступ"))
async def handle_get_access(message: types.Message) -> None:
    """Показать доступные тарифные планы."""
    user = await get_user(message.from_user.id)
    trial_used = bool(user and user["trial_used"])
    await message.answer(
        "📋 <b>Выберите тарифный план:</b>",
        reply_markup=plans_kb(trial_used),
    )


@dp.message_handler(Text(equals="Инструкция"))
async def handle_instruction(message: types.Message) -> None:
    """Показать инструкцию по подключению."""
    await message.answer(INSTRUCTION_TEXT, reply_markup=instruction_kb())


@dp.message_handler(Text(equals="Личный кабинет"))
async def handle_cabinet(message: types.Message) -> None:
    """Личный кабинет: статус подписки, конфиг, быстрое подключение."""
    user_id = message.from_user.id
    sub = await get_active_sub(user_id)

    if not sub:
        await message.answer(NO_ACTIVE_SUB_TEXT, reply_markup=cabinet_kb())
        return

    vless_link = build_vless_link(
        uuid_str=sub["vless_uuid"],
        host=VPN_HOST,
        port=VPN_PORT,
        transport=VPN_TRANSPORT,
        path=VPN_PATH,
        camouflage_host=VPN_CAMOUFLAGE_HOST,
        xhttp_mode=VPN_XHTTP_MODE,
        reality_pbk=REALITY_PUBLIC_KEY,
        reality_sid=REALITY_SHORT_ID,
        reality_fp=REALITY_FINGERPRINT,
        reality_sni=REALITY_SNI,
        reality_spx=REALITY_SPIDERX,
    )

    plan_name = PLANS.get(sub["plan"], {}).get("name", sub["plan"])
    end_date = format_date(sub["end_date"])

    cab_sub_id = sub.get("xui_sub_id", "")
    connect_base = SUB_BASE_URL.replace("/sub/", "/connect/")
    cab_sub_url = f"{connect_base}{cab_sub_id}" if cab_sub_id else ""

    text = (
        "👤 <b>Личный кабинет</b>\n\n"
        f"📦 Тариф: <b>{plan_name}</b>\n"
        f"📅 Активна до: <b>{end_date}</b>\n\n"
        f"🔑 <b>Ваш конфиг (нажмите чтобы скопировать):</b>\n"
        f"<code>{vless_link}</code>\n\n"
        "📲 Нажмите на кнопку ниже для быстрого подключения."
    )
    if cab_sub_url:
        await message.answer(text, reply_markup=quick_connect_kb(cab_sub_url))
    else:
        await message.answer(text, reply_markup=cabinet_kb())


@dp.message_handler(Text(equals="Поддержка"))
async def handle_support(message: types.Message) -> None:
    """Перенаправление в бот техподдержки."""
    await message.answer(
        "💬 <b>Техподдержка</b>\n\n"
        f"Для получения помощи перейдите в наш бот: {SUPPORT_URL}"
    )


@dp.callback_query_handler(lambda c: c.data == "referrals")
async def cb_referrals(callback: types.CallbackQuery) -> None:
    """Показать реферальную ссылку и статистику (callback из личного кабинета)."""
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    stats = await get_referral_stats(user_id)

    text = (
        "👥 <b>Реферальная программа</b>\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        "📋 <b>Как это работает:</b>\n"
        f"• Поделитесь ссылкой с друзьями\n"
        f"• Когда друг активирует подписку — вы оба получите <b>+{REFERRAL_BONUS_DAYS} дней</b>\n\n"
        "📊 <b>Ваша статистика:</b>\n"
        f"• Приглашено: <b>{stats['total']}</b>\n"
        f"• Активировали подписку: <b>{stats['activated']}</b>\n"
        f"• Заработано дней: <b>{stats['bonus_days']}</b>"
    )
    await callback.message.answer(text)
    await callback.answer()


@dp.message_handler(Text(equals="Правила"))
async def handle_rules(message: types.Message) -> None:
    """Показать правила использования сервиса."""
    text = (
        "📜 <b>Правила использования SWAGA VPN</b>\n\n"
        "Используя данный сервис, вы соглашаетесь со следующими условиями:\n\n"
        "<b>1. Назначение сервиса</b>\n"
        "Сервис предназначен исключительно для защиты личной "
        "конфиденциальности и безопасного доступа к информации в интернете.\n\n"
        "<b>2. Запрещено использовать VPN для:</b>\n"
        "• Любой противоправной деятельности\n"
        "• Распространения вредоносного ПО\n"
        "• Мошенничества и фишинга\n"
        "• Нарушения авторских прав\n"
        "• Спама и массовых рассылок\n"
        "• DDoS-атак и взломов\n"
        "• Любых действий, нарушающих законодательство РФ\n\n"
        "<b>3. Ограничение ответственности</b>\n"
        "Администрация сервиса не несёт ответственности за действия "
        "пользователей. Вся ответственность за использование VPN-соединения "
        "лежит на пользователе.\n\n"
        "<b>4. Блокировка</b>\n"
        "Администрация оставляет за собой право заблокировать доступ "
        "без возврата средств при нарушении данных правил.\n\n"
        "<b>5. Возврат средств</b>\n"
        "Возврат средств возможен в течение 24 часов после оплаты, "
        "если услуга не была использована.\n\n"
        "✅ Продолжая использование сервиса, вы подтверждаете согласие с данными правилами."
    )
    await message.answer(text)


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
    sub_id = generate_sub_id()
    now = datetime.utcnow()
    # Уникальный email с timestamp чтобы избежать Duplicate email
    email = f"tg_{user_id}_{int(now.timestamp())}"
    end = now + timedelta(days=plan["days"])

    try:
        success = xui.add_client(INBOUND_ID, new_uuid, email, sub_id=sub_id)
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
        xui_sub_id=sub_id,
    )

    # ── Реферальный бонус ─────────────────────────────────────────────────
    referral_bonus_text = ""
    referrer_id = await process_referral_bonus(user_id)
    if referrer_id:
        # Продлеваем подписку рефереру
        referrer_extended = await extend_subscription(referrer_id, REFERRAL_BONUS_DAYS)
        if referrer_extended:
            try:
                await bot.send_message(
                    referrer_id,
                    f"🎉 <b>Реферальный бонус!</b>\n\n"
                    f"Ваш друг активировал подписку.\n"
                    f"Вам добавлено <b>+{REFERRAL_BONUS_DAYS} дней</b> к подписке!",
                    parse_mode=types.ParseMode.HTML,
                )
            except Exception as e:
                logger.warning("Не удалось уведомить реферера %s: %s", referrer_id, e)
        # Продлеваем подписку приглашённому
        await extend_subscription(user_id, REFERRAL_BONUS_DAYS)
        referral_bonus_text = f"\n🎁 <b>Реферальный бонус:</b> +{REFERRAL_BONUS_DAYS} дней!"
        end = end + timedelta(days=REFERRAL_BONUS_DAYS)  # Обновляем дату для отображения

    # ── Формирование ответа ───────────────────────────────────────────────
    vless_link = build_vless_link(
        uuid_str=new_uuid,
        host=VPN_HOST,
        port=VPN_PORT,
        transport=VPN_TRANSPORT,
        path=VPN_PATH,
        camouflage_host=VPN_CAMOUFLAGE_HOST,
        xhttp_mode=VPN_XHTTP_MODE,
        reality_pbk=REALITY_PUBLIC_KEY,
        reality_sid=REALITY_SHORT_ID,
        reality_fp=REALITY_FINGERPRINT,
        reality_sni=REALITY_SNI,
        reality_spx=REALITY_SPIDERX,
    )

    connect_base = SUB_BASE_URL.replace("/sub/", "/connect/")
    sub_url = f"{connect_base}{sub_id}"
    text = (
        "✅ <b>Подписка активирована!</b>\n\n"
        f"📦 Тариф: <b>{plan['name']}</b>\n"
        f"📅 Действует до: <b>{format_date(end)}</b>"
        f"{referral_bonus_text}\n\n"
        f"🔑 <b>Ваш конфиг (нажмите чтобы скопировать):</b>\n"
        f"<code>{vless_link}</code>\n\n"
        "📲 Нажмите на кнопку ниже для быстрого подключения."
    )
    await callback.message.answer(text, reply_markup=quick_connect_kb(sub_url))
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


async def _scheduler_reminders() -> None:
    """
    Проверка каждый час — отправка напоминаний:
    - За 3 дня (72 часа)
    - За 1 день (24 часа)
    - За 3 часа
    """
    # Небольшая задержка при старте, чтобы бот успел инициализироваться
    await asyncio.sleep(60)

    while True:
        try:
            logger.info("Scheduler: проверка напоминаний")

            # Напоминания за 3 дня (72 часа)
            subs_3d = await get_subs_for_reminder(hours=72, reminder_code="3d")
            for sub in subs_3d:
                try:
                    end_str = format_date(sub["end_date"])
                    await bot.send_message(
                        sub["user_id"],
                        f"⏳ <b>Напоминание!</b>\n\n"
                        f"Ваша подписка истекает через <b>3 дня</b> ({end_str}).\n"
                        f"Продлите её заранее, чтобы не потерять доступ к VPN!",
                        parse_mode=types.ParseMode.HTML,
                    )
                    await mark_reminder_sent(sub["sub_id"], "3d")
                    logger.info("Напоминание 3d отправлено user=%s", sub["user_id"])
                except Exception as e:
                    logger.warning("Не удалось отправить напоминание 3d user=%s: %s", sub["user_id"], e)

            # Напоминания за 1 день (24 часа)
            subs_1d = await get_subs_for_reminder(hours=24, reminder_code="1d")
            for sub in subs_1d:
                try:
                    end_str = format_date(sub["end_date"])
                    await bot.send_message(
                        sub["user_id"],
                        f"⚠️ <b>Подписка истекает завтра!</b>\n\n"
                        f"Дата окончания: <b>{end_str}</b>\n"
                        f"Успейте продлить, чтобы VPN продолжил работать!",
                        parse_mode=types.ParseMode.HTML,
                    )
                    await mark_reminder_sent(sub["sub_id"], "1d")
                    logger.info("Напоминание 1d отправлено user=%s", sub["user_id"])
                except Exception as e:
                    logger.warning("Не удалось отправить напоминание 1d user=%s: %s", sub["user_id"], e)

            # Напоминания за 3 часа
            subs_3h = await get_subs_for_reminder(hours=3, reminder_code="3h")
            for sub in subs_3h:
                try:
                    await bot.send_message(
                        sub["user_id"],
                        f"🔴 <b>Срочно! Подписка истекает через 3 часа!</b>\n\n"
                        f"После истечения VPN перестанет работать.\n"
                        f"Нажмите «Получить доступ», чтобы продлить прямо сейчас!",
                        parse_mode=types.ParseMode.HTML,
                    )
                    await mark_reminder_sent(sub["sub_id"], "3h")
                    logger.info("Напоминание 3h отправлено user=%s", sub["user_id"])
                except Exception as e:
                    logger.warning("Не удалось отправить напоминание 3h user=%s: %s", sub["user_id"], e)

        except Exception as e:
            logger.error("Ошибка в scheduler_reminders: %s", e)

        # Ждём 1 час до следующей проверки
        await asyncio.sleep(3600)


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

    # Удаление старых команд и установка новых (меню слева)
    try:
        # Удаляем для всех scope
        for scope in [
            types.BotCommandScopeDefault(),
            types.BotCommandScopeAllPrivateChats(),
            types.BotCommandScopeAllGroupChats(),
        ]:
            try:
                await bot.delete_my_commands(scope=scope)
            except Exception:
                pass
        # Устанавливаем новые команды
        await bot.set_my_commands([
            types.BotCommand("start", "Главное меню"),
        ])
        logger.info("Команды бота установлены")
    except Exception as e:
        logger.error("Ошибка установки команд: %s", e)

    # Запуск сервера подписок
    await start_sub_server()

    # Запуск фоновых задач
    asyncio.create_task(_scheduler_expiration_check())
    asyncio.create_task(_scheduler_reminders())
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
    await stop_sub_server()
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
