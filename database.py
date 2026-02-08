"""
Асинхронная работа с SQLite через aiosqlite.
Таблицы: users, subscriptions, transactions.
"""

import aiosqlite
from datetime import datetime, timedelta

from config import DB_PATH


# ── Инициализация ─────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Создать таблицы, если они не существуют."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT,
                reg_date  TEXT    NOT NULL,
                trial_used INTEGER DEFAULT 0,
                current_server INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                sub_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                plan       TEXT    NOT NULL,
                start_date TEXT    NOT NULL,
                end_date   TEXT    NOT NULL,
                is_active  INTEGER DEFAULT 1,
                vless_uuid TEXT,
                xui_sub_id TEXT    DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        # Миграция: добавить xui_sub_id если таблица уже существует
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN xui_sub_id TEXT DEFAULT ''")
        except Exception:
            pass  # колонка уже существует
        # Миграция: добавить reminder_sent для отслеживания отправленных напоминаний
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN reminder_sent TEXT DEFAULT ''")
        except Exception:
            pass  # колонка уже существует
        # Миграция: добавить реферальные колонки
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_bonus_given INTEGER DEFAULT 0")
        except Exception:
            pass
        # Миграция: добавить server_id для мультисервера
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN server_id TEXT DEFAULT ''")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                amount    REAL    NOT NULL,
                status    TEXT    NOT NULL,
                timestamp TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        # Таблица платежей YooKassa
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id    TEXT    UNIQUE NOT NULL,
                user_id       INTEGER NOT NULL,
                amount        REAL    NOT NULL,
                plan_key      TEXT    NOT NULL,
                server_id     TEXT    DEFAULT '',
                status        TEXT    DEFAULT 'pending',
                created_at    TEXT    NOT NULL,
                paid_at       TEXT    DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()


# ── Users CRUD ────────────────────────────────────────────────────────────────

async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_user(user_id: int, username: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, reg_date) VALUES (?, ?, ?)",
            (user_id, username or "", datetime.utcnow().isoformat()),
        )
        await db.commit()


async def mark_trial_used(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET trial_used = 1 WHERE user_id = ?", (user_id,)
        )
        await db.commit()


async def reset_trial(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET trial_used = 0 WHERE user_id = ?", (user_id,)
        )
        await db.commit()


# ── Subscriptions CRUD ────────────────────────────────────────────────────────

async def create_subscription(
    user_id: int,
    plan: str,
    start_date: str,
    end_date: str,
    vless_uuid: str,
    xui_sub_id: str = "",
    server_id: str = "",
) -> int:
    """Создать подписку и вернуть sub_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO subscriptions
               (user_id, plan, start_date, end_date, is_active, vless_uuid, xui_sub_id, server_id)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
            (user_id, plan, start_date, end_date, vless_uuid, xui_sub_id, server_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_active_sub(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM subscriptions
               WHERE user_id = ? AND is_active = 1
               ORDER BY end_date DESC LIMIT 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_sub_by_xui_id(xui_sub_id: str) -> dict | None:
    """Find active subscription by 3X-UI subscription ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM subscriptions
               WHERE xui_sub_id = ?
               ORDER BY end_date DESC LIMIT 1""",
            (xui_sub_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def deactivate_subscription(sub_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE subscriptions SET is_active = 0 WHERE sub_id = ?", (sub_id,)
        )
        await db.commit()


async def deactivate_user_subs(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (user_id,)
        )
        await db.commit()


async def list_expiring(days: int) -> list[dict]:
    """Подписки, истекающие в пределах указанного числа дней."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = datetime.utcnow().isoformat()
        target = (datetime.utcnow() + timedelta(days=days)).isoformat()
        cursor = await db.execute(
            """SELECT * FROM subscriptions
               WHERE is_active = 1 AND end_date <= ? AND end_date > ?""",
            (target, now),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def list_expired() -> list[dict]:
    """Активные подписки, у которых дата истечения уже прошла."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = datetime.utcnow().isoformat()
        cursor = await db.execute(
            "SELECT * FROM subscriptions WHERE is_active = 1 AND end_date <= ?",
            (now,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ── Reminder functions ────────────────────────────────────────────────────────

async def get_subs_for_reminder(hours: int, reminder_code: str) -> list[dict]:
    """
    Получить подписки, которые истекают в пределах указанных часов
    и которым ещё не было отправлено это напоминание.

    reminder_code: "3d", "1d", "3h"
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = datetime.utcnow()
        target = (now + timedelta(hours=hours)).isoformat()
        now_iso = now.isoformat()
        cursor = await db.execute(
            """SELECT * FROM subscriptions
               WHERE is_active = 1
               AND end_date <= ?
               AND end_date > ?
               AND (reminder_sent IS NULL OR reminder_sent NOT LIKE ?)""",
            (target, now_iso, f"%{reminder_code}%"),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_reminder_sent(sub_id: int, reminder_code: str) -> None:
    """Отметить, что напоминание отправлено."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем текущее значение
        cursor = await db.execute(
            "SELECT reminder_sent FROM subscriptions WHERE sub_id = ?", (sub_id,)
        )
        row = await cursor.fetchone()
        current = row[0] if row and row[0] else ""

        # Добавляем новый код, если его ещё нет
        if reminder_code not in current:
            new_value = f"{current},{reminder_code}" if current else reminder_code
            await db.execute(
                "UPDATE subscriptions SET reminder_sent = ? WHERE sub_id = ?",
                (new_value, sub_id),
            )
            await db.commit()


# ── Transactions ──────────────────────────────────────────────────────────────

async def add_transaction(user_id: int, amount: float, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO transactions (user_id, amount, status, timestamp)
               VALUES (?, ?, ?, ?)""",
            (user_id, amount, status, datetime.utcnow().isoformat()),
        )
        await db.commit()


# ── Referral functions ────────────────────────────────────────────────────────

REFERRAL_BONUS_DAYS = 7  # Бонус дней за реферала


async def set_referrer(user_id: int, referrer_id: int) -> bool:
    """
    Установить реферера для пользователя.
    Возвращает True если реферер установлен, False если уже был или это сам пользователь.
    """
    if user_id == referrer_id:
        return False

    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем, нет ли уже реферера
        cursor = await db.execute(
            "SELECT referred_by FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row and row[0]:
            return False  # Уже есть реферер

        # Проверяем, существует ли реферер
        cursor = await db.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (referrer_id,)
        )
        if not await cursor.fetchone():
            return False  # Реферер не найден

        await db.execute(
            "UPDATE users SET referred_by = ? WHERE user_id = ?",
            (referrer_id, user_id),
        )
        await db.commit()
        return True


async def get_referral_stats(user_id: int) -> dict:
    """Получить статистику рефералов пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Количество приглашённых
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)
        )
        row = await cursor.fetchone()
        total_referrals = row[0] if row else 0

        # Количество активированных (тех, кто получил trial или подписку)
        cursor = await db.execute(
            """SELECT COUNT(*) FROM users u
               WHERE u.referred_by = ? AND u.referral_bonus_given = 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
        activated_referrals = row[0] if row else 0

        # Заработано дней
        bonus_days = activated_referrals * REFERRAL_BONUS_DAYS

        return {
            "total": total_referrals,
            "activated": activated_referrals,
            "bonus_days": bonus_days,
        }


async def process_referral_bonus(user_id: int) -> int | None:
    """
    Обработать реферальный бонус при активации пробного периода.
    Возвращает ID реферера, если бонус выдан, иначе None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Получаем пользователя
        cursor = await db.execute(
            "SELECT referred_by, referral_bonus_given FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        referred_by = row["referred_by"]
        bonus_given = row["referral_bonus_given"]

        # Если нет реферера или бонус уже выдан
        if not referred_by or bonus_given:
            return None

        # Помечаем бонус как выданный
        await db.execute(
            "UPDATE users SET referral_bonus_given = 1 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()

        return referred_by


async def extend_subscription(user_id: int, days: int) -> bool:
    """
    Продлить активную подписку на указанное количество дней.
    Возвращает True если продлено, False если нет активной подписки.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Получаем активную подписку
        cursor = await db.execute(
            """SELECT sub_id, end_date FROM subscriptions
               WHERE user_id = ? AND is_active = 1
               ORDER BY end_date DESC LIMIT 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False

        # Продлеваем
        current_end = datetime.fromisoformat(row["end_date"])
        new_end = current_end + timedelta(days=days)

        await db.execute(
            "UPDATE subscriptions SET end_date = ? WHERE sub_id = ?",
            (new_end.isoformat(), row["sub_id"]),
        )
        await db.commit()
        return True


async def extend_subscription_to_date(user_id: int, new_end: datetime) -> bool:
    """
    Продлить активную подписку до указанной даты.
    Возвращает True если продлено, False если нет активной подписки.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT sub_id FROM subscriptions
               WHERE user_id = ? AND is_active = 1
               ORDER BY end_date DESC LIMIT 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False

        await db.execute(
            "UPDATE subscriptions SET end_date = ? WHERE sub_id = ?",
            (new_end.isoformat(), row["sub_id"]),
        )
        await db.commit()
        return True


async def count_users() -> int:
    """Получить общее количество пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


# ── Payments (YooKassa) ───────────────────────────────────────────────────────

async def create_payment(
    payment_id: str,
    user_id: int,
    amount: float,
    plan_key: str,
    server_id: str = "",
) -> bool:
    """Создать запись о платеже."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO payments (payment_id, user_id, amount, plan_key, server_id, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (payment_id, user_id, amount, plan_key, server_id, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def get_payment(payment_id: str) -> dict | None:
    """Получить платёж по ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payments WHERE payment_id = ?",
            (payment_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_payment_status(payment_id: str, status: str, paid_at: str = None) -> bool:
    """Обновить статус платежа."""
    async with aiosqlite.connect(DB_PATH) as db:
        if paid_at:
            await db.execute(
                "UPDATE payments SET status = ?, paid_at = ? WHERE payment_id = ?",
                (status, paid_at, payment_id),
            )
        else:
            await db.execute(
                "UPDATE payments SET status = ? WHERE payment_id = ?",
                (status, payment_id),
            )
        await db.commit()
        return True


async def get_pending_payment(user_id: int) -> dict | None:
    """Получить последний ожидающий платёж пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM payments
               WHERE user_id = ? AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
