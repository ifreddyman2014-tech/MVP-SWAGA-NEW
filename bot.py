"""
Основной модуль Telegram VPN-бота SWAGA.
aiogram v2 + asyncio scheduler для проверок подписок и бэкапов.
"""

import asyncio
import logging
import traceback
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.types import InputFile
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
    extend_subscription_to_date,
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
    servers_kb,
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
LOGO_PATH = "logo.png"

WELCOME_TEXT = (
    "👋 <b>Добро пожаловать в SWAGA</b>\n\n"
    "Скорость. Приватность. Контроль — в одном клике.\n\n"
    "⚡ <b>Быстро</b> — оптимизированные каналы без лагов\n"
    "🛡 <b>Безопасно</b> — полный шифрованный туннель\n"
    "🕶 <b>Приватно</b> — без логов и цифрового следа\n\n"
    "🎁 <b>7 дней пробного доступа</b> — попробуйте все возможности сервиса бесплатно.\n\n"
    "SWAGA уже готов к работе.\n"
    "Просто подключайтесь и начинайте.\n\n"
    "👇 <b>Выберите формат доступа</b>"
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

    await message.answer_photo(
        InputFile(LOGO_PATH),
        caption=WELCOME_TEXT,
        reply_markup=main_menu_kb(),
    )


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
        "<b>2. Политика No-Logs</b>\n"
        "🔒 Мы <b>не храним</b> никаких данных о вашей активности:\n"
        "• Не записываем посещённые сайты\n"
        "• Не сохраняем IP-адреса подключений\n"
        "• Не ведём журналы трафика\n"
        "• Технически не имеем возможности отследить ваши действия\n\n"
        "<b>3. Запрещено использовать VPN для:</b>\n"
        "• Любой противоправной деятельности\n"
        "• Распространения вредоносного ПО\n"
        "• Мошенничества и фишинга\n"
        "• Нарушения авторских прав\n"
        "• Спама и массовых рассылок\n"
        "• DDoS-атак и взломов\n\n"
        "<b>4. Ограничение ответственности</b>\n"
        "Администрация сервиса не несёт ответственности за действия "
        "пользователей. Вся ответственность за использование VPN-соединения "
        "лежит на пользователе.\n\n"
        "<b>5. Блокировка</b>\n"
        "Администрация оставляет за собой право заблокировать доступ "
        "без возврата средств при нарушении данных правил.\n\n"
        "<b>6. Возврат средств</b>\n"
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


@dp.message_handler(commands=["capacity"])
async def cmd_capacity(message: types.Message) -> None:
    """Показать вместимость сервера (только для админов)."""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    # Проверяем аргумент --speedtest
    args = message.get_args()
    run_speedtest = "speedtest" in args.lower() if args else False

    from capacity import get_cpu_cores, get_ram_gb, get_bandwidth_mbps, calculate_capacity

    cpu = get_cpu_cores()
    ram = get_ram_gb()

    if run_speedtest:
        await message.answer("⏳ Запуск теста скорости (30-60 сек)...")

    download, upload, is_real = get_bandwidth_mbps(run_speedtest)
    cap = calculate_capacity(cpu, ram, download, upload)

    test_label = "реальный тест ✅" if is_real else "оценка"

    text = (
        "📊 <b>Вместимость сервера SWAGA VPN</b>\n\n"
        f"<b>Характеристики:</b>\n"
        f"• CPU: {cpu} ядер\n"
        f"• RAM: {ram} GB\n"
        f"• Download: {download} Mbps\n"
        f"• Upload: {upload} Mbps\n"
        f"• <i>({test_label})</i>\n\n"
        f"<b>Лимиты (одновременно):</b>\n"
        f"• По CPU: {cap['limits']['CPU']}\n"
        f"• По RAM: {cap['limits']['RAM']}\n"
        f"• По Upload: {cap['limits']['Bandwidth']}\n\n"
        f"<b>Рекомендации:</b>\n"
        f"👥 Макс. одновременно: <b>{cap['max_concurrent']}</b>\n"
        f"👤 Макс. всего польз.: <b>{cap['max_total']}</b>\n\n"
        f"⚠️ Ограничивающий фактор: <b>{cap['limiting_factor']}</b>\n\n"
        f"<i>💡 /capacity speedtest — реальный тест</i>"
    )
    await message.answer(text)


@dp.message_handler(commands=["servers"])
async def cmd_servers(message: types.Message) -> None:
    """Показать статус серверов (только для админов)."""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    from servers import server_manager

    # Загружаем конфигурацию если ещё не загружена
    if not server_manager.servers:
        server_manager.load_config()

    servers = server_manager.get_all_servers()
    if not servers:
        await message.answer(
            "📡 <b>Серверы не настроены</b>\n\n"
            "Добавьте серверы в <code>servers.json</code>"
        )
        return

    # Проверяем здоровье серверов
    await message.answer("🔄 Проверка серверов...")
    await server_manager.check_all_servers()

    stats = server_manager.get_stats()

    text = "📡 <b>Статус серверов SWAGA VPN</b>\n\n"

    for srv in servers:
        status = "🟢" if srv.is_healthy else "🔴"
        enabled = "✓" if srv.enabled else "✗"
        text += (
            f"{status} <b>{srv.name}</b> [{enabled}]\n"
            f"   📍 {srv.location} | {srv.host}:{srv.vpn_port}\n"
            f"   👥 {srv.current_users}/{srv.max_users} пользователей\n"
        )
        if srv.last_error:
            text += f"   ⚠️ {srv.last_error[:50]}\n"
        text += "\n"

    text += (
        f"<b>Общая статистика:</b>\n"
        f"• Серверов: {stats['healthy_servers']}/{stats['total_servers']} онлайн\n"
        f"• Пользователей: {stats['total_users']}/{stats['total_capacity']}\n"
        f"• Загрузка: {stats['load_percent']}%"
    )

    await message.answer(text)


@dp.message_handler(commands=["server_add"])
async def cmd_server_add(message: types.Message) -> None:
    """
    Добавить сервер (только для админов).
    Формат: /server_add id name host xui_host:port username password
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args()
    if not args:
        await message.answer(
            "📝 <b>Добавление сервера</b>\n\n"
            "Формат:\n"
            "<code>/server_add id|name|host|xui_host:port|user|pass|location</code>\n\n"
            "Пример:\n"
            "<code>/server_add nl1|Нидерланды|nl.vpn.com|127.0.0.1:2055|admin|pass123|NL</code>"
        )
        return

    try:
        parts = args.split("|")
        if len(parts) < 6:
            raise ValueError("Недостаточно параметров")

        srv_id = parts[0].strip()
        name = parts[1].strip()
        host = parts[2].strip()
        xui_parts = parts[3].strip().split(":")
        xui_host = xui_parts[0]
        xui_port = int(xui_parts[1]) if len(xui_parts) > 1 else 2055
        username = parts[4].strip()
        password = parts[5].strip()
        location = parts[6].strip() if len(parts) > 6 else ""

        from servers import server_manager, VPNServer

        server = VPNServer(
            id=srv_id,
            name=name,
            host=host,
            xui_host=xui_host,
            xui_port=xui_port,
            xui_web_path="",
            xui_username=username,
            xui_password=password,
            location=location,
        )

        if server_manager.add_server(server):
            await message.answer(f"✅ Сервер <b>{name}</b> добавлен!")
        else:
            await message.answer(f"❌ Сервер с ID <b>{srv_id}</b> уже существует")

    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message_handler(commands=["server_toggle"])
async def cmd_server_toggle(message: types.Message) -> None:
    """Включить/выключить сервер. Формат: /server_toggle server_id"""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args()
    if not args:
        await message.answer("Формат: <code>/server_toggle server_id</code>")
        return

    from servers import server_manager

    server = server_manager.get_server(args.strip())
    if not server:
        await message.answer(f"❌ Сервер <b>{args}</b> не найден")
        return

    server.enabled = not server.enabled
    server_manager.save_config()

    status = "включён ✅" if server.enabled else "выключен ❌"
    await message.answer(f"Сервер <b>{server.name}</b> {status}")


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
    """Обработка выбора тарифного плана — показать выбор сервера."""
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
    if plan_key == "trial" and user["trial_used"]:
        await callback.answer(
            "⚠️ Пробный период уже использован.", show_alert=True,
        )
        return

    # ── Показать выбор сервера ────────────────────────────────────────────
    from servers import server_manager

    if not server_manager.servers:
        server_manager.load_config()

    servers = server_manager.get_healthy_servers()

    if not servers:
        # Если нет серверов — используем текущий сервер (fallback)
        await callback.answer()
        await _create_subscription_on_server(callback, plan_key, None)
        return

    if len(servers) == 1:
        # Если только один сервер — сразу создаём подписку
        await callback.answer()
        await _create_subscription_on_server(callback, plan_key, servers[0].id)
        return

    # Показываем выбор сервера
    await callback.message.answer(
        f"🌍 <b>Выберите сервер</b>\n\n"
        f"Тариф: <b>{plan['name']}</b>\n\n"
        "Выберите локацию для подключения:",
        reply_markup=servers_kb(servers, plan_key),
    )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("server_"))
async def cb_server_selected(callback: types.CallbackQuery) -> None:
    """Обработка выбора сервера — создание подписки."""
    # Формат: server_{server_id}_{plan_key} или server_auto_{plan_key}
    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer("❌ Ошибка выбора сервера", show_alert=True)
        return

    server_id = parts[1]  # server_id или "auto"
    plan_key = "_".join(parts[2:])  # plan_key (может содержать _)

    if server_id == "auto":
        server_id = None  # Автовыбор

    await callback.answer()
    await _create_subscription_on_server(callback, plan_key, server_id)


async def _create_subscription_on_server(
    callback: types.CallbackQuery,
    plan_key: str,
    server_id: str | None,
) -> None:
    """Создать подписку на выбранном сервере."""
    user_id = callback.from_user.id
    plan = PLANS.get(plan_key)

    if not plan:
        await callback.message.answer("❌ Неизвестный тарифный план.")
        return

    user = await get_user(user_id)

    # ── Пробный период ────────────────────────────────────────────────────
    if plan_key == "trial":
        if user and user["trial_used"]:
            await callback.message.answer("⚠️ Пробный период уже использован.")
            return
        await mark_trial_used(user_id)

    # ── Платный тариф ─────────────────────────────────────────────────────
    if plan["price"] > 0:
        payment_ok = await process_payment(user_id, plan["price"], plan_key)
        if not payment_ok:
            await callback.message.answer(
                "❌ Ошибка при обработке платежа. Попробуйте позже."
            )
            return

    # ── Проверяем, есть ли активная подписка (для продления) ─────────────
    existing_sub = await get_active_sub(user_id)
    now = datetime.utcnow()

    # ── Если есть активная подписка — продлеваем её ────────────────────────
    if existing_sub and existing_sub.get("vless_uuid"):
        # Продление: добавляем дни к текущей дате окончания
        current_end = datetime.fromisoformat(existing_sub["end_date"])
        # Если подписка ещё не истекла — добавляем к ней, иначе от сейчас
        base_date = max(current_end, now)
        new_end = base_date + timedelta(days=plan["days"])

        # Обновляем дату окончания в БД
        await extend_subscription_to_date(user_id, new_end)

        # Используем существующий конфиг
        new_uuid = existing_sub["vless_uuid"]
        sub_id = existing_sub.get("xui_sub_id", "")
        actual_server_id = existing_sub.get("server_id", "default")

        # Определяем хост для ссылки
        from servers import server_manager
        if not server_manager.servers:
            server_manager.load_config()

        if actual_server_id and actual_server_id != "default":
            server = server_manager.get_server(actual_server_id)
            vpn_host = server.host if server else VPN_HOST
            vpn_port = server.vpn_port if server else VPN_PORT
        else:
            vpn_host = VPN_HOST
            vpn_port = VPN_PORT

        end = new_end
        is_extension = True

    else:
        # ── Новая подписка — создаём VPN-клиент ────────────────────────────
        is_extension = False

        # Выбор сервера
        from servers import server_manager

        if not server_manager.servers:
            server_manager.load_config()

        if server_id:
            server = server_manager.get_server(server_id)
        else:
            server = server_manager.get_best_server()

        # Если нет серверов в мультисервере — используем текущий из .env
        use_default = server is None

        # Создание VPN-клиента
        new_uuid = generate_uuid()
        sub_id = generate_sub_id()
        email = f"tg_{user_id}_{int(now.timestamp())}"
        end = now + timedelta(days=plan["days"])

        try:
            if use_default:
                # Используем дефолтный xui из .env
                success = xui.add_client(INBOUND_ID, new_uuid, email, sub_id=sub_id)
                vpn_host = VPN_HOST
                vpn_port = VPN_PORT
                actual_server_id = "default"
            else:
                # Используем выбранный сервер
                from xui_api import XUIAPI
                server_xui = XUIAPI()
                # Определяем протокол: HTTPS для внешних серверов или SSL-портов
                if server.xui_host not in ("127.0.0.1", "localhost"):
                    protocol = "https"
                elif server.xui_port in (443, 2053, 2096):
                    protocol = "https"
                else:
                    protocol = "http"
                server_xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
                login_resp = server_xui.session.post(
                    f"{server_xui.base_url}/login",
                    json={"username": server.xui_username, "password": server.xui_password},
                    verify=False,
                    timeout=10,
                )
                login_data = login_resp.json()
                if not login_data.get("success"):
                    raise ConnectionError(f"Не удалось авторизоваться в панели сервера {server.name}")
                server_xui._logged_in = True  # Помечаем как авторизованный
                success = server_xui.add_client(server.inbound_id, new_uuid, email, sub_id=sub_id)
                vpn_host = server.host
                vpn_port = server.vpn_port
                actual_server_id = server.id
                server.current_users += 1

            if not success:
                raise RuntimeError("3X-UI add_client вернул False")
        except Exception as e:
            logger.error("Ошибка создания VPN-клиента: %s", e)
            await notify_error("Создание VPN-клиента", e)
            await callback.message.answer(
                "❌ Не удалось создать VPN-конфиг. Обратитесь в поддержку."
            )
            return

        # Сохранение новой подписки в БД
        await deactivate_user_subs(user_id)
        await create_subscription(
            user_id=user_id,
            plan=plan_key,
            start_date=now.isoformat(),
            end_date=end.isoformat(),
            vless_uuid=new_uuid,
            xui_sub_id=sub_id,
            server_id=actual_server_id,
        )

    # ── Реферальный бонус ─────────────────────────────────────────────────
    referral_bonus_text = ""
    referrer_id = await process_referral_bonus(user_id)
    if referrer_id:
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
        await extend_subscription(user_id, REFERRAL_BONUS_DAYS)
        referral_bonus_text = f"\n🎁 <b>Реферальный бонус:</b> +{REFERRAL_BONUS_DAYS} дней!"
        end = end + timedelta(days=REFERRAL_BONUS_DAYS)

    # ── Формирование ответа ───────────────────────────────────────────────
    # Получаем настройки сервера для VLESS ссылки
    srv = None
    if actual_server_id and actual_server_id != "default":
        srv = server_manager.get_server(actual_server_id)

    # Используем настройки сервера или глобальные из .env
    if srv and srv.reality_pbk:
        vless_link = build_vless_link(
            uuid_str=new_uuid,
            host=vpn_host,
            port=vpn_port,
            transport=srv.transport or VPN_TRANSPORT,
            path=srv.transport_path or VPN_PATH,
            camouflage_host=srv.transport_host or VPN_CAMOUFLAGE_HOST,
            xhttp_mode=srv.xhttp_mode or VPN_XHTTP_MODE,
            reality_pbk=srv.reality_pbk,
            reality_sid=srv.reality_sid,
            reality_fp=srv.reality_fp or REALITY_FINGERPRINT,
            reality_sni=srv.reality_sni,
            reality_spx=REALITY_SPIDERX,
        )
    else:
        vless_link = build_vless_link(
            uuid_str=new_uuid,
            host=vpn_host,
            port=vpn_port,
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

    # Добавляем информацию о сервере
    server_info = ""
    if srv:
        server_info = f"\n🌍 Сервер: <b>{srv.name}</b>"

    connect_base = SUB_BASE_URL.replace("/sub/", "/connect/")
    sub_url = f"{connect_base}{sub_id}"

    # Разный текст для продления и новой подписки
    if is_extension:
        action_text = "✅ <b>Подписка продлена!</b>"
    else:
        action_text = "✅ <b>Подписка активирована!</b>"

    text = (
        f"{action_text}\n\n"
        f"📦 Тариф: <b>{plan['name']}</b>\n"
        f"📅 Действует до: <b>{format_date(end)}</b>"
        f"{server_info}"
        f"{referral_bonus_text}\n\n"
        f"🔑 <b>Ваш конфиг (нажмите чтобы скопировать):</b>\n"
        f"<code>{vless_link}</code>\n\n"
        "📲 Нажмите на кнопку ниже для быстрого подключения."
    )
    await callback.message.answer(text, reply_markup=quick_connect_kb(sub_url))

    # ── Уведомление админам о подписке ────────────────────────────────────
    username = callback.from_user.username
    user_link = f"@{username}" if username else f"ID: {user_id}"
    admin_action = "🔄 <b>Продление подписки!</b>" if is_extension else "💰 <b>Новая подписка!</b>"
    await notify_admins(
        f"{admin_action}\n\n"
        f"👤 Пользователь: {user_link}\n"
        f"📦 Тариф: <b>{plan['name']}</b>\n"
        f"💵 Сумма: <b>{plan['price']} ₽</b>\n"
        f"📅 До: <b>{format_date(end)}</b>\n"
        f"🌍 Сервер: <b>{actual_server_id}</b>"
    )


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
