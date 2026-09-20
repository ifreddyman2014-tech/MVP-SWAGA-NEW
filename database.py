"""
Асинхронная работа с SQLite через aiosqlite.
Таблицы: users, subscriptions, transactions.
"""

import sqlite3

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
        except sqlite3.OperationalError:
            pass  # колонка уже существует
        # Миграция: добавить reminder_sent для отслеживания отправленных напоминаний
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN reminder_sent TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # колонка уже существует
        # Миграция: добавить реферальные колонки
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_bonus_given INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        # Миграция: добавить server_id для мультисервера
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN server_id TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # Миграция: добавить xui_email для обновления клиента в панели
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN xui_email TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # Миграция: добавить флаг получения компенсации
        try:
            await db.execute("ALTER TABLE users ADD COLUMN compensation_claimed INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
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
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id         TEXT    UNIQUE NOT NULL,
                user_id            INTEGER NOT NULL,
                amount             REAL    NOT NULL,
                plan_key           TEXT    NOT NULL,
                server_id          TEXT    DEFAULT '',
                status             TEXT    DEFAULT 'pending',
                created_at         TEXT    NOT NULL,
                paid_at            TEXT    DEFAULT NULL,
                target_end_date    TEXT    DEFAULT NULL,
                fulfillment_status TEXT    DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        # Миграция: добавить target_end_date если таблица payments уже существует
        try:
            await db.execute(
                "ALTER TABLE payments ADD COLUMN target_end_date TEXT DEFAULT NULL"
            )
        except sqlite3.OperationalError:
            pass  # колонка уже существует
        # Миграция: добавить fulfillment_status ('pending'=sync needed, 'fulfilled'=done, NULL=old)
        try:
            await db.execute(
                "ALTER TABLE payments ADD COLUMN fulfillment_status TEXT DEFAULT NULL"
            )
        except sqlite3.OperationalError:
            pass  # колонка уже существует
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
    xui_email: str = "",
) -> int:
    """Создать подписку и вернуть sub_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO subscriptions
               (user_id, plan, start_date, end_date, is_active, vless_uuid, xui_sub_id, server_id, xui_email)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (user_id, plan, start_date, end_date, vless_uuid, xui_sub_id, server_id, xui_email),
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


async def extend_subscription_to_date(
    user_id: int,
    new_end: datetime,
    plan: str | None = None,
) -> bool:
    """
    Продлить активную подписку до указанной даты.
    Если передан plan — обновляет и поле plan (нужно при переходе с trial на платный тариф).
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

        if plan is not None:
            await db.execute(
                "UPDATE subscriptions SET end_date = ?, plan = ? WHERE sub_id = ?",
                (new_end.isoformat(), plan, row["sub_id"]),
            )
        else:
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


async def get_subs_by_server(server_id: str) -> list[dict]:
    """Получить все активные подписки на конкретном сервере."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM subscriptions
               WHERE server_id = ? AND is_active = 1""",
            (server_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_sub_server(sub_id: int, new_server_id: str, new_uuid: str, new_email: str, new_sub_id: str) -> bool:
    """Обновить сервер для подписки (для failover)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE subscriptions
               SET server_id = ?, vless_uuid = ?, xui_email = ?, xui_sub_id = ?
               WHERE sub_id = ?""",
            (new_server_id, new_uuid, new_email, new_sub_id, sub_id),
        )
        await db.commit()
        return True


# ── Migration History (для безопасной очистки после failover) ─────────────────

async def init_migration_table() -> None:
    """Создать таблицу истории миграций."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS migration_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                sub_id          INTEGER NOT NULL,
                user_id         INTEGER NOT NULL,
                old_server_id   TEXT    NOT NULL,
                old_uuid        TEXT    NOT NULL,
                old_email       TEXT    NOT NULL,
                new_server_id   TEXT    NOT NULL,
                new_uuid        TEXT    NOT NULL,
                migrated_at     TEXT    NOT NULL,
                cleaned_up      INTEGER DEFAULT 0,
                cleaned_at      TEXT    DEFAULT NULL,
                FOREIGN KEY (sub_id) REFERENCES subscriptions(sub_id)
            )
        """)
        await db.commit()


async def save_migration(
    sub_id: int,
    user_id: int,
    old_server_id: str,
    old_uuid: str,
    old_email: str,
    new_server_id: str,
    new_uuid: str,
) -> bool:
    """Сохранить запись о миграции для последующей очистки."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO migration_history
                   (sub_id, user_id, old_server_id, old_uuid, old_email, new_server_id, new_uuid, migrated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sub_id, user_id, old_server_id, old_uuid, old_email,
                 new_server_id, new_uuid, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def get_pending_cleanups(server_id: str) -> list[dict]:
    """
    Получить список клиентов для удаления на восстановленном сервере.
    Возвращает только записи, которые ещё не очищены (cleaned_up = 0).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM migration_history
               WHERE old_server_id = ? AND cleaned_up = 0""",
            (server_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_cleanup_done(migration_id: int) -> bool:
    """Отметить запись миграции как очищенную."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE migration_history
               SET cleaned_up = 1, cleaned_at = ?
               WHERE id = ?""",
            (datetime.utcnow().isoformat(), migration_id),
        )
        await db.commit()
        return True


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
    """
    Обновить статус платежа.
    Для status='succeeded': атомарный guard WHERE status != 'succeeded'.
    Возвращает True только если строка реально изменилась (rowcount > 0).
    Возврат False для 'succeeded' означает: параллельный webhook уже обработал платёж.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        if status == "succeeded":
            # Атомарный guard: обновляем только если ещё не succeeded
            if paid_at:
                cursor = await db.execute(
                    """UPDATE payments SET status = ?, paid_at = ?
                       WHERE payment_id = ? AND status != 'succeeded'""",
                    (status, paid_at, payment_id),
                )
            else:
                cursor = await db.execute(
                    """UPDATE payments SET status = ?
                       WHERE payment_id = ? AND status != 'succeeded'""",
                    (status, payment_id),
                )
            await db.commit()
            # rowcount == 0 означает: параллельный webhook уже обработал этот платёж
            return cursor.rowcount > 0
        elif paid_at:
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


async def set_payment_target_end(payment_id: str, target_end_date: str) -> None:
    """
    Зафиксировать целевую дату окончания подписки для данного платежа.
    Вызывается как первое действие handle_payment_success — до extend_subscription_to_date.
    Это позволяет безопасно повторять синхронизацию: вместо пересчёта от текущей
    end_date берём сохранённое target_end_date, исключая повторное начисление дней.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET target_end_date = ? WHERE payment_id = ?",
            (target_end_date, payment_id),
        )
        await db.commit()


async def begin_fulfillment(
    payment_id: str,
    user_id: int,
    plan_key: str,
    plan_days: int,
    paid_at: str,
    *,
    is_renewal: bool,
    existing_uuid: str = "",
    new_uuid: str = "",
    new_sub_id: str = "",
    new_email: str = "",
    new_server_id: str = "",
    new_start_date: str = "",
) -> tuple[str, str | None, dict | None]:
    """
    Atomic payment fulfillment using BEGIN IMMEDIATE.

    Separates provider status ('succeeded') from fulfillment status ('pending'/'fulfilled').
    All four: payment status, target_end_date, subscription change, and sync task record
    are written in a single transaction. Network calls happen AFTER this returns.

    Returns (result_code, target_end_iso, sub_info):
      'first'             — won the race; subscription updated; fulfillment_status='pending'
      'sync_pending'      — DB already consistent, VPN panel sync still incomplete
      'already_fulfilled' — fully processed; skip
      'not_found'         — payment_id not in DB

    sub_info keys: uuid, email, xui_sub_id, server_id, end_date, expiry_ms, is_renewal
    """
    now_dt = datetime.fromisoformat(paid_at) if paid_at else datetime.utcnow()
    now_iso = paid_at or now_dt.isoformat()

    async with aiosqlite.connect(DB_PATH, isolation_level=None) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            # Read payment state
            cur = await db.execute(
                "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
            )
            pmt = await cur.fetchone()
            if not pmt:
                await db.execute("ROLLBACK")
                return ("not_found", None, None)
            pmt = dict(pmt)
            fs = pmt.get("fulfillment_status")

            if fs == "fulfilled":
                await db.execute("COMMIT")
                return ("already_fulfilled", pmt.get("target_end_date"), None)

            # status='succeeded' AND fs IS NULL → processed by code before this deploy
            if pmt.get("status") == "succeeded" and fs is None:
                await db.execute("COMMIT")
                return ("already_fulfilled", pmt.get("target_end_date"), None)

            if fs == "pending":
                # Payment committed atomically but VPN panel sync incomplete
                stored_target = pmt.get("target_end_date")
                sub_info = await _read_sub_info_on_conn(
                    db, user_id, stored_target or now_iso, now_iso
                )
                await db.execute("COMMIT")
                return ("sync_pending", stored_target, sub_info)

            # Fresh processing: status is still 'pending' (not yet 'succeeded')
            # Read existing subscription inside the write lock
            cur2 = await db.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 "
                "ORDER BY end_date DESC LIMIT 1",
                (user_id,),
            )
            existing_sub = await cur2.fetchone()
            existing_sub = dict(existing_sub) if existing_sub else None

            # Compute target_end, accumulating from existing sub if any
            if existing_sub and existing_sub.get("end_date"):
                base_date = max(datetime.fromisoformat(existing_sub["end_date"]), now_dt)
            else:
                base_date = now_dt
            target_end_dt = base_date + timedelta(days=plan_days)
            target_end_iso = target_end_dt.isoformat()
            expiry_ms = int(target_end_dt.timestamp() * 1000)

            # Atomically claim the payment (guard: only if still not 'succeeded')
            cur3 = await db.execute(
                """UPDATE payments
                   SET status = 'succeeded', paid_at = ?, target_end_date = ?,
                       fulfillment_status = 'pending'
                   WHERE payment_id = ? AND status != 'succeeded'""",
                (now_iso, target_end_iso, payment_id),
            )
            if cur3.rowcount == 0:
                # Another concurrent transaction won the race
                await db.execute("ROLLBACK")
                cur4 = await db.execute(
                    "SELECT fulfillment_status, target_end_date FROM payments WHERE payment_id = ?",
                    (payment_id,),
                )
                row4 = await cur4.fetchone()
                row4 = dict(row4) if row4 else {}
                if row4.get("fulfillment_status") == "pending":
                    sub_info = await _read_sub_info_on_conn(
                        db, user_id, row4.get("target_end_date") or now_iso, now_iso
                    )
                    return ("sync_pending", row4.get("target_end_date"), sub_info)
                return ("already_fulfilled", row4.get("target_end_date"), None)

            # Update subscription
            if is_renewal and existing_sub and existing_sub.get("vless_uuid"):
                await db.execute(
                    "UPDATE subscriptions SET end_date = ?, plan = ?, reminder_sent = '' "
                    "WHERE user_id = ? AND is_active = 1",
                    (target_end_iso, plan_key, user_id),
                )
                uuid = existing_sub["vless_uuid"]
                email = existing_sub.get("xui_email", f"tg_{user_id}")
                xui_sub_id = existing_sub.get("xui_sub_id", "")
                server_id_used = existing_sub.get("server_id", "")
            else:
                # New subscription (first buy or server change)
                await db.execute(
                    "UPDATE subscriptions SET is_active = 0 WHERE user_id = ? AND is_active = 1",
                    (user_id,),
                )
                uuid = new_uuid
                email = new_email
                xui_sub_id = new_sub_id
                server_id_used = new_server_id
                await db.execute(
                    """INSERT INTO subscriptions
                       (user_id, plan, start_date, end_date, is_active,
                        vless_uuid, xui_sub_id, server_id, xui_email)
                       VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                    (user_id, plan_key, new_start_date or now_iso,
                     target_end_iso, uuid, xui_sub_id, server_id_used, email),
                )

            await db.execute("COMMIT")
            sub_info = {
                "uuid": uuid,
                "email": email,
                "xui_sub_id": xui_sub_id,
                "server_id": server_id_used,
                "end_date": target_end_iso,
                "expiry_ms": expiry_ms,
                "is_renewal": is_renewal and bool(existing_sub and existing_sub.get("vless_uuid")),
            }
            return ("first", target_end_iso, sub_info)

        except Exception:
            await db.execute("ROLLBACK")
            raise


async def _read_sub_info_on_conn(
    db: aiosqlite.Connection,
    user_id: int,
    stored_target: str,
    now_iso: str,
) -> dict:
    """Read current active sub from an open connection for sync_pending sub_info."""
    cur = await db.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1 "
        "ORDER BY end_date DESC LIMIT 1",
        (user_id,),
    )
    row = await cur.fetchone()
    row = dict(row) if row else {}
    sub_end = row.get("end_date", stored_target)
    # No-shrink: use max(target_end, current sub.end_date)
    sync_end = max(stored_target, sub_end) if stored_target and sub_end else (stored_target or sub_end or now_iso)
    sync_ms = int(datetime.fromisoformat(sync_end).timestamp() * 1000)
    return {
        "uuid": row.get("vless_uuid", ""),
        "email": row.get("xui_email", ""),
        "xui_sub_id": row.get("xui_sub_id", ""),
        "server_id": row.get("server_id", ""),
        "end_date": sync_end,
        "expiry_ms": sync_ms,
        "is_renewal": bool(row.get("vless_uuid")),
    }


async def mark_payment_fulfilled(payment_id: str) -> None:
    """Mark a payment's fulfillment as complete (VPN panel sync done)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET fulfillment_status = 'fulfilled' WHERE payment_id = ?",
            (payment_id,),
        )
        await db.commit()


async def get_pending_fulfillments() -> list[dict]:
    """
    Return payments with fulfillment_status='pending' for startup sync.
    These are payments where the DB is consistent but VPN panel sync is incomplete.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT p.payment_id, p.user_id, p.plan_key, p.target_end_date,
                   s.vless_uuid, s.xui_email, s.xui_sub_id, s.server_id, s.end_date
            FROM payments p
            LEFT JOIN subscriptions s
                ON s.user_id = p.user_id AND s.is_active = 1
            WHERE p.fulfillment_status = 'pending'
            ORDER BY p.paid_at ASC
        """)
        rows = await cur.fetchall()
        result = []
        for row in rows:
            r = dict(row)
            target = r.get("target_end_date")
            sub_end = r.get("end_date")
            # No-shrink: sync with max(target_end, current sub.end_date)
            if target and sub_end:
                sync_end = max(target, sub_end)
            else:
                sync_end = target or sub_end
            r["sync_end_date"] = sync_end
            if sync_end:
                r["expiry_ms"] = int(datetime.fromisoformat(sync_end).timestamp() * 1000)
            else:
                r["expiry_ms"] = 0
            result.append(r)
        return result


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


# ── Promo Codes ───────────────────────────────────────────────────────────────

async def init_promo_table() -> None:
    """Создать таблицу промокодов если не существует."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                code          TEXT    UNIQUE NOT NULL,
                discount_percent INTEGER DEFAULT 0,
                bonus_days    INTEGER DEFAULT 0,
                max_uses      INTEGER DEFAULT 0,
                uses_count    INTEGER DEFAULT 0,
                expires_at    TEXT    DEFAULT NULL,
                is_active     INTEGER DEFAULT 1,
                created_at    TEXT    NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_uses (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_id   INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                used_at    TEXT    NOT NULL,
                FOREIGN KEY (promo_id) REFERENCES promo_codes(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(promo_id, user_id)
            )
        """)
        await db.commit()


async def create_promo_code(
    code: str,
    discount_percent: int = 0,
    bonus_days: int = 0,
    max_uses: int = 0,
    expires_at: str = None,
) -> bool:
    """Создать промокод. Возвращает True при успехе."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO promo_codes
                   (code, discount_percent, bonus_days, max_uses, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (code.upper(), discount_percent, bonus_days, max_uses, expires_at,
                 datetime.utcnow().isoformat()),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def get_promo_code(code: str) -> dict | None:
    """Получить промокод по коду."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM promo_codes WHERE code = ? AND is_active = 1",
            (code.upper(),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def validate_promo_code(code: str, user_id: int) -> tuple[bool, str, dict | None]:
    """
    Проверить промокод для пользователя.
    Возвращает: (is_valid, error_message, promo_data)
    """
    promo = await get_promo_code(code)
    if not promo:
        return False, "Промокод не найден или неактивен", None

    # Проверка срока действия
    if promo["expires_at"]:
        expires = datetime.fromisoformat(promo["expires_at"])
        if datetime.utcnow() > expires:
            return False, "Срок действия промокода истёк", None

    # Проверка лимита использований
    if promo["max_uses"] > 0 and promo["uses_count"] >= promo["max_uses"]:
        return False, "Промокод больше не действует", None

    # Проверка, не использовал ли пользователь уже этот промокод
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM promo_uses WHERE promo_id = ? AND user_id = ?",
            (promo["id"], user_id),
        )
        if await cursor.fetchone():
            return False, "Вы уже использовали этот промокод", None

    return True, "", promo


async def use_promo_code(promo_id: int, user_id: int) -> bool:
    """Отметить использование промокода пользователем."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # Записываем использование
            await db.execute(
                "INSERT INTO promo_uses (promo_id, user_id, used_at) VALUES (?, ?, ?)",
                (promo_id, user_id, datetime.utcnow().isoformat()),
            )
            # Увеличиваем счётчик
            await db.execute(
                "UPDATE promo_codes SET uses_count = uses_count + 1 WHERE id = ?",
                (promo_id,),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def list_promo_codes() -> list[dict]:
    """Получить все промокоды."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM promo_codes ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def deactivate_promo_code(code: str) -> bool:
    """Деактивировать промокод."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE promo_codes SET is_active = 0 WHERE code = ?",
            (code.upper(),),
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_user_discount_promo(user_id: int, promo_id: int, discount_percent: int) -> bool:
    """Сохранить активный скидочный промокод для пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN active_promo_id INTEGER DEFAULT NULL")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN active_discount INTEGER DEFAULT 0")
        except Exception:
            pass
        await db.execute(
            "UPDATE users SET active_promo_id = ?, active_discount = ? WHERE user_id = ?",
            (promo_id, discount_percent, user_id),
        )
        await db.commit()
        return True


async def get_user_discount(user_id: int) -> tuple[int | None, int]:
    """Получить активную скидку пользователя. Возвращает (promo_id, discount_percent)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT active_promo_id, active_discount FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row and row["active_promo_id"]:
            return row["active_promo_id"], row["active_discount"] or 0
        return None, 0


async def clear_user_discount(user_id: int) -> None:
    """Очистить активную скидку после использования."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET active_promo_id = NULL, active_discount = 0 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def get_all_user_ids() -> list[int]:
    """Получить все ID пользователей для рассылки."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_compensation_claimed(user_id: int) -> bool:
    """Проверить, получил ли пользователь компенсацию."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT compensation_claimed FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return bool(row[0]) if row else False


async def mark_compensation_claimed(user_id: int) -> None:
    """Отметить что пользователь получил компенсацию."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET compensation_claimed = 1 WHERE user_id = ?", (user_id,)
        )
        await db.commit()


# ── Web Users (регистрация без Telegram) ─────────────────────────────────────

async def init_web_users_table() -> None:
    """Создать таблицу web_users если не существует, добавить telegram_user_id при миграции."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                email            TEXT    UNIQUE NOT NULL,
                password_hash    TEXT    NOT NULL,
                created_at       TEXT    NOT NULL,
                user_id          INTEGER UNIQUE,
                sub_id           TEXT    DEFAULT NULL
            )
        """)
        # Миграция: добавляем telegram_user_id если колонка ещё не существует
        try:
            await db.execute(
                "ALTER TABLE web_users ADD COLUMN telegram_user_id INTEGER DEFAULT NULL"
            )
        except Exception:
            pass  # Колонка уже существует
        # Миграция: добавляем display_name если колонка ещё не существует
        try:
            await db.execute(
                "ALTER TABLE web_users ADD COLUMN display_name TEXT DEFAULT NULL"
            )
        except Exception:
            pass  # Колонка уже существует
        await db.commit()


async def create_web_user(email: str, password_hash: str) -> tuple[int, int]:
    """
    Создать web-пользователя и синтетического users-пользователя.
    Возвращает (web_user_id, synthetic_user_id).
    synthetic_user_id = -(web_user_id) — отрицательный, не конфликтует с Telegram-ID.
    """
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # Шаг 1: Вставляем web_user без user_id (NULL), потом обновим
        cursor = await db.execute(
            "INSERT INTO web_users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.lower().strip(), password_hash, now),
        )
        web_id = cursor.lastrowid
        # Шаг 2: Вычисляем синтетический user_id = -web_id
        synthetic_uid = -web_id
        await db.execute(
            "UPDATE web_users SET user_id = ? WHERE id = ?", (synthetic_uid, web_id)
        )
        # Шаг 3: Создаём запись в users (для FK в subscriptions)
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, reg_date) VALUES (?, ?, ?)",
            (synthetic_uid, f"web_{email}", now),
        )
        await db.commit()
        return web_id, synthetic_uid


async def get_web_user_by_email(email: str) -> dict | None:
    """Найти web-пользователя по email."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM web_users WHERE email = ?",
            (email.lower().strip(),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_web_user_by_id(web_user_id: int) -> dict | None:
    """Найти web-пользователя по id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM web_users WHERE id = ?",
            (web_user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def set_web_user_sub_id(web_user_id: int, sub_id: str) -> None:
    """Сохранить xui_sub_id для web-пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE web_users SET sub_id = ? WHERE id = ?",
            (sub_id, web_user_id),
        )
        await db.commit()


async def get_web_user_by_telegram_id(tg_user_id: int) -> dict | None:
    """Найти web-пользователя по Telegram user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM web_users WHERE telegram_user_id = ?",
            (tg_user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_web_user_from_telegram(tg_user_id: int, display_name: str) -> int:
    """
    Создать web_user для Telegram-пользователя (без email/пароля).
    user_id = tg_user_id (положительный) — совпадает с записью в таблице users.
    Возвращает web_user_id.
    """
    now = datetime.utcnow().isoformat()
    # Placeholder email чтобы соблюсти NOT NULL — никогда не совпадёт с реальным
    placeholder_email = f"tg_{tg_user_id}@telegram.auth"
    placeholder_hash = "tg_oauth_nologin"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT OR IGNORE INTO web_users
               (email, password_hash, created_at, user_id, telegram_user_id, display_name)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (placeholder_email, placeholder_hash, now, tg_user_id, tg_user_id, display_name),
        )
        if cursor.lastrowid:
            await db.commit()
            return cursor.lastrowid
        # Уже существует — обновляем display_name и возвращаем id
        await db.execute(
            "UPDATE web_users SET display_name = ? WHERE telegram_user_id = ?",
            (display_name, tg_user_id),
        )
        await db.commit()
        cur2 = await db.execute(
            "SELECT id FROM web_users WHERE telegram_user_id = ?", (tg_user_id,)
        )
        row = await cur2.fetchone()
        return row[0] if row else 0


async def get_all_web_users_with_subs() -> list[dict]:
    """Все web-пользователи с данными подписки — для admin-панели."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                w.id, w.email, w.created_at, w.user_id, w.sub_id,
                s.plan, s.end_date, s.is_active, s.server_id
            FROM web_users w
            LEFT JOIN subscriptions s ON s.user_id = w.user_id AND s.is_active = 1
            ORDER BY w.id DESC
        """)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
