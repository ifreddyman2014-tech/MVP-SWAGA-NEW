"""
Клавиатуры Telegram-бота (Reply + Inline).
"""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import PLANS, SUPPORT_URL


# ── Reply-клавиатуры ──────────────────────────────────────────────────────────

def main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню бота — пять кнопок, каждая на отдельной строке."""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Получить доступ"))
    kb.add(KeyboardButton("Инструкция"))
    kb.add(KeyboardButton("Личный кабинет"))
    kb.add(KeyboardButton("Правила"))
    kb.add(KeyboardButton("Поддержка"))
    return kb


# ── Inline-клавиатуры ─────────────────────────────────────────────────────────

def plans_kb(
    trial_used: bool,
    discount_percent: int = 0,
    renew_source: str | None = None,
) -> InlineKeyboardMarkup:
    """
    Выбор тарифного плана.
    Скрывает пробный период, если он уже использован.
    discount_percent: скидка в процентах (0-99)
    renew_source: если задан, кодируется в callback_data как plan_{key}:{renew_source}
                  чтобы платёж получил атрибуцию источника обновления.
    """
    kb = InlineKeyboardMarkup(row_width=1)

    def _cb(key: str) -> str:
        return f"plan_{key}:{renew_source}" if renew_source else f"plan_{key}"

    if not trial_used:
        trial = PLANS["trial"]
        kb.add(
            InlineKeyboardButton(
                text=f"🎁 {trial['name']} — {trial['days']} дн. (бесплатно)",
                callback_data=_cb("trial"),
            )
        )
    for key in ("1m", "3m", "1y"):
        plan = PLANS[key]
        if discount_percent > 0:
            original = plan["price"]
            discounted = int(original * (100 - discount_percent) / 100)
            btn_text = f"{plan['name']} — {original}→{discounted} ₽ 🔥"
        else:
            btn_text = f"{plan['name']} — {plan['price']} ₽"
        kb.add(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=_cb(key),
            )
        )
    # Кнопка ввода промокода (скрываем если уже есть скидка)
    if discount_percent == 0:
        kb.add(
            InlineKeyboardButton(
                text="🎟 Ввести промокод",
                callback_data="enter_promo",
            )
        )
    return kb


def instruction_kb() -> InlineKeyboardMarkup:
    """Клавиатура на экране инструкции."""
    kb = InlineKeyboardMarkup(row_width=2)
    # Мобильные приложения
    kb.add(
        InlineKeyboardButton(
            text="📱 iOS — Happ Plus",
            url="https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
        ),
        InlineKeyboardButton(
            text="📱 Android — Hiddify",
            url="https://play.google.com/store/apps/details?id=app.hiddify.com",
        ),
    )
    kb.add(
        InlineKeyboardButton(
            text="📱 iOS / Android — Karing",
            url="https://karing.app/en/download/",
        ),
    )
    # Десктопные приложения
    kb.add(
        InlineKeyboardButton(
            text="💻 Windows",
            url="https://github.com/2dust/v2rayN/releases",
        ),
        InlineKeyboardButton(
            text="💻 macOS",
            url="https://github.com/yanue/V2rayU/releases",
        ),
    )
    kb.add(
        InlineKeyboardButton(
            text="Получить доступ",
            callback_data="get_access",
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="Техподдержка",
            url=SUPPORT_URL,
        )
    )
    return kb


def quick_connect_kb(sub_url: str) -> InlineKeyboardMarkup:
    """Кнопки после выдачи конфига: быстрое подключение + рефералы + поддержка."""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(
            text="⚡ Быстрое подключение",
            url=sub_url,
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="🔄 Обновить доступ",
            callback_data="update_access",
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="💳 Продлить подписку",
            callback_data="renew_cabinet",
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="👥 Рефералы",
            callback_data="referrals",
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="Техподдержка",
            url=SUPPORT_URL,
        )
    )
    return kb


def payment_success_kb(sub_url: str) -> InlineKeyboardMarkup:
    """Keyboard after successful payment: connect CTA + config + support."""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="⚡ Подключить VPN", url=sub_url))
    kb.add(InlineKeyboardButton(text="🔑 Показать конфигурацию", callback_data="show_config"))
    kb.add(InlineKeyboardButton(text="📱 Инструкция", callback_data="show_instruction"))
    kb.add(InlineKeyboardButton(text="👤 Личный кабинет", callback_data="update_access"))
    kb.add(InlineKeyboardButton(text="🆘 Поддержка", url=SUPPORT_URL))
    return kb


def renew_cta_kb(source: str = "") -> InlineKeyboardMarkup:
    """Single-button keyboard with [Продлить подписку].

    source: attribution tag appended to callback_data (e.g. '72h', '24h', '3h',
            'expired', 'cabinet'). Empty string → generic 'get_access' callback.
    """
    kb = InlineKeyboardMarkup(row_width=1)
    callback = f"renew_{source}" if source else "get_access"
    kb.add(
        InlineKeyboardButton(
            text="💳 Продлить подписку",
            callback_data=callback,
        )
    )
    return kb


def cabinet_kb() -> InlineKeyboardMarkup:
    """Клавиатура личного кабинета (продление подписки + рефералы)."""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(
            text="🔄 Обновить доступ",
            callback_data="update_access",
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="👥 Рефералы",
            callback_data="referrals",
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="Продлить подписку",
            callback_data="get_access",
        )
    )
    return kb


def servers_kb(servers: list, plan_key: str) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора сервера.
    servers: список объектов VPNServer
    plan_key: ключ тарифа для callback_data
    """
    kb = InlineKeyboardMarkup(row_width=1)

    # Флаги стран
    flags = {
        "DE": "🇩🇪",
        "NL": "🇳🇱",
        "EE": "🇪🇪",
        "US": "🇺🇸",
        "FI": "🇫🇮",
        "FR": "🇫🇷",
        "GB": "🇬🇧",
        "RU": "🇷🇺",
        "KZ": "🇰🇿",
    }

    for srv in servers:
        if not srv.enabled or not srv.is_healthy:
            continue

        flag = flags.get(srv.location, "🌐")
        load = int(srv.current_users / max(srv.max_users, 1) * 100)

        # Индикатор загрузки
        if load < 50:
            load_icon = "🟢"
        elif load < 80:
            load_icon = "🟡"
        else:
            load_icon = "🔴"

        kb.add(
            InlineKeyboardButton(
                text=f"{flag} {srv.name} {load_icon}",
                callback_data=f"server_{srv.id}_{plan_key}",
            )
        )

    # Кнопка "Автовыбор" — система сама выберет лучший сервер
    kb.add(
        InlineKeyboardButton(
            text="⚡ Автовыбор (рекомендуется)",
            callback_data=f"server_auto_{plan_key}",
        )
    )

    return kb

