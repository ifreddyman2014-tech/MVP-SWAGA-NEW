"""
Основной модуль Telegram VPN-бота SWAGA.
aiogram v2 + asyncio scheduler для проверок подписок и бэкапов.
"""

import asyncio
import logging
import os
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
    set_payment_target_end,
    begin_fulfillment,
    mark_payment_fulfilled,
    get_pending_fulfillments,
    count_users,
    REFERRAL_BONUS_DAYS,
    create_payment as db_create_payment,
    get_payment as db_get_payment,
    init_promo_table,
    validate_promo_code,
    use_promo_code,
    create_promo_code,
    list_promo_codes,
    deactivate_promo_code,
    set_user_discount_promo,
    get_user_discount,
    clear_user_discount,
    get_subs_by_server,
    update_sub_server,
    init_migration_table,
    save_migration,
    get_pending_cleanups,
    mark_cleanup_done,
    get_all_user_ids,
    get_compensation_claimed,
    mark_compensation_claimed,
)
from xui_api import XUIAPI
# from yookassa_payment import create_payment as yookassa_create_payment  # Временно отключено
from backup import backup_now
from utils import generate_uuid, generate_sub_id, format_date, build_vless_link
from sub_app import start_sub_server, stop_sub_server, set_payment_callback
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

# Servers that must never be touched by automatic sync (protected reserve).
_PROTECTED_SERVER_IDS = {"us2", "us2-ws"}


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
    "<b>📱 iOS:</b>\n"
    "• <b>Happ Plus</b> — доступен в App Store РФ\n"
    "• <b>Karing</b> — доступен в App Store РФ\n"
    "• <b>V2RayTun</b> — нужно сменить регион Apple ID (Казахстан / Турция)\n\n"
    "<b>📱 Android:</b>\n"
    "• <b>Hiddify</b> — доступен в Google Play\n"
    "• <b>Karing</b> — скачать APK на karing.app\n\n"
    "Нажмите «Личный кабинет» → «Быстрое подключение» — откроется страница с пошаговой инструкцией для вашего приложения\n\n"
    "<b>💻 Windows / macOS:</b>\n"
    "• <b>v2rayN</b> (Windows) / <b>v2rayU</b> (macOS)\n"
    "• Скопируйте VLESS-ссылку в Личном кабинете → «Импорт из буфера обмена»\n\n"
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
    user_id = message.from_user.id
    user = await get_user(user_id)
    trial_used = bool(user and user["trial_used"])
    # Проверяем активную скидку
    _, discount = await get_user_discount(user_id)
    if discount > 0:
        text = f"📋 <b>Выберите тарифный план:</b>\n\n🎟 Активна скидка: <b>-{discount}%</b>"
    else:
        text = "📋 <b>Выберите тарифный план:</b>"
    await message.answer(
        text,
        reply_markup=plans_kb(trial_used, discount_percent=discount),
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

    # Получаем ВСЕ серверы и формируем конфиги для каждого
    from servers import server_manager
    if not server_manager.servers:
        server_manager.load_config()

    # Используем ВСЕ enabled серверы, а не только healthy
    all_servers = [s for s in server_manager.servers.values() if s.enabled] if server_manager.servers else []
    all_configs = []

    location_flags = {
        "DE": "🇩🇪", "NL": "🇳🇱", "EE": "🇪🇪", "US": "🇺🇸", "FI": "🇫🇮",
        "FR": "🇫🇷", "GB": "🇬🇧", "LV": "🇱🇻", "RU": "🇷🇺", "KZ": "🇰🇿",
    }

    location_names = {
        "DE": "Germany", "NL": "Netherlands", "EE": "Estonia", "US": "USA", "FI": "Finland",
        "FR": "France", "GB": "UK", "LV": "Latvia", "RU": "Russia", "KZ": "Kazakhstan",
    }

    # Формируем конфиги для ВСЕХ серверов
    if all_servers:
        for server in all_servers:
            if server.reality_pbk or getattr(server, "transport", "") == "ws":
                vless_link = build_vless_link(
                    uuid_str=sub["vless_uuid"],
                    host=server.host,
                    port=server.vpn_port,
                    transport=server.transport or VPN_TRANSPORT,
                    path=server.transport_path or VPN_PATH,
                    camouflage_host=server.transport_host or VPN_CAMOUFLAGE_HOST,
                    xhttp_mode=server.xhttp_mode or VPN_XHTTP_MODE,
                    reality_pbk=server.reality_pbk,
                    reality_sid=server.reality_sid,
                    reality_fp=server.reality_fp or REALITY_FINGERPRINT,
                    reality_sni=server.reality_sni,
                    reality_spx=REALITY_SPIDERX,
                    remark=f"SWAGA {location_names.get(server.location, server.location or '')}".strip() or server.name,
                )
            else:
                vless_link = build_vless_link(
                    uuid_str=sub["vless_uuid"],
                    host=server.host,
                    port=server.vpn_port,
                    transport=VPN_TRANSPORT,
                    path=VPN_PATH,
                    camouflage_host=VPN_CAMOUFLAGE_HOST,
                    xhttp_mode=VPN_XHTTP_MODE,
                    reality_pbk=REALITY_PUBLIC_KEY,
                    reality_sid=REALITY_SHORT_ID,
                    reality_fp=REALITY_FINGERPRINT,
                    reality_sni=REALITY_SNI,
                    reality_spx=REALITY_SPIDERX,
                    remark=f"SWAGA {location_names.get(server.location, server.location or '')}".strip() or server.name,
                )

            flag = location_flags.get(server.location, "🌐")
            all_configs.append({
                "name": server.name,
                "flag": flag,
                "link": vless_link
            })
    else:
        # Fallback на дефолтный сервер
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
        all_configs.append({
            "name": "SWAGA VPN",
            "flag": "🌐",
            "link": vless_link
        })

    plan_name = PLANS.get(sub["plan"], {}).get("name", sub["plan"])
    end_date = format_date(sub["end_date"])

    # Подсчет оставшихся дней
    from datetime import datetime
    end_dt = datetime.fromisoformat(sub["end_date"]) if isinstance(sub["end_date"], str) else sub["end_date"]
    days_left = max((end_dt - datetime.utcnow()).days, 0)

    cab_sub_id = sub.get("xui_sub_id", "")
    connect_base = SUB_BASE_URL.replace("/sub/", "/connect/")
    cab_sub_url = f"{connect_base}{cab_sub_id}" if cab_sub_id else ""

    # Формируем список всех конфигов
    configs_text = "\n\n".join([
        f"{cfg['flag']} <b>{cfg['name']}</b>\n<code>{cfg['link']}</code>"
        for cfg in all_configs
    ])

    text = (
        "👤 <b>Личный кабинет</b>\n\n"
        f"📦 Тариф: <b>{plan_name}</b>\n"
        f"📅 Активна до: <b>{end_date}</b>\n"
        f"⏱ Осталось: <b>{days_left} дн.</b>\n"
        f"🌍 Доступно серверов: <b>{len(all_configs)}</b>\n\n"
        f"{configs_text}\n\n"
        f"<i>💡 Выбери любой сервер — все работают одновременно!</i>\n"
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


@dp.message_handler(commands=["reissue"])
async def cmd_reissue(message: types.Message) -> None:
    """Перевыпустить VPN-доступ для пользователя по Telegram ID (только для админов).
    Использование: /reissue <user_id>
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Только для администраторов.")
        return

    args = message.get_args().strip()
    if not args or not args.isdigit():
        await message.answer("Использование: /reissue <telegram_user_id>")
        return

    target_id = int(args)
    sub = await get_active_sub(target_id)
    if not sub:
        await message.answer(f"❌ Активная подписка для {target_id} не найдена.")
        return

    old_uuid = sub.get("vless_uuid", "")
    sub_db_id = sub["sub_id"]
    xui_sub_id = sub.get("xui_sub_id", "")
    end_date = sub.get("end_date", "")
    expiry_ms = int(datetime.fromisoformat(end_date).timestamp() * 1000) if end_date else 0

    new_uuid = generate_uuid()
    new_email = f"tg_{target_id}_{int(datetime.utcnow().timestamp())}"

    await message.answer(f"🔄 Перевыпускаю доступ для {target_id}...")

    from servers import server_manager
    if not server_manager.servers:
        server_manager.load_config()
    enabled_servers = [s for s in server_manager.get_all_servers() if s.enabled]

    added = []
    for server in enabled_servers:
        try:
            if old_uuid:
                _server_delete_client(server, old_uuid)
            ok = _server_add_client(server, new_uuid, new_email, sub_id=xui_sub_id, expiry_ms=expiry_ms, flow=server.flow)
            if ok:
                added.append(server.name)
        except Exception as e:
            logger.error("reissue: ошибка на %s: %s", server.name, e)

    if not added:
        await message.answer("❌ Не удалось добавить клиента ни на один сервер.")
        return

    # Обновляем UUID в БД
    await update_sub_server(sub_db_id, sub.get("server_id", ""), new_uuid, new_email, xui_sub_id)

    await message.answer(
        f"✅ Доступ перевыпущен для {target_id}\n"
        f"Серверы: {', '.join(added)}\n"
        f"Подписка действует до: {end_date[:10] if end_date else '?'}"
    )

    # Уведомляем пользователя и отправляем кнопку обновления подписки
    if xui_sub_id:
        connect_base = SUB_BASE_URL.replace("/sub/", "/connect/")
        connect_url = f"{connect_base}{xui_sub_id}"
        user_kb = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔄 Обновить подписку", url=connect_url)
        )
        try:
            await bot.send_message(
                target_id,
                "🔄 <b>Ваш VPN-доступ был перевыпущен.</b>\n\n"
                "Нажмите кнопку ниже и обновите подписку в V2RayTun, "
                "чтобы продолжить пользоваться VPN.",
                parse_mode="HTML",
                reply_markup=user_kb,
            )
        except Exception as e:
            logger.warning("reissue: не удалось уведомить пользователя %s: %s", target_id, e)
            await message.answer("⚠️ Не удалось отправить уведомление пользователю (заблокировал бота?).")


@dp.message_handler(commands=["db_stats"])
async def cmd_db_stats(message: types.Message) -> None:
    """Статистика базы данных (только для админов)."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    import aiosqlite
    from config import DB_PATH

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Всего пользователей
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0]

        # Новые за сегодня
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE date(reg_date) = date('now')")
        new_today = (await cur.fetchone())[0]

        # Новые за 7 дней
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE reg_date >= datetime('now', '-7 days')")
        new_week = (await cur.fetchone())[0]

        # Активные подписки по плану
        cur = await db.execute("""
            SELECT plan, COUNT(*) as cnt FROM subscriptions
            WHERE is_active=1 AND end_date >= datetime('now')
            GROUP BY plan ORDER BY cnt DESC
        """)
        plans = await cur.fetchall()

        # Платящие (1m, 3m, 1y)
        cur = await db.execute("""
            SELECT COUNT(*) FROM subscriptions
            WHERE is_active=1 AND end_date >= datetime('now') AND plan IN ('1m','3m','1y')
        """)
        paying = (await cur.fetchone())[0]

        # По серверам
        cur = await db.execute("""
            SELECT server_id, COUNT(*) as cnt FROM subscriptions
            WHERE is_active=1 AND end_date >= datetime('now')
            GROUP BY server_id ORDER BY cnt DESC
        """)
        by_server = await cur.fetchall()

        # Выручка за всё время
        cur = await db.execute("SELECT SUM(amount) FROM payments WHERE status='succeeded'")
        revenue_all = (await cur.fetchone())[0] or 0

        # Выручка за 30 дней
        cur = await db.execute("""
            SELECT SUM(amount) FROM payments
            WHERE status='succeeded' AND paid_at >= datetime('now', '-30 days')
        """)
        revenue_30d = (await cur.fetchone())[0] or 0

        # Выручка за 7 дней
        cur = await db.execute("""
            SELECT SUM(amount) FROM payments
            WHERE status='succeeded' AND paid_at >= datetime('now', '-7 days')
        """)
        revenue_7d = (await cur.fetchone())[0] or 0

        # Истекают в ближайшие 7 дней
        cur = await db.execute("""
            SELECT COUNT(*) FROM subscriptions
            WHERE is_active=1
              AND end_date >= datetime('now')
              AND end_date <= datetime('now', '+7 days')
              AND plan IN ('1m','3m','1y')
        """)
        expiring_7d = (await cur.fetchone())[0]

    plan_names = {'trial': 'Триал', '1m': '1 месяц', '3m': '3 месяца', '1y': '1 год',
                  'giveaway_7d': 'Гивей 7д', 'giveaway_365d': 'Гивей 365д'}

    total_active = sum(r[1] for r in plans)
    plans_text = "\n".join(
        f"  • {plan_names.get(r[0], r[0])}: <b>{r[1]}</b>" for r in plans
    )
    servers_text = "\n".join(
        f"  • {r[0]}: <b>{r[1]}</b>" for r in by_server
    )

    text = (
        f"📊 <b>Статистика SWAGA VPN</b>\n\n"
        f"👥 <b>Пользователи</b>\n"
        f"  • Всего в БД: <b>{total_users}</b>\n"
        f"  • Новых сегодня: <b>{new_today}</b>\n"
        f"  • Новых за 7 дней: <b>{new_week}</b>\n\n"
        f"🔑 <b>Подписки</b>\n"
        f"  • Активных всего: <b>{total_active}</b>\n"
        f"  • Платящих: <b>{paying}</b>\n"
        f"  • Истекают за 7 дней: <b>{expiring_7d}</b>\n\n"
        f"📋 <b>По тарифам:</b>\n{plans_text}\n\n"
        f"🌍 <b>По серверам:</b>\n{servers_text}\n\n"
        f"💰 <b>Выручка</b>\n"
        f"  • За 7 дней: <b>{int(revenue_7d):,} ₽</b>\n"
        f"  • За 30 дней: <b>{int(revenue_30d):,} ₽</b>\n"
        f"  • За всё время: <b>{int(revenue_all):,} ₽</b>"
    )

    await message.answer(text)


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


@dp.message_handler(commands=["promo_add"])
async def cmd_promo_add(message: types.Message) -> None:
    """
    Создать промокод на бонусные дни (только для админов).
    Формат: /promo_add КОД ДНЕЙ [МАКС_ИСПОЛЬЗОВАНИЙ]
    Пример: /promo_add WINTER2026 30 100
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args().split()
    if len(args) < 2:
        await message.answer(
            "❌ Формат: <code>/promo_add КОД ДНЕЙ [МАКС_ИСПОЛЬЗОВАНИЙ]</code>\n\n"
            "Пример: <code>/promo_add WINTER2026 30 100</code>\n"
            "— Промокод WINTER2026 даёт +30 дней, лимит 100 использований\n\n"
            "Пример: <code>/promo_add VIP7 7</code>\n"
            "— Промокод VIP7 даёт +7 дней, без лимита\n\n"
            "<i>Для скидок: /promo_discount КОД ПРОЦЕНТ</i>"
        )
        return

    code = args[0].upper()
    try:
        bonus_days = int(args[1])
    except ValueError:
        await message.answer("❌ Количество дней должно быть числом.")
        return

    max_uses = 0
    if len(args) > 2:
        try:
            max_uses = int(args[2])
        except ValueError:
            await message.answer("❌ Макс. использований должно быть числом.")
            return

    success = await create_promo_code(code, bonus_days=bonus_days, max_uses=max_uses)
    if success:
        limit_text = f"лимит {max_uses}" if max_uses else "без лимита"
        await message.answer(
            f"✅ <b>Промокод создан!</b>\n\n"
            f"🎟 Код: <code>{code}</code>\n"
            f"🎁 Бонус: +{bonus_days} дней\n"
            f"📊 Лимит: {limit_text}"
        )
    else:
        await message.answer(f"❌ Не удалось создать промокод. Возможно, код <b>{code}</b> уже существует.")


@dp.message_handler(commands=["promo_discount"])
async def cmd_promo_discount(message: types.Message) -> None:
    """
    Создать промокод на скидку (только для админов).
    Формат: /promo_discount КОД ПРОЦЕНТ [МАКС_ИСПОЛЬЗОВАНИЙ]
    Пример: /promo_discount SALE30 30 50
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args().split()
    if len(args) < 2:
        await message.answer(
            "❌ Формат: <code>/promo_discount КОД ПРОЦЕНТ [МАКС_ИСПОЛЬЗОВАНИЙ]</code>\n\n"
            "Пример: <code>/promo_discount SALE30 30 50</code>\n"
            "— Промокод SALE30 даёт скидку 30%, лимит 50 использований\n\n"
            "Пример: <code>/promo_discount VIP50 50</code>\n"
            "— Промокод VIP50 даёт скидку 50%, без лимита"
        )
        return

    code = args[0].upper()
    try:
        discount_percent = int(args[1])
        if discount_percent < 1 or discount_percent > 99:
            await message.answer("❌ Скидка должна быть от 1 до 99%.")
            return
    except ValueError:
        await message.answer("❌ Процент скидки должен быть числом.")
        return

    max_uses = 0
    if len(args) > 2:
        try:
            max_uses = int(args[2])
        except ValueError:
            await message.answer("❌ Макс. использований должно быть числом.")
            return

    success = await create_promo_code(code, discount_percent=discount_percent, max_uses=max_uses)
    if success:
        limit_text = f"лимит {max_uses}" if max_uses else "без лимита"
        await message.answer(
            f"✅ <b>Промокод на скидку создан!</b>\n\n"
            f"🎟 Код: <code>{code}</code>\n"
            f"💰 Скидка: -{discount_percent}%\n"
            f"📊 Лимит: {limit_text}"
        )
    else:
        await message.answer(f"❌ Не удалось создать промокод. Возможно, код <b>{code}</b> уже существует.")


@dp.message_handler(commands=["promo_list"])
async def cmd_promo_list(message: types.Message) -> None:
    """Список всех промокодов (только для админов)."""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    promos = await list_promo_codes()
    if not promos:
        await message.answer("📋 Промокодов пока нет.\n\nСоздайте: <code>/promo_add КОД ДНЕЙ</code>")
        return

    text = "🎟 <b>Список промокодов:</b>\n\n"
    for p in promos:
        status = "✅" if p["is_active"] else "❌"
        uses = p["uses_count"]
        max_uses = p["max_uses"] if p["max_uses"] > 0 else "∞"
        # Показываем или дни, или скидку
        if p["bonus_days"] > 0:
            bonus_info = f"+{p['bonus_days']} дн."
        elif p["discount_percent"] > 0:
            bonus_info = f"-{p['discount_percent']}%"
        else:
            bonus_info = "—"
        text += (
            f"{status} <code>{p['code']}</code>\n"
            f"   {bonus_info} | {uses}/{max_uses} исп.\n"
        )

    text += "\n<i>Удалить: /promo_del КОД</i>"
    await message.answer(text)


@dp.message_handler(commands=["promo_del"])
async def cmd_promo_del(message: types.Message) -> None:
    """Деактивировать промокод (только для админов)."""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    code = message.get_args().strip().upper()
    if not code:
        await message.answer("❌ Укажите код: <code>/promo_del КОД</code>")
        return

    success = await deactivate_promo_code(code)
    if success:
        await message.answer(f"✅ Промокод <code>{code}</code> деактивирован.")
    else:
        await message.answer(f"❌ Промокод <code>{code}</code> не найден.")


@dp.message_handler(commands=["user_info"])
async def cmd_user_info(message: types.Message) -> None:
    """
    Просмотр информации о пользователе и его подписке (только для админов).
    Формат: /user_info USER_ID
    Пример: /user_info 123456789
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args().strip()
    if not args:
        await message.answer(
            "❌ Формат: <code>/user_info USER_ID</code>\n\n"
            "Пример: <code>/user_info 123456789</code>\n"
            "— Показать информацию о пользователе и его подписке"
        )
        return

    try:
        target_user_id = int(args)
    except ValueError:
        await message.answer("❌ USER_ID должен быть числом.")
        return

    # Получаем информацию о пользователе
    user = await get_user(target_user_id)
    if not user:
        await message.answer(f"❌ Пользователь с ID <code>{target_user_id}</code> не найден в базе.")
        return

    # Получаем активную подписку
    sub = await get_active_sub(target_user_id)

    # Формируем сообщение с информацией
    text = f"👤 <b>Информация о пользователе</b>\n\n"
    text += f"🆔 ID: <code>{user['user_id']}</code>\n"
    text += f"👤 Username: @{user['username']}" if user['username'] else f"👤 Username: <i>не указан</i>\n"
    text += f"\n📅 Регистрация: {format_date(user['reg_date'])}\n"
    text += f"🎁 Триал использован: {'Да ✅' if user['trial_used'] else 'Нет ❌'}\n\n"

    if sub:
        # Вычисляем оставшееся время
        end_date = datetime.fromisoformat(sub['end_date'])
        now = datetime.utcnow()
        days_left = (end_date - now).days

        text += f"📦 <b>Активная подписка</b>\n\n"
        text += f"📋 План: <code>{sub['plan']}</code>\n"
        text += f"📅 Начало: {format_date(sub['start_date'])}\n"
        text += f"📅 Окончание: {format_date(sub['end_date'])}\n"

        if days_left > 0:
            text += f"⏳ Осталось дней: <b>{days_left}</b>\n"
        elif days_left == 0:
            text += f"⏳ Истекает сегодня\n"
        else:
            text += f"⏳ Просрочена на <b>{abs(days_left)}</b> дней\n"

        text += f"🔑 UUID: <code>{sub['vless_uuid']}</code>\n"
        if sub['server_id']:
            text += f"🌐 Сервер: <code>{sub['server_id']}</code>\n"
    else:
        text += f"📦 <b>Активная подписка</b>\n\n"
        text += f"❌ Нет активной подписки\n"

    text += f"\n<i>Управление: /user_extend {target_user_id} ДНЕЙ</i>"

    await message.answer(text)


@dp.message_handler(commands=["web_user"])
async def cmd_web_user(message: types.Message) -> None:
    """
    Поиск web-пользователя по email (только для админов).
    Формат: /web_user email@example.com
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args().strip().lower()
    if not args:
        await message.answer(
            "❌ Формат: <code>/web_user EMAIL</code>\n\n"
            "Пример: <code>/web_user user@gmail.com</code>",
            parse_mode="HTML",
        )
        return

    from database import get_web_user_by_email
    web_user = await get_web_user_by_email(args)
    if not web_user:
        await message.answer(
            f"❌ Web-пользователь <code>{args}</code> не найден в базе.",
            parse_mode="HTML",
        )
        return

    synthetic_uid = web_user.get("user_id")
    sub = await get_active_sub(synthetic_uid) if synthetic_uid else None

    text = "🌐 <b>Web-пользователь</b>\n\n"
    text += f"📧 Email: <code>{web_user['email']}</code>\n"
    text += f"🆔 Web ID: <code>{web_user['id']}</code>\n"
    text += f"🔑 Synthetic UID: <code>{synthetic_uid}</code>\n"
    text += f"📅 Регистрация: {format_date(web_user['created_at'])}\n\n"

    if sub:
        end_date = datetime.fromisoformat(sub['end_date'])
        now = datetime.utcnow()
        days_left = (end_date - now).days
        text += "📦 <b>Подписка</b>\n"
        text += f"📋 План: <code>{sub['plan']}</code>\n"
        text += f"📅 До: {format_date(sub['end_date'])}\n"
        if days_left > 0:
            text += f"⏳ Осталось: <b>{days_left} дн.</b>\n"
        elif days_left == 0:
            text += "⏳ Истекает сегодня\n"
        else:
            text += f"⏳ Просрочена на <b>{abs(days_left)} дн.</b>\n"
        if sub.get('server_id'):
            text += f"🌐 Сервер: <code>{sub['server_id']}</code>\n"
    else:
        text += "📦 <b>Подписка:</b> ❌ нет активной\n"

    text += f"\n<i>Управление: /user_extend {synthetic_uid} ДНЕЙ</i>"

    await message.answer(text, parse_mode="HTML")


@dp.message_handler(commands=["user_extend"])
async def cmd_user_extend(message: types.Message) -> None:
    """
    Изменить количество дней подписки пользователя (только для админов).
    Формат: /user_extend USER_ID DAYS
    Пример: /user_extend 123456789 30 (добавить 30 дней)
    Пример: /user_extend 123456789 -7 (убрать 7 дней)
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args().split()
    if len(args) < 2:
        await message.answer(
            "❌ Формат: <code>/user_extend USER_ID ДНЕЙ</code>\n\n"
            "Пример: <code>/user_extend 123456789 30</code>\n"
            "— Добавить 30 дней к подписке\n\n"
            "Пример: <code>/user_extend 123456789 -7</code>\n"
            "— Убрать 7 дней от подписки"
        )
        return

    try:
        target_user_id = int(args[0])
        days = int(args[1])
    except ValueError:
        await message.answer("❌ USER_ID и ДНЕЙ должны быть числами.")
        return

    # Проверяем существование пользователя
    user = await get_user(target_user_id)
    if not user:
        await message.answer(f"❌ Пользователь с ID <code>{target_user_id}</code> не найден в базе.")
        return

    # Получаем активную подписку
    sub = await get_active_sub(target_user_id)
    if not sub:
        await message.answer(
            f"❌ У пользователя <code>{target_user_id}</code> нет активной подписки.\n\n"
            f"Создайте подписку через покупку или триал."
        )
        return

    # Продлеваем/уменьшаем подписку
    success = await extend_subscription(target_user_id, days)

    if success:
        # Получаем обновленную подписку для показа новой даты
        updated_sub = await get_active_sub(target_user_id)
        end_date = datetime.fromisoformat(updated_sub['end_date'])
        now = datetime.utcnow()
        days_left = (end_date - now).days

        action = "добавлено" if days > 0 else "убавлено"
        await message.answer(
            f"✅ Подписка пользователя <code>{target_user_id}</code> обновлена!\n\n"
            f"📅 {action.capitalize()}: <b>{abs(days)}</b> дней\n"
            f"📅 Новая дата окончания: {format_date(updated_sub['end_date'])}\n"
            f"⏳ Осталось дней: <b>{days_left}</b>"
        )

        # Уведомляем пользователя
        try:
            user_text = (
                f"🎁 <b>Ваша подписка обновлена!</b>\n\n"
                f"Администратор {'добавил' if days > 0 else 'убавил'} <b>{abs(days)}</b> дней к вашей подписке.\n\n"
                f"📅 Новая дата окончания: {format_date(updated_sub['end_date'])}\n"
                f"⏳ Осталось дней: <b>{days_left}</b>"
            )
            await bot.send_message(target_user_id, user_text)
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя {target_user_id}: {e}")
    else:
        await message.answer(
            f"❌ Не удалось обновить подписку пользователя <code>{target_user_id}</code>."
        )


@dp.message_handler(commands=["giveaccess"])
async def cmd_give_access(message: types.Message) -> None:
    """
    Выдать или продлить подписку пользователю (только для админов).
    Формат: /giveaccess USER_ID DAYS
    Пример: /giveaccess 123456789 30
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args().split()
    if len(args) < 2:
        await message.answer(
            "❌ Формат: <code>/giveaccess USER_ID ДНЕЙ</code>\n\n"
            "Пример: <code>/giveaccess 123456789 30</code>\n"
            "— Выдать 30 дней подписки пользователю"
        )
        return

    try:
        target_user_id = int(args[0])
        days = int(args[1])
    except ValueError:
        await message.answer("❌ USER_ID и ДНЕЙ должны быть числами.")
        return

    if days <= 0:
        await message.answer("❌ Количество дней должно быть больше 0.")
        return

    # Проверяем существование пользователя
    user = await get_user(target_user_id)
    if not user:
        # Создаем пользователя если не существует
        await create_user(target_user_id, "")
        user = await get_user(target_user_id)

    # Проверяем активную подписку
    sub = await get_active_sub(target_user_id)
    now = datetime.utcnow()

    if sub:
        # У пользователя есть активная подписка - продлеваем
        success = await extend_subscription(target_user_id, days)

        if success:
            updated_sub = await get_active_sub(target_user_id)
            end_date = datetime.fromisoformat(updated_sub['end_date'])
            days_left = max((end_date - now).days, 0)

            await message.answer(
                f"✅ Подписка продлена!\n\n"
                f"👤 Пользователь: <code>{target_user_id}</code>\n"
                f"➕ Добавлено: <b>{days}</b> дней\n"
                f"📅 Новая дата окончания: {format_date(updated_sub['end_date'])}\n"
                f"⏳ Осталось дней: <b>{days_left}</b>"
            )

            # Уведомляем пользователя
            try:
                user_text = (
                    f"🎁 <b>Подписка обновлена!</b>\n\n"
                    f"Администратор добавил <b>{days}</b> дней к вашей подписке.\n\n"
                    f"📅 Новая дата окончания: {format_date(updated_sub['end_date'])}\n"
                    f"⏳ Осталось дней: <b>{days_left}</b>"
                )
                await bot.send_message(target_user_id, user_text)
            except Exception as e:
                logger.warning(f"Не удалось уведомить пользователя {target_user_id}: {e}")
        else:
            await message.answer(
                f"❌ Не удалось продлить подписку пользователя <code>{target_user_id}</code>."
            )
    else:
        # Нет активной подписки - создаем новую
        from servers import server_manager

        if not server_manager.servers:
            server_manager.load_config()

        # Выбираем лучший сервер
        selected_server = server_manager.get_best_server()

        if not selected_server:
            await message.answer(
                "❌ Нет доступных серверов для создания подписки.\n"
                "Проверьте health check серверов."
            )
            return

        # Создаем UUID и email для пользователя
        import uuid as uuid_lib
        new_uuid = str(uuid_lib.uuid4())
        email = f"tg_{target_user_id}_{int(now.timestamp())}"

        # Вычисляем дату окончания
        end_date = now + timedelta(days=days)
        expiry_ms = int(end_date.timestamp() * 1000)

        # Создаем клиента на сервере
        try:
            sub_id_value = uuid_lib.uuid4().hex[:16]
            logger.info(f"Попытка создать ключ на сервере {selected_server.name} ({selected_server.id})")
            success = _server_add_client(
                selected_server, new_uuid, email,
                sub_id=sub_id_value, expiry_ms=expiry_ms, flow=selected_server.flow,
            )

            if not success:
                await message.answer(
                    f"❌ Не удалось создать ключ на сервере {selected_server.name}."
                )
                logger.error(f"Не удалось создать ключ на {selected_server.name}")
                return

            logger.info(f"✅ Создан ключ на сервере {selected_server.name} для пользователя {target_user_id}")

            # Сохраняем подписку в БД
            await create_subscription(
                user_id=target_user_id,
                plan="admin_gift",
                vless_uuid=new_uuid,
                start_date=now.isoformat(),
                end_date=end_date.isoformat(),
                server_id=selected_server.id,
                xui_email=email,
                xui_sub_id=sub_id_value,
            )

            # Синхронизируем с другими серверами
            other_servers = [s for s in server_manager.get_all_servers() if s.enabled and s.id != selected_server.id]
            if other_servers:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    _sync_client_to_other_servers,
                    new_uuid,
                    email,
                    sub_id_value,
                    expiry_ms,
                    selected_server.id,
                    other_servers,
                    False,  # is_renewal
                )

            days_left = max((end_date - now).days, 0)

            await message.answer(
                f"✅ Подписка создана!\n\n"
                f"👤 Пользователь: <code>{target_user_id}</code>\n"
                f"🎁 Выдано: <b>{days}</b> дней\n"
                f"🌍 Сервер: {selected_server.name}\n"
                f"📅 Дата окончания: {format_date(end_date.isoformat())}\n"
                f"⏳ Осталось дней: <b>{days_left}</b>"
            )

            # Уведомляем пользователя
            try:
                user_text = (
                    f"🎁 <b>Вам выдана подписка!</b>\n\n"
                    f"Администратор активировал для вас подписку на <b>{days}</b> дней.\n\n"
                    f"📅 Действует до: {format_date(end_date.isoformat())}\n"
                    f"⏳ Осталось дней: <b>{days_left}</b>\n\n"
                    f"Используйте /start для получения ключей."
                )
                await bot.send_message(target_user_id, user_text)
            except Exception as e:
                logger.warning(f"Не удалось уведомить пользователя {target_user_id}: {e}")

        except Exception as e:
            await message.answer(
                f"❌ Ошибка при создании подписки: {str(e)}"
            )
            logger.error(f"Ошибка создания подписки для {target_user_id}: {e}")
            logger.error(traceback.format_exc())


@dp.callback_query_handler(lambda c: c.data == "update_access")
async def cb_update_access(callback: types.CallbackQuery) -> None:
    """Обновить доступ: +7 дней компенсации для платных, активация триала для остальных."""
    user_id = callback.from_user.id
    await callback.answer()

    already_claimed = await get_compensation_claimed(user_id)
    if already_claimed:
        await callback.message.answer(
            "✅ Вы уже получили компенсацию.\n"
            "Если есть вопросы — обратитесь в поддержку.",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("Поддержка", url=SUPPORT_URL)
            ),
        )
        return

    sub = await get_active_sub(user_id)
    now = datetime.utcnow()

    if sub and sub.get("plan") != "trial":
        # Платный подписчик → добавляем 7 дней
        current_end = datetime.fromisoformat(sub["end_date"])
        new_end = current_end + timedelta(days=7)

        await extend_subscription_to_date(user_id, new_end)

        # Обновляем в 3X-UI
        new_expiry_ms = int(new_end.timestamp() * 1000)
        new_uuid = sub["vless_uuid"]
        email = sub.get("xui_email", f"tg_{user_id}")
        xui_sub_id = sub.get("xui_sub_id", "")
        actual_server_id = sub.get("server_id", "default")

        try:
            from servers import server_manager
            if not server_manager.servers:
                server_manager.load_config()
            server = server_manager.get_server(actual_server_id) if actual_server_id != "default" else None
            if server:
                # WS серверы не хранят expiry — только синхронизируем на остальные
                if getattr(server, "transport", "") != "ws":
                    srv_xui = XUIAPI()
                    protocol = "https" if getattr(server, 'xui_ssl', True) else "http"
                    srv_xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
                    login_resp_ok = srv_xui.login(server.xui_username, server.xui_password)
                    login_resp = type("_R", (), {"json": lambda self, **kw: {"success": login_resp_ok}})()
                    if login_resp.json().get("success"):
                        srv_xui._logged_in = True
                        srv_xui.update_client(
                            server.inbound_id, new_uuid, email,
                            sub_id=xui_sub_id, expiry_time=new_expiry_ms, flow=server.flow,
                        )
                other_servers = [s for s in server_manager.get_all_servers() if s.enabled]
                if len(other_servers) > 1:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, _sync_client_to_other_servers,
                        new_uuid, email, xui_sub_id, new_expiry_ms, actual_server_id, other_servers,
                        True,  # is_renewal
                    )
            else:
                xui.update_client(INBOUND_ID, new_uuid, email, sub_id=xui_sub_id, expiry_time=new_expiry_ms)
        except Exception as e:
            logger.error("Ошибка обновления 3X-UI при компенсации: %s", e)

        await mark_compensation_claimed(user_id)
        new_end_str = format_date(new_end.isoformat())
        await callback.message.answer(
            f"🎁 <b>Компенсация начислена!</b>\n\n"
            f"✅ Добавлено +7 дней к вашей подписке.\n"
            f"📅 Новая дата окончания: <b>{new_end_str}</b>\n\n"
            f"Спасибо за терпение! 💪",
        )
    else:
        # Нет активной платной подписки → проверяем триал
        user = await get_user(user_id)
        if user and not user.get("trial_used"):
            await callback.message.answer(
                "🎁 <b>Активируйте пробный период!</b>\n\n"
                "Вам доступны 7 дней бесплатного VPN.\n"
                "Нажмите кнопку ниже для активации.",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🎁 Получить 7 дней бесплатно", callback_data="plan_trial")
                ),
            )
        else:
            await callback.message.answer(
                "💬 Для получения компенсации обратитесь в поддержку.",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("Поддержка", url=SUPPORT_URL)
                ),
            )


BROADCAST_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "media", "broadcast.jpg")



@dp.message_handler(commands=["keygen"])
async def cmd_keygen(message: types.Message) -> None:
    """
    Создать гивевей-ключ без привязки к реальному пользователю.
    Формат: /keygen DAYS
    Пример: /keygen 30
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args().split()
    if not args or not args[0].isdigit():
        await message.answer(
            "❌ Формат: <code>/keygen ДНЕЙ</code>\n"
            "Пример: <code>/keygen 30</code>"
        )
        return

    days = int(args[0])
    if days < 1 or days > 3650:
        await message.answer(
            f"❌ Недопустимое значение: <b>{days}</b>\n"
            "Допустимо от <b>1 до 3650</b> дней."
        )
        return

    from servers import server_manager
    if not server_manager.servers:
        server_manager.load_config()

    servers = server_manager.get_healthy_servers()
    if not servers:
        await message.answer("❌ Нет доступных серверов. Проверьте health check.")
        return

    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    expiry_ms = int(end_date.timestamp() * 1000)

    import uuid as _uuid_lib
    import time as _time

    # Уникальный гивевей-ID (не пересекается с реальными Telegram ID)
    GIVEAWAY_BASE = 9_000_000_000
    giveaway_id = GIVEAWAY_BASE + (int(_time.time() * 1000) % 1_000_000_000)
    new_uuid = str(_uuid_lib.uuid4())
    sub_id_value = _uuid_lib.uuid4().hex[:16]
    email = f"giveaway_{giveaway_id}"

    await message.answer("⏳ Создаю ключи на серверах...")

    try:
        # Создаём фиктивного пользователя в БД
        await create_user(giveaway_id, f"giveaway_{giveaway_id}")

        selected_server = servers[0]

        success = _server_add_client(
            selected_server, new_uuid, email,
            sub_id=sub_id_value, expiry_ms=expiry_ms, flow=selected_server.flow,
        )
        if not success:
            await message.answer(f"❌ Не удалось создать ключ на {selected_server.name}.")
            return

        # Сохраняем подписку в БД
        await create_subscription(
            user_id=giveaway_id,
            plan=f"giveaway_{days}d",
            vless_uuid=new_uuid,
            start_date=now.isoformat(),
            end_date=end_date.isoformat(),
            server_id=selected_server.id,
            xui_email=email,
            xui_sub_id=sub_id_value,
        )

        # Синхронизируем на остальные серверы
        other_servers = [
            s for s in server_manager.get_all_servers()
            if s.enabled and s.id != selected_server.id
        ]
        if other_servers:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                _sync_client_to_other_servers,
                new_uuid, email, sub_id_value, expiry_ms,
                selected_server.id, other_servers,
                False,  # is_renewal
            )

        sub_url = f"{SUB_BASE_URL}{sub_id_value}"
        connect_url = f"{SUB_BASE_URL.replace('/sub/', '/connect/')}{sub_id_value}"

        # VLESS-ссылка основного сервера — для прямой вставки в VPN-приложение без сайта
        vless_direct = build_vless_link(
            uuid_str=new_uuid,
            host=selected_server.host,
            port=selected_server.vpn_port,
            transport=selected_server.transport or VPN_TRANSPORT,
            path=selected_server.transport_path or VPN_PATH,
            camouflage_host=selected_server.transport_host or VPN_CAMOUFLAGE_HOST,
            xhttp_mode=selected_server.xhttp_mode or VPN_XHTTP_MODE,
            reality_pbk=selected_server.reality_pbk,
            reality_sid=selected_server.reality_sid,
            reality_fp=selected_server.reality_fp or REALITY_FINGERPRINT,
            reality_sni=selected_server.reality_sni,
            reality_spx=REALITY_SPIDERX,
            remark=f"SWAGA {selected_server.name}",
        )

        reply = (
            f"✅ <b>Гивевей-ключ создан</b>\n\n"
            f"⏱ Дней: <b>{days}</b>\n"
            f"📅 Действует до: <b>{end_date.strftime('%d.%m.%Y')}</b>\n\n"
            f"🔗 <b>Ссылка для пользователя (открывает страницу подключения):</b>\n"
            f"{connect_url}\n\n"
            f"📲 <b>VLESS-ссылка (вставить в Karing/Hiddify):</b>\n"
            f"<code>{vless_direct}</code>\n\n"
            f"📋 <b>Ссылка на подписку (для приложений):</b>\n"
            f"{sub_url}"
        )

        await message.answer(reply, disable_web_page_preview=True)
        logger.info(f"Admin {user_id} created giveaway key: {days}d, id={giveaway_id}")

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        logger.error(f"keygen error: {e}")
        logger.error(traceback.format_exc())

@dp.message_handler(commands=["broadcast"])
async def cmd_broadcast(message: types.Message) -> None:
    """Рассылка уведомления об обновлении сервиса всем пользователями (только для админов)."""
    if message.from_user.id not in ADMIN_IDS:
        return

    broadcast_text = (
        "📢 <b>SWAGA VPN — важное обновление</b>\n\n"
        "Мы протестировали все VPN-приложения и выбрали лучшее.\n\n"
        "🏆 <b>Karing — самое стабильное приложение для SWAGA VPN</b>\n"
        "Работает быстро, не отваливается, доступен в App Store РФ без смены региона.\n\n"
        "──────────────────────\n"
        "📥 <b>Шаг 1 — Установите Karing</b>\n\n"
        "📱 <a href=\"https://apps.apple.com/app/id6472431552\">iOS — App Store</a>\n"
        "📱 <a href=\"https://karing.app/en/download/\">Android — скачать APK</a>\n"
        "💻 <a href=\"https://github.com/KaringX/karing/releases\">Windows / macOS — GitHub</a>\n\n"
        "──────────────────────\n"
        "🔗 <b>Шаг 2 — Откройте страницу подключения</b>\n\n"
        "В этом боте: <b>Личный кабинет → Быстрое подключение</b>\n\n"
        "Если страница открылась внутри Telegram — нажмите <b>··· → Открыть в браузере</b>\n\n"
        "──────────────────────\n"
        "➕ <b>Шаг 3 — Добавьте подписку</b>\n\n"
        "На странице выберите вкладку <b>🟢 Karing</b>\n"
        "→ Нажмите зелёную кнопку «Добавить подписку в Karing»\n"
        "→ Karing откроется автоматически\n"
        "→ Нажмите <b>«Подтвердить»</b>\n\n"
        "Все серверы (🇫🇷 Франция, 🇺🇸 США, 🇬🇧 Великобритания) добавятся сами.\n\n"
        "──────────────────────\n"
        "🌐 <b>Шаг 4 — Подключитесь</b>\n\n"
        "В Karing:\n"
        "→ Нажмите на профиль <b>SWAGA VPN</b>\n"
        "→ Выберите любой сервер\n"
        "→ Нажмите большую кнопку <b>«Подключить»</b>\n"
        "→ При запросе «Разрешить VPN?» — нажмите <b>«Разрешить»</b>\n\n"
        "Статус изменится на <b>«Подключено»</b> ✅\n\n"
        "──────────────────────\n"
        "❓ Не получается? Пишите → @SWAGASupport_bot"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("📱 Скачать Karing (iOS)", url="https://apps.apple.com/app/id6472431552"),
        types.InlineKeyboardButton("📱 Скачать Karing (Android APK)", url="https://karing.app/en/download/"),
        types.InlineKeyboardButton("💻 Скачать Karing (Windows / macOS)", url="https://github.com/KaringX/karing/releases"),
    )
    kb.add(
        types.InlineKeyboardButton("💬 Написать в поддержку", url="https://t.me/SWAGASupport_bot")
    )

    instruction_text = (
        "📲 <b>Подробная инструкция — как подключить Karing</b>\n\n"
        "──────────────────────\n"
        "📥 <b>Шаг 1 — Установите Karing</b>\n\n"
        "• <b>iOS:</b> App Store → поиск «Karing» → Установить\n"
        "• <b>Android:</b> karing.app → Download APK → установите файл\n"
        "  (разрешите «установку из неизвестных источников»)\n"
        "• <b>Windows:</b> GitHub → скачайте файл .exe → запустите\n"
        "• <b>macOS:</b> GitHub → скачайте файл .dmg → перетащите в Applications\n\n"
        "──────────────────────\n"
        "🔗 <b>Шаг 2 — Откройте страницу подключения</b>\n\n"
        "В боте нажмите: <b>Личный кабинет → Быстрое подключение</b>\n\n"
        "⚠️ Страница открылась внутри Telegram?\n"
        "Нажмите <b>··· (три точки)</b> → <b>«Открыть в браузере»</b>\n\n"
        "──────────────────────\n"
        "➕ <b>Шаг 3 — Добавьте подписку</b>\n\n"
        "На странице выберите вкладку <b>🟢 Karing</b>\n"
        "→ Нажмите зелёную кнопку <b>«Добавить подписку в Karing»</b>\n"
        "→ Karing откроется автоматически\n"
        "→ Появится окно — нажмите <b>«Подтвердить»</b>\n"
        "→ Подождите 3–5 секунд\n\n"
        "Все серверы добавятся автоматически:\n"
        "🇫🇷 Франция · 🇺🇸 США 1 · 🇺🇸 США 2 · 🇬🇧 Великобритания\n\n"
        "──────────────────────\n"
        "🌐 <b>Шаг 4 — Выберите сервер и подключитесь</b>\n\n"
        "→ Нажмите на профиль <b>SWAGA VPN</b>\n"
        "→ Выберите сервер (рекомендуем 🇫🇷 Франция или 🇺🇸 США 1)\n"
        "→ Нажмите большую кнопку <b>«Подключить»</b>\n"
        "→ Появится запрос <b>«Разрешить VPN?»</b> → нажмите <b>«Разрешить»</b>\n\n"
        "Статус изменится на <b>«Подключено»</b> — VPN работает ✅\n\n"
        "──────────────────────\n"
        "🔄 <b>Не работает / серверы не грузятся?</b>\n\n"
        "→ Нажмите на профиль SWAGA VPN\n"
        "→ Нажмите значок обновления <b>🔄</b> рядом с названием\n"
        "→ Подождите загрузки и подключитесь снова\n\n"
        "──────────────────────\n"
        "❓ Остались вопросы? → @SWAGASupport_bot"
    )

    user_ids = await get_all_user_ids()
    status_msg = await message.answer(f"📤 Начинаю рассылку... Пользователей: {len(user_ids)}")

    # Кешируем file_id фото после первой успешной отправки (быстрее для массовой рассылки)
    # Фото и текст отправляются отдельно — обходим лимит caption 1024 символа
    use_photo = os.path.exists(BROADCAST_IMAGE_PATH)
    photo_file_id: str | None = None

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            if use_photo:
                if photo_file_id:
                    await bot.send_photo(uid, photo_file_id)
                else:
                    with open(BROADCAST_IMAGE_PATH, "rb") as f:
                        sent_msg = await bot.send_photo(uid, types.InputFile(f))
                    photo_file_id = sent_msg.photo[-1].file_id
            await bot.send_message(uid, broadcast_text, reply_markup=kb, parse_mode=types.ParseMode.HTML)
            await bot.send_message(uid, instruction_text, parse_mode=types.ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 сообщений/сек, в пределах лимитов Telegram

    await status_msg.edit_text(
        f"✅ Рассылка завершена!\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Не доставлено (заблокировали бота): {failed}"
    )


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

# Состояние ожидания ввода промокода
waiting_promo_code: set[int] = set()


@dp.callback_query_handler(lambda c: c.data == "enter_promo")
async def cb_enter_promo(callback: types.CallbackQuery) -> None:
    """Начать ввод промокода."""
    waiting_promo_code.add(callback.from_user.id)
    await callback.message.answer(
        "🎟 <b>Введите промокод:</b>\n\n"
        "Отправьте промокод одним сообщением.",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message_handler(lambda m: m.from_user.id in waiting_promo_code)
async def handle_promo_code_input(message: types.Message) -> None:
    """Обработка введённого промокода."""
    user_id = message.from_user.id
    waiting_promo_code.discard(user_id)

    code = message.text.strip().upper()
    if not code:
        await message.answer("❌ Промокод не может быть пустым.")
        return

    # Проверяем промокод
    is_valid, error_msg, promo = await validate_promo_code(code, user_id)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return

    # Проверяем, есть ли активная подписка для применения бонуса
    sub = await get_active_sub(user_id)
    bonus_days = promo["bonus_days"]
    discount = promo["discount_percent"]

    if bonus_days > 0 and sub:
        # Применяем бонусные дни
        await extend_subscription(user_id, bonus_days)
        await use_promo_code(promo["id"], user_id)
        await message.answer(
            f"✅ <b>Промокод применён!</b>\n\n"
            f"🎁 Добавлено дней: <b>+{bonus_days}</b>\n\n"
            f"Проверьте новую дату в Личном кабинете.",
            parse_mode="HTML",
        )
    elif bonus_days > 0 and not sub:
        await message.answer(
            f"ℹ️ Промокод даёт <b>+{bonus_days} дней</b>, "
            f"но у вас нет активной подписки.\n\n"
            f"Сначала оформите подписку, затем примените промокод.",
            parse_mode="HTML",
        )
    elif discount > 0:
        # Промокод на скидку — сохраняем для использования при оплате
        await set_user_discount_promo(user_id, promo["id"], discount)
        # Показываем меню с новыми ценами
        user = await get_user(user_id)
        trial_used = bool(user and user["trial_used"])
        await message.answer(
            f"✅ <b>Промокод активирован!</b>\n\n"
            f"💰 Скидка: <b>-{discount}%</b>\n\n"
            f"Выберите тариф:",
            parse_mode="HTML",
            reply_markup=plans_kb(trial_used, discount_percent=discount),
        )
    else:
        await message.answer("❌ Промокод не содержит бонусов.")


@dp.callback_query_handler(lambda c: c.data == "get_access")
async def cb_get_access(callback: types.CallbackQuery) -> None:
    """Inline-кнопка 'Получить доступ' (из инструкции/кабинета)."""
    user_id = callback.from_user.id
    user = await get_user(user_id)
    trial_used = bool(user and user["trial_used"])
    # Проверяем активную скидку
    _, discount = await get_user_discount(user_id)
    if discount > 0:
        text = f"📋 <b>Выберите тарифный план:</b>\n\n🎟 Активна скидка: <b>-{discount}%</b>"
    else:
        text = "📋 <b>Выберите тарифный план:</b>"
    await callback.message.answer(
        text,
        reply_markup=plans_kb(trial_used, discount_percent=discount),
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

    # Сразу создаем подписку без выбора сервера (автоматический выбор лучшего)
    await callback.answer()
    await _create_subscription_on_server(callback, plan_key, None)


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


def _server_add_client(
    server,
    uuid: str,
    email: str,
    sub_id: str = "",
    expiry_ms: int = 0,
    flow: str = "",
) -> bool:
    """Add VPN client — WS servers via SSH, xui servers via API."""
    if getattr(server, "transport", "") == "ws":
        import ws_manager
        return ws_manager.add_client(
            server.xui_host,
            getattr(server, "ws_ssh_password", ""),
            getattr(server, "ws_config_path", ""),
            uuid, email,
        )
    from xui_api import XUIAPI
    srv_xui = XUIAPI()
    protocol = "https" if getattr(server, "xui_ssl", True) else "http"
    srv_xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
    if not srv_xui.login(server.xui_username, server.xui_password):
        logger.warning("_server_add_client: auth failed on %s", server.name)
        return False
    return srv_xui.add_client(
        server.inbound_id, uuid, email,
        sub_id=sub_id, expiry_time=expiry_ms, flow=flow,
    )


def _server_delete_client(server, uuid: str) -> bool:
    """Delete VPN client — WS servers via SSH, xui servers via API."""
    if getattr(server, "transport", "") == "ws":
        import ws_manager
        return ws_manager.delete_client(
            server.xui_host,
            getattr(server, "ws_ssh_password", ""),
            getattr(server, "ws_config_path", ""),
            uuid,
        )
    from xui_api import XUIAPI
    srv_xui = XUIAPI()
    protocol = "https" if getattr(server, "xui_ssl", True) else "http"
    srv_xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
    if not srv_xui.login(server.xui_username, server.xui_password):
        logger.warning("_server_delete_client: auth failed on %s", server.name)
        return False
    return srv_xui.delete_client(server.inbound_id, uuid)


def _server_sync_client(
    server,
    uuid: str,
    email: str,
    sub_id: str = "",
    expiry_ms: int = 0,
    flow: str = "",
) -> bool:
    """
    Идемпотентная синхронизация клиента на один сервер.

    WS-серверы: ws_manager.add_client уже идемпотентен (проверяет UUID перед добавлением).
    XUI-серверы: вызываем add_or_update_client — сначала updateClient по UUID,
                 при ответе «not found» — addClient. Это исключает Duplicate email
                 при продлениях, сохраняя создание при первичной регистрации.
    """
    if getattr(server, "transport", "") == "ws":
        import ws_manager
        return ws_manager.add_client(
            server.xui_host,
            getattr(server, "ws_ssh_password", ""),
            getattr(server, "ws_config_path", ""),
            uuid, email,
        )
    from xui_api import XUIAPI
    srv_xui = XUIAPI()
    protocol = "https" if getattr(server, "xui_ssl", True) else "http"
    srv_xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
    if not srv_xui.login(server.xui_username, server.xui_password):
        logger.warning("_server_sync_client: auth failed on %s", server.name)
        return False
    return srv_xui.add_or_update_client(
        server.inbound_id, uuid, email,
        sub_id=sub_id, expiry_time=expiry_ms, flow=flow,
    )


def _sync_client_to_other_servers(
    uuid: str, email: str, sub_id: str, expiry_ms: int,
    primary_server_id: str, enabled_servers: list,
    is_renewal: bool = False,
) -> None:
    """
    Синхронизирует клиента на все включённые серверы кроме основного.

    is_renewal=True: клиент уже существует → используем add_or_update (update first).
    is_renewal=False: новая подписка → то же самое, add_or_update безопасен в обоих случаях.
    Параметр сохранён для явности контекста и будущего логирования.
    """
    for server in enabled_servers:
        if server.id == primary_server_id:
            continue
        if server.id in _PROTECTED_SERVER_IDS:
            logger.warning("sync: protected server %s excluded from sync target (uuid=%s)", server.id, uuid)
            continue
        try:
            ok = _server_sync_client(
                server, uuid, email,
                sub_id=sub_id, expiry_ms=expiry_ms, flow=server.flow,
            )
            if ok:
                logger.info("sync: %s %s on %s", email,
                            "updated" if is_renewal else "added", server.name)
            else:
                logger.error("sync: FAILED to sync %s on %s (expiry=%s, renewal=%s)",
                             email, server.name, expiry_ms, is_renewal)
        except Exception as e:
            logger.warning("sync: failed to sync %s to %s: %s", email, server.name, e)


def _delete_client_from_all_servers(uuid: str, inbound_id_fallback: int) -> None:
    """Delete an expired client from every enabled server (best-effort, sync)."""
    from xui_api import XUIAPI
    from servers import server_manager

    if not server_manager.servers:
        server_manager.load_config()

    servers = [s for s in server_manager.get_all_servers() if s.enabled]
    if not servers:
        # Fallback: use global default xui (legacy single-server mode)
        try:
            xui.delete_client(inbound_id_fallback, uuid)
        except Exception as e:
            logger.warning("Ошибка удаления клиента (fallback) %s: %s", uuid, e)
        return

    for server in servers:
        try:
            ok = _server_delete_client(server, uuid)
            if ok:
                logger.info("expire-delete: %s removed from %s", uuid, server.name)
            else:
                logger.warning("expire-delete: failed to remove %s from %s", uuid, server.name)
        except Exception as e:
            logger.warning("expire-delete: error on %s for %s: %s", server.name, uuid, e)


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

    # ── Платный тариф — создаём платёж в YooKassa ────────────────────────
    if plan["price"] > 0:
        # Проверяем активный промокод на скидку
        promo_id, discount_percent = await get_user_discount(user_id)
        original_price = plan["price"]
        if discount_percent > 0:
            final_price = int(original_price * (100 - discount_percent) / 100)
            discount_text = f"🎟 Скидка: <b>-{discount_percent}%</b> (было {original_price} ₽)\n"
        else:
            final_price = original_price
            discount_text = ""

        # Создаём платёж
        from yookassa_payment import create_payment as yookassa_create_payment
        payment_result = yookassa_create_payment(
            amount=final_price,
            user_id=user_id,
            plan_key=plan_key,
            server_id=server_id or "",
            description=f"SWAGA VPN — {plan['name']}",
        )

        if not payment_result:
            await callback.message.answer(
                "❌ Ошибка при создании платежа. Попробуйте позже."
            )
            return

        # Сохраняем платёж в БД
        await db_create_payment(
            payment_id=payment_result["payment_id"],
            user_id=user_id,
            amount=final_price,
            plan_key=plan_key,
            server_id=server_id or "",
        )

        # Используем промокод (списываем) и очищаем скидку
        if promo_id:
            await use_promo_code(promo_id, user_id)
            await clear_user_discount(user_id)

        # Отправляем ссылку на оплату
        pay_url = payment_result["confirmation_url"]
        await callback.message.answer(
            f"💳 <b>Оплата подписки</b>\n\n"
            f"📦 Тариф: <b>{plan['name']}</b>\n"
            f"{discount_text}"
            f"💰 Сумма: <b>{final_price} ₽</b>\n\n"
            f"Нажмите кнопку ниже для оплаты.\n"
            f"После оплаты подписка активируется автоматически.",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("💳 Оплатить", url=pay_url)
            ),
        )
        await callback.answer()
        return  # Не создаём подписку — это сделает webhook

    # ── Проверяем, есть ли активная подписка (для продления) ─────────────
    existing_sub = await get_active_sub(user_id)
    now = datetime.utcnow()

    # Проверяем, выбрал ли пользователь другой сервер
    existing_server_id = existing_sub.get("server_id", "default") if existing_sub else None
    is_server_change = server_id and existing_server_id and server_id != existing_server_id

    # ── Если есть активная подписка на ТОМ ЖЕ сервере — продлеваем ─────────
    if existing_sub and existing_sub.get("vless_uuid") and not is_server_change:
        # Продление: добавляем дни к текущей дате окончания
        current_end = datetime.fromisoformat(existing_sub["end_date"])
        # Если подписка ещё не истекла — добавляем к ней, иначе от сейчас
        base_date = max(current_end, now)
        new_end = base_date + timedelta(days=plan["days"])

        # Обновляем дату окончания в БД
        await extend_subscription_to_date(user_id, new_end, plan=plan_key)

        # Используем существующий конфиг
        new_uuid = existing_sub["vless_uuid"]
        sub_id = existing_sub.get("xui_sub_id", "")
        actual_server_id = existing_sub.get("server_id", "default")
        email = existing_sub.get("xui_email", f"tg_{user_id}")

        # Определяем хост для ссылки
        from servers import server_manager
        if not server_manager.servers:
            server_manager.load_config()

        # Обновляем expiry в 3X-UI панели
        new_expiry_ms = int(new_end.timestamp() * 1000)
        if actual_server_id and actual_server_id != "default":
            server = server_manager.get_server(actual_server_id)
            vpn_host = server.host if server else VPN_HOST
            vpn_port = server.vpn_port if server else VPN_PORT
            # Обновляем на внешнем сервере
            if server:
                # WS серверы не хранят expiry в конфиге — срок действия контролируется только БД
                if getattr(server, "transport", "") != "ws":
                    try:
                        from xui_api import XUIAPI
                        server_xui = XUIAPI()
                        protocol = "https" if getattr(server, "xui_ssl", True) else "http"
                        server_xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
                        login_resp_ok = server_xui.login(server.xui_username, server.xui_password)
                        login_resp = type("_R", (), {"json": lambda self, **kw: {"success": login_resp_ok}})()
                        if login_resp.json().get("success"):
                            server_xui._logged_in = True
                            server_xui.update_client(
                                server.inbound_id, new_uuid, email,
                                sub_id=sub_id, expiry_time=new_expiry_ms,
                                flow=server.flow
                            )
                    except Exception as e:
                        logger.warning("Не удалось обновить expiry в панели: %s", e)
                # Обновляем expiry на всех остальных включённых серверах
                other_servers = [s for s in server_manager.get_all_servers() if s.enabled]
                if len(other_servers) > 1:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, _sync_client_to_other_servers,
                        new_uuid, email, sub_id, new_expiry_ms, actual_server_id, other_servers,
                        True,  # is_renewal
                    )
        else:
            vpn_host = VPN_HOST
            vpn_port = VPN_PORT
            # Обновляем на дефолтном сервере
            try:
                xui.update_client(INBOUND_ID, new_uuid, email, sub_id=sub_id, expiry_time=new_expiry_ms)
            except Exception as e:
                logger.warning("Не удалось обновить expiry в панели: %s", e)

        end = new_end
        expiry_ms = int(end.timestamp() * 1000)
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
            if server is None:
                server = server_manager.get_best_server()
        else:
            server = server_manager.get_best_server()

        # Используем дефолт из .env только если в конфиге вообще нет серверов
        use_default = server is None and not server_manager.servers

        if server is None and server_manager.servers:
            # Есть серверы в конфиге, но ни один не доступен — берём любой enabled
            enabled = [s for s in server_manager.servers.values() if s.enabled]
            server = enabled[0] if enabled else None
            use_default = server is None

        # Создание VPN-клиента
        new_uuid = generate_uuid()
        sub_id = generate_sub_id()
        email = f"tg_{user_id}_{int(now.timestamp())}"

        # Суммируем дни с существующей подпиской (даже при смене сервера)
        if existing_sub and existing_sub.get("end_date"):
            current_end = datetime.fromisoformat(existing_sub["end_date"])
            base_date = max(current_end, now)
        else:
            base_date = now
        end = base_date + timedelta(days=plan["days"])
        expiry_ms = int(end.timestamp() * 1000)  # 3X-UI использует миллисекунды

        try:
            if use_default:
                # Используем дефолтный xui из .env
                success = xui.add_client(
                    INBOUND_ID, new_uuid, email,
                    sub_id=sub_id, expiry_time=expiry_ms
                )
                vpn_host = VPN_HOST
                vpn_port = VPN_PORT
                actual_server_id = "default"
            else:
                # Используем выбранный сервер
                success = _server_add_client(
                    server, new_uuid, email,
                    sub_id=sub_id, expiry_ms=expiry_ms, flow=server.flow,
                )
                vpn_host = server.host
                vpn_port = server.vpn_port
                actual_server_id = server.id
                server.current_users += 1
                # Регистрируем UUID на всех остальных включённых серверах
                other_servers = [s for s in server_manager.get_all_servers() if s.enabled]
                if len(other_servers) > 1:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, _sync_client_to_other_servers,
                        new_uuid, email, sub_id, expiry_ms, actual_server_id, other_servers,
                        False,  # is_renewal
                    )

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
            xui_email=email,
        )

    # ── Реферальный бонус ─────────────────────────────────────────────────
    referral_bonus_text = ""
    referrer_id = await process_referral_bonus(user_id)
    if referrer_id:
        referrer_extended = await extend_subscription(referrer_id, REFERRAL_BONUS_DAYS)
        if referrer_extended:
            # Синхронизируем 3X-UI реферера: extend_subscription обновляет только БД
            referrer_sub = await get_active_sub(referrer_id)
            if referrer_sub and referrer_sub.get("vless_uuid"):
                referrer_expiry_ms = int(
                    datetime.fromisoformat(referrer_sub["end_date"]).timestamp() * 1000
                )
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, _sync_client_to_other_servers,
                    referrer_sub["vless_uuid"], referrer_sub.get("xui_email", ""),
                    referrer_sub.get("xui_sub_id", ""), referrer_expiry_ms,
                    "", [s for s in server_manager.get_all_servers() if s.enabled],
                    True,  # is_renewal
                )
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
        # Синхронизируем 3X-UI нового пользователя с учётом бонуса
        bonus_expiry_ms = int(end.timestamp() * 1000)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, _sync_client_to_other_servers,
            new_uuid, email, sub_id, bonus_expiry_ms, actual_server_id,
            [s for s in server_manager.get_all_servers() if s.enabled],
            True,  # is_renewal (updating expiry after referral bonus)
        )

    # ── Формирование ответа ───────────────────────────────────────────────
    # Получаем настройки сервера для VLESS ссылки
    srv = None
    if actual_server_id and actual_server_id != "default":
        srv = server_manager.get_server(actual_server_id)

    # Формируем название конфига с локацией
    location_names = {
        "DE": "Germany", "NL": "Netherlands", "EE": "Estonia", "US": "USA", "FI": "Finland",
        "FR": "France", "GB": "UK", "LV": "Latvia", "RU": "Russia", "KZ": "Kazakhstan",
    }
    if srv:
        loc_name = location_names.get(srv.location, srv.location or "")
        remark = f"SWAGA {loc_name}".strip() if loc_name else "SWAGA VPN"
    else:
        remark = "SWAGA VPN"

    # Используем настройки сервера или глобальные из .env
    if srv and (srv.reality_pbk or getattr(srv, "transport", "") == "ws"):
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
            remark=remark,
            flow=srv.flow,
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
            remark=remark,
        )

    # Добавляем информацию о сервере
    server_info = ""
    if srv:
        server_info = f"\n🌍 Сервер: <b>{srv.name}</b>"

    connect_base = SUB_BASE_URL.replace("/sub/", "/connect/")
    sub_url = f"{connect_base}{sub_id}"

    # ── Создаем ключи на ВСЕХ серверах ────────────────────────────────────
    # Используем ВСЕ enabled серверы, а не только healthy (чтобы не зависеть от health check)
    all_servers = [s for s in server_manager.servers.values() if s.enabled] if server_manager.servers else []
    all_configs = []
    logger.info(f"Создание ключей для пользователя {user_id} на {len(all_servers)} серверах")

    # Добавляем текущий сервер/конфиг
    location_flags = {
        "DE": "🇩🇪", "NL": "🇳🇱", "EE": "🇪🇪", "US": "🇺🇸", "FI": "🇫🇮",
        "FR": "🇫🇷", "GB": "🇬🇧", "LV": "🇱🇻", "RU": "🇷🇺", "KZ": "🇰🇿",
    }

    if srv:
        flag = location_flags.get(srv.location, "🌐")
        all_configs.append({
            "name": srv.name,
            "flag": flag,
            "link": vless_link,
            "server_id": actual_server_id
        })
    else:
        all_configs.append({
            "name": "SWAGA VPN",
            "flag": "🌐",
            "link": vless_link,
            "server_id": "default"
        })

    # Создаем ключи на остальных серверах
    for server in all_servers:
        # Пропускаем текущий сервер
        if server.id == actual_server_id:
            logger.debug(f"Пропуск сервера {server.name} (уже создан ключ)")
            continue

        try:
            logger.info(f"Попытка создать ключ на сервере {server.name} ({server.id})")
            ok = _server_add_client(server, new_uuid, email, sub_id=sub_id, expiry_ms=expiry_ms, flow=server.flow)
            if not ok:
                logger.warning(f"Не удалось добавить клиента на {server.name}, пропускаем")
                continue

            logger.info(f"✅ Клиент успешно добавлен на {server.name}")

            # Формируем VLESS ссылку для этого сервера
            loc_name = location_names.get(server.location, server.location or "")
            server_remark = f"SWAGA {loc_name}".strip() if loc_name else server.name

            if server.reality_pbk or getattr(server, "transport", "") == "ws":
                server_vless_link = build_vless_link(
                    uuid_str=new_uuid,
                    host=server.host,
                    port=server.vpn_port,
                    transport=server.transport or VPN_TRANSPORT,
                    path=server.transport_path or VPN_PATH,
                    camouflage_host=server.transport_host or VPN_CAMOUFLAGE_HOST,
                    xhttp_mode=server.xhttp_mode or VPN_XHTTP_MODE,
                    reality_pbk=server.reality_pbk,
                    reality_sid=server.reality_sid,
                    reality_fp=server.reality_fp or REALITY_FINGERPRINT,
                    reality_sni=server.reality_sni,
                    reality_spx=REALITY_SPIDERX,
                    remark=server_remark,
                    flow=server.flow,
                )
            else:
                server_vless_link = build_vless_link(
                    uuid_str=new_uuid,
                    host=server.host,
                    port=server.vpn_port,
                    transport=VPN_TRANSPORT,
                    path=VPN_PATH,
                    camouflage_host=VPN_CAMOUFLAGE_HOST,
                    xhttp_mode=VPN_XHTTP_MODE,
                    reality_pbk=REALITY_PUBLIC_KEY,
                    reality_sid=REALITY_SHORT_ID,
                    reality_fp=REALITY_FINGERPRINT,
                    reality_sni=REALITY_SNI,
                    reality_spx=REALITY_SPIDERX,
                    remark=server_remark,
                    flow=server.flow,
                )

            flag = location_flags.get(server.location, "🌐")
            all_configs.append({
                "name": server.name,
                "flag": flag,
                "link": server_vless_link,
                "server_id": server.id
            })

            logger.info(f"✅ Создан ключ на сервере {server.name} для пользователя {user_id}")

        except Exception as e:
            logger.error(f"❌ Не удалось создать ключ на сервере {server.name} ({server.id}): {e}", exc_info=True)
            # Продолжаем, даже если не удалось создать на этом сервере

    # ── Формируем сообщение со ВСЕМИ серверами ────────────────────────────
    # Разный текст для продления и новой подписки
    if is_extension:
        action_text = "✅ <b>Подписка продлена!</b>"
    else:
        action_text = "✅ <b>Подписка активирована!</b>"

    # Формируем список всех конфигов
    configs_text = "\n\n".join([
        f"{cfg['flag']} <b>{cfg['name']}</b>\n<code>{cfg['link']}</code>"
        for cfg in all_configs
    ])

    days_left = max((end - datetime.utcnow()).days, 0)

    text = (
        f"{action_text}\n\n"
        f"📦 Тариф: <b>{plan['name']}</b>\n"
        f"📅 Действует до: <b>{format_date(end)}</b>\n"
        f"⏱ Осталось: <b>{days_left} дн.</b>\n"
        f"🌍 Доступно серверов: <b>{len(all_configs)}</b>"
        f"{referral_bonus_text}\n\n"
        f"{configs_text}\n\n"
        f"<i>💡 Выбери любой сервер — все работают одновременно!</i>\n"
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
                # Удалить клиента из 3X-UI на всех серверах
                if sub["vless_uuid"]:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, _delete_client_from_all_servers,
                        sub["vless_uuid"], INBOUND_ID,
                    )

                # Деактивировать подписку
                await deactivate_subscription(sub["sub_id"])

                # Уведомить пользователя (только реальных Telegram-пользователей)
                uid = sub["user_id"]
                if 0 < uid < 9_000_000_000:
                    try:
                        await bot.send_message(
                            uid,
                            "😔 Ваша подписка истекла.\n"
                            "Нажмите «Получить доступ», чтобы выбрать новый тариф.",
                            parse_mode=types.ParseMode.HTML,
                        )
                    except Exception as e:
                        logger.warning("Не удалось уведомить user=%s: %s", uid, e)

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

            def _is_telegram_user(uid: int) -> bool:
                # Пропускаем web-пользователей (отрицательные ID) и giveaway-ключи (> 9млрд)
                return 0 < uid < 9_000_000_000

            # Напоминания за 3 дня (72 часа)
            subs_3d = await get_subs_for_reminder(hours=72, reminder_code="3d")
            for sub in subs_3d:
                if not _is_telegram_user(sub["user_id"]):
                    await mark_reminder_sent(sub["sub_id"], "3d")
                    continue
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
                if not _is_telegram_user(sub["user_id"]):
                    await mark_reminder_sent(sub["sub_id"], "1d")
                    continue
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
                if not _is_telegram_user(sub["user_id"]):
                    await mark_reminder_sent(sub["sub_id"], "3h")
                    continue
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


async def _migrate_user_to_server(sub: dict, new_server) -> bool:
    """
    Мигрировать пользователя на новый сервер.
    Создаёт нового клиента на новом сервере и обновляет подписку.
    """
    try:
        user_id = sub["user_id"]
        old_uuid = sub["vless_uuid"]
        end_date = datetime.fromisoformat(sub["end_date"])
        expiry_ms = int(end_date.timestamp() * 1000)

        # Генерируем новые данные
        new_uuid = generate_uuid()
        new_sub_id = generate_sub_id()
        new_email = f"tg_{user_id}_{int(datetime.utcnow().timestamp())}"

        # Создаём клиента на новом сервере
        success = _server_add_client(
            new_server, new_uuid, new_email,
            sub_id=new_sub_id, expiry_ms=expiry_ms, flow=new_server.flow,
        )
        if not success:
            logger.error("Не удалось создать клиента на сервере %s", new_server.name)
            return False

        # Сохраняем историю миграции (для последующей безопасной очистки)
        await save_migration(
            sub_id=sub["sub_id"],
            user_id=user_id,
            old_server_id=sub["server_id"],
            old_uuid=old_uuid,
            old_email=sub.get("xui_email", ""),
            new_server_id=new_server.id,
            new_uuid=new_uuid,
        )

        # Обновляем подписку в БД
        await update_sub_server(sub["sub_id"], new_server.id, new_uuid, new_email, new_sub_id)

        # Формируем новую ссылку
        vless_link = build_vless_link(
            uuid_str=new_uuid,
            host=new_server.host,
            port=new_server.vpn_port,
            transport=new_server.transport or VPN_TRANSPORT,
            path=new_server.transport_path or VPN_PATH,
            camouflage_host=new_server.transport_host or VPN_CAMOUFLAGE_HOST,
            xhttp_mode=new_server.xhttp_mode or VPN_XHTTP_MODE,
            reality_pbk=new_server.reality_pbk,
            reality_sid=new_server.reality_sid,
            reality_fp=new_server.reality_fp or REALITY_FINGERPRINT,
            reality_sni=new_server.reality_sni,
            reality_spx=REALITY_SPIDERX,
        )

        # Уведомляем пользователя
        sub_url = f"{SUB_BASE_URL}{new_sub_id}"
        try:
            await bot.send_message(
                user_id,
                f"🔄 <b>Автопереключение сервера</b>\n\n"
                f"Ваш предыдущий сервер временно недоступен.\n"
                f"Вы переключены на: <b>{new_server.name}</b>\n\n"
                f"🔑 Новый конфиг:\n<code>{vless_link}</code>\n\n"
                f"📲 Или используйте быстрое подключение:",
                parse_mode="HTML",
                reply_markup=quick_connect_kb(sub_url),
            )
        except Exception as e:
            logger.warning("Не удалось уведомить user=%s о failover: %s", user_id, e)

        logger.info("Пользователь %s мигрирован на сервер %s", user_id, new_server.name)
        return True

    except Exception as e:
        logger.error("Ошибка миграции пользователя %s: %s", sub.get("user_id"), e)
        return False


async def _cleanup_old_clients(server) -> int:
    """
    Удалить старых клиентов с восстановленного сервера.
    Удаляет ТОЛЬКО клиентов из таблицы migration_history.
    Возвращает количество удалённых.
    """
    pending = await get_pending_cleanups(server.id)
    if not pending:
        return 0

    cleaned = 0
    for migration in pending:
        try:
            success = _server_delete_client(server, migration["old_uuid"])
            if success:
                await mark_cleanup_done(migration["id"])
                cleaned += 1
                logger.info("Очищен старый клиент %s с сервера %s", migration["old_email"], server.name)
            else:
                # Клиент уже удалён или не существует — тоже отмечаем как очищено
                await mark_cleanup_done(migration["id"])
                cleaned += 1
        except Exception as e:
            logger.warning("Ошибка удаления клиента %s: %s", migration["old_uuid"], e)

    return cleaned


async def _scheduler_server_failover() -> None:
    """
    Проверка серверов каждые 2 минуты.
    При падении сервера — переключение пользователей на здоровый.
    При восстановлении — очистка старых клиентов.
    """
    await asyncio.sleep(120)  # Ждём 2 минуты при старте

    # Отслеживаем количество последовательных ошибок для каждого сервера
    server_fail_count: dict[str, int] = {}
    # Отслеживаем серверы, которые были "упавшими" (для очистки при восстановлении)
    servers_was_down: set[str] = set()
    FAIL_THRESHOLD = 3  # Сколько ошибок подряд = сервер упал

    while True:
        try:
            from servers import server_manager
            if not server_manager.servers:
                server_manager.load_config()

            # Проверяем все серверы
            health_results = await server_manager.check_all_servers()

            for server_id, is_healthy in health_results.items():
                server = server_manager.get_server(server_id)
                if not server or not server.enabled:
                    continue

                if is_healthy:
                    # Сбрасываем счётчик ошибок
                    prev_fail_count = server_fail_count.get(server_id, 0)
                    server_fail_count[server_id] = 0

                    # Если сервер восстановился после падения — очищаем старых клиентов
                    if server_id in servers_was_down:
                        servers_was_down.remove(server_id)
                        cleaned = await _cleanup_old_clients(server)
                        if cleaned > 0:
                            await notify_admins(
                                f"🧹 <b>Очистка завершена</b>\n\n"
                                f"Сервер <b>{server.name}</b> восстановлен.\n"
                                f"Удалено старых клиентов: {cleaned}"
                            )
                            logger.info(
                                "Сервер %s восстановлен, очищено %d старых клиентов",
                                server.name, cleaned
                            )
                else:
                    # Увеличиваем счётчик ошибок
                    server_fail_count[server_id] = server_fail_count.get(server_id, 0) + 1
                    fail_count = server_fail_count[server_id]

                    logger.warning(
                        "Сервер %s недоступен (%d/%d)",
                        server.name, fail_count, FAIL_THRESHOLD
                    )

                    # Если порог достигнут — уведомляем админа (без автомиграции)
                    if fail_count == FAIL_THRESHOLD:
                        subs = await get_subs_by_server(server_id)
                        await notify_admins(
                            f"🚨 <b>Сервер упал!</b>\n\n"
                            f"Сервер: <b>{server.name}</b> (<code>{server_id}</code>)\n"
                            f"Активных подписчиков: <b>{len(subs)}</b>\n\n"
                            f"Автомиграция отключена. Проверь сервер вручную."
                        )
                        # Запоминаем, что этот сервер требует очистки при восстановлении
                        servers_was_down.add(server_id)

        except Exception as e:
            logger.error("Ошибка в scheduler_failover: %s", e)

        # Проверяем каждые 2 минуты
        await asyncio.sleep(120)


# ══════════════════════════════════════════════════════════════════════════════
#  YOOKASSA PAYMENT CALLBACK
# ══════════════════════════════════════════════════════════════════════════════

async def handle_payment_success(
    user_id: int,
    plan_key: str,
    server_id: str,
    amount: float,
    payment_id: str = "",
    paid_at: str = "",
) -> None:
    """
    Callback для обработки успешного платежа от YooKassa.

    begin_fulfillment (BEGIN IMMEDIATE) atomically: records payment as succeeded,
    stores target_end_date, updates/creates the subscription, marks fulfillment='pending'.
    Network calls (3X-UI panel sync) happen AFTER the transaction commits.
    On 'sync_pending' (process crashed after commit but before sync), network calls
    are retried idempotently. On 'already_fulfilled', the call is a no-op.
    """
    logger.info(
        "Payment success: user=%s, plan=%s, server=%s, amount=%s, payment_id=%s",
        user_id, plan_key, server_id, amount, payment_id
    )

    plan = PLANS.get(plan_key)
    if not plan:
        logger.error("Unknown plan: %s", plan_key)
        return

    # Загружаем серверы
    from servers import server_manager
    if not server_manager.servers:
        server_manager.load_config()

    now = datetime.utcnow()

    # Проверяем существующую подписку
    existing_sub = await get_active_sub(user_id)
    existing_server_id = existing_sub.get("server_id", "default") if existing_sub else None
    is_server_change = server_id and existing_server_id and server_id != existing_server_id

    # ── Если есть активная подписка на ТОМ ЖЕ сервере — продлеваем ─────────
    if existing_sub and existing_sub.get("vless_uuid") and not is_server_change:
        # Atomic: payment marked succeeded+pending, subscription end_date updated — one transaction.
        # Network calls happen only after this returns.
        result_code, _target_end, sub_info = await begin_fulfillment(
            payment_id, user_id, plan_key, plan["days"],
            paid_at or now.isoformat(),
            is_renewal=True,
            existing_uuid=existing_sub["vless_uuid"],
        )
        if result_code == "already_fulfilled":
            logger.info("Payment %s already fulfilled, skipping", payment_id)
            return
        if result_code == "not_found":
            logger.error("Payment %s not found in DB during renewal", payment_id)
            return
        # 'first' or 'sync_pending': do/redo the VPN panel network calls
        new_uuid = sub_info["uuid"]
        sub_id = sub_info["xui_sub_id"]
        actual_server_id = sub_info["server_id"]
        email = sub_info["email"]
        end = datetime.fromisoformat(sub_info["end_date"])
        new_expiry_ms = sub_info["expiry_ms"]
        if actual_server_id and actual_server_id != "default":
            server = server_manager.get_server(actual_server_id)
            vpn_host = server.host if server else VPN_HOST
            vpn_port = server.vpn_port if server else VPN_PORT
            # Обновляем на внешнем сервере
            if server:
                # WS серверы не хранят expiry в конфиге — срок действия контролируется только БД
                if getattr(server, "transport", "") != "ws":
                    try:
                        from xui_api import XUIAPI
                        server_xui = XUIAPI()
                        protocol = "https" if getattr(server, "xui_ssl", True) else "http"
                        server_xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
                        login_resp_ok = server_xui.login(server.xui_username, server.xui_password)
                        login_resp = type("_R", (), {"json": lambda self, **kw: {"success": login_resp_ok}})()
                        if login_resp.json().get("success"):
                            server_xui._logged_in = True
                            server_xui.update_client(
                                server.inbound_id, new_uuid, email,
                                sub_id=sub_id, expiry_time=new_expiry_ms,
                                flow=server.flow
                            )
                    except Exception as e:
                        logger.warning("Не удалось обновить expiry в панели: %s", e)
                # Обновляем expiry на всех остальных включённых серверах
                other_servers = [s for s in server_manager.get_all_servers() if s.enabled]
                if len(other_servers) > 1:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, _sync_client_to_other_servers,
                        new_uuid, email, sub_id, new_expiry_ms, actual_server_id, other_servers,
                        True,  # is_renewal
                    )
        else:
            server = None
            vpn_host = VPN_HOST
            vpn_port = VPN_PORT
            # Обновляем на дефолтном сервере
            try:
                xui.update_client(INBOUND_ID, new_uuid, email, sub_id=sub_id, expiry_time=new_expiry_ms)
            except Exception as e:
                logger.warning("Не удалось обновить expiry в панели: %s", e)

        if payment_id:
            await mark_payment_fulfilled(payment_id)
        is_extension = True
        logger.info("Extending subscription for user %s to %s", user_id, end)

    else:
        # ── Новая подписка — создаём VPN-клиент ────────────────────────────
        is_extension = False

        # Выбираем сервер
        if server_id:
            server = server_manager.get_server(server_id)
            if server is None:
                server = server_manager.get_best_server()
        else:
            server = server_manager.get_best_server()

        # Используем дефолт из .env только если в конфиге вообще нет серверов
        use_default = server is None and not server_manager.servers

        if server is None and server_manager.servers:
            enabled = [s for s in server_manager.servers.values() if s.enabled]
            server = enabled[0] if enabled else None
            use_default = server is None

        # Pre-generate VPN identity BEFORE the atomic DB transaction
        new_uuid = generate_uuid()
        sub_id = generate_sub_id()
        email = f"tg_{user_id}_{int(now.timestamp())}"
        if server and not use_default:
            actual_server_id = server.id
        else:
            actual_server_id = "default"

        # Atomic: payment marked succeeded+pending, old subs deactivated, new sub inserted.
        # Network calls (add to panel) happen only after commit.
        result_code, _target_end, sub_info = await begin_fulfillment(
            payment_id, user_id, plan_key, plan["days"],
            paid_at or now.isoformat(),
            is_renewal=False,
            new_uuid=new_uuid,
            new_sub_id=sub_id,
            new_email=email,
            new_server_id=actual_server_id,
            new_start_date=now.isoformat(),
        )
        if result_code == "already_fulfilled":
            logger.info("Payment %s already fulfilled, skipping", payment_id)
            return
        if result_code == "not_found":
            logger.error("Payment %s not found in DB during new-sub creation", payment_id)
            return
        # 'sync_pending': process crashed after commit — use the stored sub identity
        if result_code == "sync_pending":
            new_uuid = sub_info["uuid"] or new_uuid
            sub_id = sub_info["xui_sub_id"] or sub_id
            email = sub_info["email"] or email
            actual_server_id = sub_info["server_id"] or actual_server_id
            if actual_server_id and actual_server_id != "default":
                server = server_manager.get_server(actual_server_id) or server

        end = datetime.fromisoformat(sub_info["end_date"])
        expiry_ms = sub_info["expiry_ms"]

        try:
            if use_default or actual_server_id == "default":
                success = xui.add_or_update_client(
                    INBOUND_ID, new_uuid, email,
                    sub_id=sub_id, expiry_time=expiry_ms
                ) if hasattr(xui, "add_or_update_client") else xui.add_client(
                    INBOUND_ID, new_uuid, email,
                    sub_id=sub_id, expiry_time=expiry_ms
                )
                vpn_host = VPN_HOST
                vpn_port = VPN_PORT
            else:
                success = _server_add_client(
                    server, new_uuid, email,
                    sub_id=sub_id, expiry_ms=expiry_ms, flow=server.flow,
                )
                vpn_host = server.host
                vpn_port = server.vpn_port
                if result_code == "first":
                    server.current_users += 1
                # Sync to all other enabled servers
                other_servers = [s for s in server_manager.get_all_servers() if s.enabled]
                if len(other_servers) > 1:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, _sync_client_to_other_servers,
                        new_uuid, email, sub_id, expiry_ms, actual_server_id, other_servers,
                        False,  # is_renewal
                    )

            if not success:
                raise RuntimeError("3X-UI add_client вернул False")

        except Exception as e:
            logger.error("Ошибка создания VPN-клиента после оплаты: %s", e)
            await notify_error("Создание VPN-клиента (оплата)", e)
            try:
                await bot.send_message(
                    user_id,
                    "❌ Оплата прошла, но не удалось создать VPN-конфиг.\n"
                    "Обратитесь в поддержку — мы всё исправим!",
                )
            except Exception:
                pass
            # Subscription IS already in DB (begin_fulfillment committed). Startup sync
            # will retry the panel call on next restart. Do NOT return without mark_fulfilled —
            # this leaves fulfillment_status='pending' so startup sync picks it up.
            if payment_id:
                logger.warning(
                    "Panel sync failed for payment %s; startup sync will retry", payment_id
                )
            return

        if payment_id:
            await mark_payment_fulfilled(payment_id)

    # Реферальный бонус
    referral_bonus_text = ""
    referrer_id = await process_referral_bonus(user_id)
    if referrer_id:
        referrer_extended = await extend_subscription(referrer_id, REFERRAL_BONUS_DAYS)
        if referrer_extended:
            # Синхронизируем 3X-UI реферера: extend_subscription обновляет только БД
            referrer_sub = await get_active_sub(referrer_id)
            if referrer_sub and referrer_sub.get("vless_uuid"):
                referrer_expiry_ms = int(
                    datetime.fromisoformat(referrer_sub["end_date"]).timestamp() * 1000
                )
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, _sync_client_to_other_servers,
                    referrer_sub["vless_uuid"], referrer_sub.get("xui_email", ""),
                    referrer_sub.get("xui_sub_id", ""), referrer_expiry_ms,
                    "", [s for s in server_manager.get_all_servers() if s.enabled],
                    True,  # is_renewal
                )
            try:
                await bot.send_message(
                    referrer_id,
                    f"🎉 <b>Реферальный бонус!</b>\n\n"
                    f"Ваш друг оплатил подписку.\n"
                    f"Вам добавлено <b>+{REFERRAL_BONUS_DAYS} дней</b>!",
                    parse_mode=types.ParseMode.HTML,
                )
            except Exception:
                pass
        await extend_subscription(user_id, REFERRAL_BONUS_DAYS)
        referral_bonus_text = f"\n🎁 <b>Реферальный бонус:</b> +{REFERRAL_BONUS_DAYS} дней!"
        end = end + timedelta(days=REFERRAL_BONUS_DAYS)
        # Синхронизируем 3X-UI нового пользователя с учётом бонуса
        bonus_expiry_ms = int(end.timestamp() * 1000)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, _sync_client_to_other_servers,
            new_uuid, email, sub_id, bonus_expiry_ms, actual_server_id,
            [s for s in server_manager.get_all_servers() if s.enabled],
            True,  # is_renewal (updating expiry after referral bonus)
        )

    # Формируем VLESS ссылку
    srv = server_manager.get_server(actual_server_id) if actual_server_id != "default" else None

    location_names = {
        "DE": "Germany", "NL": "Netherlands", "EE": "Estonia", "US": "USA", "FI": "Finland",
        "FR": "France", "GB": "UK", "LV": "Latvia", "RU": "Russia", "KZ": "Kazakhstan",
    }
    if srv:
        loc_name = location_names.get(srv.location, srv.location or "")
        remark = f"SWAGA {loc_name}".strip() if loc_name else "SWAGA VPN"
    else:
        remark = "SWAGA VPN"

    if srv and (srv.reality_pbk or getattr(srv, "transport", "") == "ws"):
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
            remark=remark,
            flow=srv.flow,
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
            remark=remark,
        )

    # Информация о сервере
    server_info = ""
    if srv:
        server_info = f"\n🌍 Сервер: <b>{srv.name}</b>"

    connect_base = SUB_BASE_URL.replace("/sub/", "/connect/")
    sub_url = f"{connect_base}{sub_id}"

    # Уведомляем пользователя (только Telegram-юзеры, у web-юзеров user_id < 0)
    if user_id > 0:
        try:
            text = (
                "✅ <b>Оплата прошла успешно!</b>\n\n"
                f"📦 Тариф: <b>{plan['name']}</b>\n"
                f"💰 Сумма: <b>{amount:.0f} ₽</b>\n"
                f"📅 Действует до: <b>{format_date(end)}</b>"
                f"{server_info}"
                f"{referral_bonus_text}\n\n"
                f"🔑 <b>Ваш конфиг:</b>\n"
                f"<code>{vless_link}</code>\n\n"
                "📲 Нажмите кнопку для подключения."
            )
            await bot.send_message(
                user_id,
                text,
                reply_markup=quick_connect_kb(sub_url),
                parse_mode=types.ParseMode.HTML,
            )
        except Exception as e:
            logger.error("Не удалось уведомить пользователя %s: %s", user_id, e)
    else:
        logger.info("Web-пользователь %s оплатил подписку — Telegram-уведомление не отправляется", user_id)

    # Уведомление админам
    try:
        user = await get_user(user_id)
        if user_id > 0:
            username = user.get("username") if user else None
            user_link = f"@{username}" if username else f"TG ID: {user_id}"
        else:
            user_link = f"🌐 Web ID: {abs(user_id)}"
        await notify_admins(
            f"💰 <b>Новая оплата!</b>\n\n"
            f"👤 Пользователь: {user_link}\n"
            f"📦 Тариф: <b>{plan['name']}</b>\n"
            f"💵 Сумма: <b>{amount:.0f} ₽</b>\n"
            f"📅 До: <b>{format_date(end)}</b>\n"
            f"🌍 Сервер: <b>{actual_server_id}</b>"
        )
    except Exception as e:
        logger.error("Ошибка уведомления админов: %s", e)


async def _startup_sync_pending_fulfillments() -> None:
    """
    On startup, find payments with fulfillment_status='pending' and retry the VPN
    panel sync. These are payments where the DB was committed (subscription is valid)
    but the process crashed before syncing the panel.

    Uses the no-shrink invariant: sync expiry = max(target_end_date, current sub.end_date).
    Never re-extends the subscription — only pushes the already-committed end_date to panels.
    """
    from servers import server_manager
    if not server_manager.servers:
        server_manager.load_config()

    pending = await get_pending_fulfillments()
    if not pending:
        return

    logger.info("STARTUP SYNC: %d pending fulfillment(s) found — retrying panel sync", len(pending))

    for pmt in pending:
        payment_id = pmt["payment_id"]
        user_id = pmt["user_id"]
        uuid = pmt.get("vless_uuid")
        email = pmt.get("xui_email", "")
        xui_sub_id = pmt.get("xui_sub_id", "")
        srv_id = pmt.get("server_id", "")
        expiry_ms = pmt.get("expiry_ms", 0)
        sync_end = pmt.get("sync_end_date", "")

        if not uuid:
            logger.error(
                "STARTUP SYNC: payment %s pending but no vless_uuid in sub for user %s — "
                "manual review needed",
                payment_id, user_id,
            )
            continue

        logger.info(
            "STARTUP SYNC: retrying panel sync for payment %s user %s server %s expiry %s",
            payment_id, user_id, srv_id, sync_end,
        )
        try:
            if srv_id and srv_id != "default":
                if srv_id in _PROTECTED_SERVER_IDS:
                    logger.warning(
                        "STARTUP SYNC: payment %s — primary server %s is protected, "
                        "skipping sync (subscription remains valid in DB)",
                        payment_id, srv_id,
                    )
                    continue
                server = server_manager.get_server(srv_id)
                if server:
                    ok = _server_add_client(
                        server, uuid, email,
                        sub_id=xui_sub_id, expiry_ms=expiry_ms, flow=getattr(server, "flow", ""),
                    )
                    if ok:
                        all_servers = [s for s in server_manager.get_all_servers() if s.enabled]
                        if len(all_servers) > 1:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(
                                None, _sync_client_to_other_servers,
                                uuid, email, xui_sub_id, expiry_ms, srv_id, all_servers,
                                True,  # is_renewal (updating expiry)
                            )
                    else:
                        logger.error("STARTUP SYNC: panel add/update failed for payment %s", payment_id)
                        continue
                else:
                    logger.error("STARTUP SYNC: server %s not found for payment %s", srv_id, payment_id)
                    continue
            await mark_payment_fulfilled(payment_id)
            logger.info("STARTUP SYNC: payment %s marked fulfilled", payment_id)
        except Exception as e:
            logger.error("STARTUP SYNC: error for payment %s: %s", payment_id, e)


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP / SHUTDOWN
# ══════════════════════════════════════════════════════════════════════════════

async def on_startup(_dp: Dispatcher) -> None:
    """Инициализация при запуске бота."""
    await init_db()
    await init_promo_table()
    await init_migration_table()
    logger.info("База данных инициализирована")

    # Загрузка конфигурации серверов
    from servers import server_manager
    if server_manager.load_config():
        logger.info("Конфигурация серверов загружена: %d серверов", len(server_manager.servers))
        for srv_id, srv in server_manager.servers.items():
            status = "✅" if srv.enabled else "❌"
            logger.info("  %s %s (%s)", status, srv.name, srv_id)

        # Запускаем health check для автоматической проверки серверов
        server_manager.start_health_checks()
        logger.info("Health check запущен для автоматической проверки серверов")
    else:
        logger.error("❌ Не удалось загрузить конфигурацию серверов!")

    # Установка callback для обработки успешных платежей
    set_payment_callback(handle_payment_success)
    logger.info("YooKassa callback установлен")

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

    # Retry pending fulfillments from any crash before last restart
    try:
        await _startup_sync_pending_fulfillments()
    except Exception as e:
        logger.error("Startup sync error: %s", e)

    # Запуск фоновых задач
    asyncio.create_task(_scheduler_expiration_check())
    asyncio.create_task(_scheduler_reminders())
    asyncio.create_task(_scheduler_backup())
    asyncio.create_task(_scheduler_server_failover())
    logger.info("Фоновые задачи запущены (включая failover)")

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
