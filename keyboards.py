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
    """Главное меню бота — четыре кнопки, каждая на отдельной строке."""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Получить доступ"))
    kb.add(KeyboardButton("Инструкция"))
    kb.add(KeyboardButton("Личный кабинет"))
    kb.add(KeyboardButton("Поддержка"))
    return kb


# ── Inline-клавиатуры ─────────────────────────────────────────────────────────

def plans_kb(trial_used: bool) -> InlineKeyboardMarkup:
    """
    Выбор тарифного плана.
    Скрывает пробный период, если он уже использован.
    """
    kb = InlineKeyboardMarkup(row_width=1)
    if not trial_used:
        trial = PLANS["trial"]
        kb.add(
            InlineKeyboardButton(
                text=f"🎁 {trial['name']} — {trial['days']} дн. (бесплатно)",
                callback_data="plan_trial",
            )
        )
    for key in ("1m", "3m", "1y"):
        plan = PLANS[key]
        kb.add(
            InlineKeyboardButton(
                text=f"{plan['name']} — {plan['price']} ₽",
                callback_data=f"plan_{key}",
            )
        )
    return kb


def instruction_kb() -> InlineKeyboardMarkup:
    """Клавиатура на экране инструкции."""
    kb = InlineKeyboardMarkup(row_width=1)
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


def quick_connect_kb() -> InlineKeyboardMarkup:
    """Кнопки после выдачи конфига: скачать приложение + поддержка."""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(
            text="📲 Скачать V2RayTun (Android)",
            url="https://play.google.com/store/apps/details?id=com.v2raytun.android",
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="📲 Скачать V2RayTun (iOS)",
            url="https://apps.apple.com/app/v2raytun/id6476628951",
        )
    )
    kb.add(
        InlineKeyboardButton(
            text="Техподдержка",
            url=SUPPORT_URL,
        )
    )
    return kb


def cabinet_kb() -> InlineKeyboardMarkup:
    """Клавиатура личного кабинета (продление подписки)."""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(
            text="Продлить подписку",
            callback_data="get_access",
        )
    )
    return kb
