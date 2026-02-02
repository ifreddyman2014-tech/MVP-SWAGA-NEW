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
) -> int:
    """Создать подписку и вернуть sub_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO subscriptions
               (user_id, plan, start_date, end_date, is_active, vless_uuid, xui_sub_id)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (user_id, plan, start_date, end_date, vless_uuid, xui_sub_id),
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


# ── Transactions ──────────────────────────────────────────────────────────────

async def add_transaction(user_id: int, amount: float, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO transactions (user_id, amount, status, timestamp)
               VALUES (?, ?, ?, ?)""",
            (user_id, amount, status, datetime.utcnow().isoformat()),
        )
        await db.commit()
