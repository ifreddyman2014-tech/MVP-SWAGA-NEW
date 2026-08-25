"""
SWAGA VPN — Metrics v0.2
Read-only analytics over vpn_bot.db.

DB timestamp convention (confirmed from database.py + sub_app.py source):
  ALL timestamps stored as UTC-naive ISO 8601 via datetime.utcnow().isoformat().
  Fields: users.reg_date, subscriptions.start_date/end_date,
          payments.created_at, payments.paid_at.

Usage:
    python metrics.py [--db PATH] [--tz TIMEZONE] [--json]
    python metrics.py --simulate-pricing 149 419 1390
    python metrics.py --simulate-pricing 199 449 1690
"""

import argparse
import asyncio
import json as _json
import math
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import aiosqlite

# ── Constants ─────────────────────────────────────────────────────────────────

BUSINESS_TIMEZONE = "Asia/Novokuznetsk"   # UTC+7
GIVEAWAY_BASE     = 9_000_000_000          # user_id >= this → synthetic giveaway
DB_PATH           = os.getenv("DATABASE_PATH", "./vpn_bot.db")
MRR_DIVISORS      = {"1m": 1, "3m": 3, "1y": 12}
PAID_PLANS        = ("1m", "3m", "1y")

# Sanity baselines from manual audit 2026-08-25 (used only for notes, not hardcoded results)
_SANITY_BASELINE  = {"total_real": 126, "ever_paid": 50, "active_paid": 30}


# ── Time boundary helpers ─────────────────────────────────────────────────────

def _to_utc_naive_iso(dt_aware: datetime) -> str:
    """Convert tz-aware datetime → UTC naive ISO string (DB storage format)."""
    return dt_aware.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def compute_boundaries(tz_name: str) -> dict:
    """
    Compute all period boundaries in the business timezone, then express them
    as UTC-naive ISO 8601 strings matching DB storage convention.

    The DB stores UTC-naive strings; to correctly filter "today in Novokuznetsk"
    we convert the business-TZ midnight to its UTC equivalent.
    """
    tz       = ZoneInfo(tz_name)
    now_biz  = datetime.now(tz=tz)
    now_utc  = datetime.now(timezone.utc)

    def _midnight(offset_days: int = 0) -> datetime:
        d = (now_biz + timedelta(days=offset_days))
        return d.replace(hour=0, minute=0, second=0, microsecond=0)

    today_biz        = _midnight(0)
    tomorrow_biz     = _midnight(1)
    day7_biz         = _midnight(-7)
    day30_biz        = _midnight(-30)
    month_start_biz  = today_biz.replace(day=1)
    if today_biz.month == 12:
        month_end_biz = today_biz.replace(year=today_biz.year + 1, month=1, day=1)
    else:
        month_end_biz = today_biz.replace(month=today_biz.month + 1, day=1)

    return {
        "tz_name":       tz_name,
        "business_now":  now_biz,
        "business_date": now_biz.strftime("%Y-%m-%d"),
        # Current UTC moment for is-subscription-active checks
        "now_utc":       now_utc.replace(tzinfo=None).isoformat(),
        # Period boundaries expressed in UTC for SQL comparison against UTC-naive DB values
        "today_start":   _to_utc_naive_iso(today_biz),
        "tomorrow_start": _to_utc_naive_iso(tomorrow_biz),
        "day7_start":    _to_utc_naive_iso(day7_biz),
        "day30_start":   _to_utc_naive_iso(day30_biz),
        "month_start":   _to_utc_naive_iso(month_start_biz),
        "month_end":     _to_utc_naive_iso(month_end_biz),
    }


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _scalar(conn: aiosqlite.Connection, sql: str, params=()) -> Any:
    async with conn.execute(sql, params) as cur:
        row = await cur.fetchone()
        return row[0] if row else None


async def _fetchall(conn: aiosqlite.Connection, sql: str, params=()) -> list:
    async with conn.execute(sql, params) as cur:
        return await cur.fetchall()


# ── Timestamp storage analysis ────────────────────────────────────────────────

async def analyse_timestamps(conn: aiosqlite.Connection) -> dict:
    """
    Sample timestamps from each table and document the storage convention.
    No values are modified.
    """
    samples = {}

    samples["payments.created_at"] = [
        r[0] for r in await _fetchall(
            conn, "SELECT created_at FROM payments ORDER BY id LIMIT 4"
        )
    ]
    samples["payments.paid_at"] = [
        r[0] for r in await _fetchall(
            conn,
            "SELECT paid_at FROM payments WHERE status='succeeded' ORDER BY id LIMIT 4",
        )
    ]
    samples["users.reg_date"] = [
        r[0] for r in await _fetchall(
            conn,
            "SELECT reg_date FROM users WHERE user_id > 0 AND user_id < ? ORDER BY rowid LIMIT 4",
            (GIVEAWAY_BASE,),
        )
    ]
    samples["subscriptions.start_date"] = [
        r[0] for r in await _fetchall(
            conn,
            "SELECT start_date FROM subscriptions WHERE user_id > 0 LIMIT 4",
        )
    ]
    samples["subscriptions.end_date"] = [
        r[0] for r in await _fetchall(
            conn,
            "SELECT end_date FROM subscriptions WHERE user_id > 0 LIMIT 4",
        )
    ]

    # Source code evidence (from database.py and sub_app.py):
    #   users.reg_date       → datetime.utcnow().isoformat()   (database.py:117)
    #   payments.created_at  → datetime.utcnow().isoformat()   (database.py:572)
    #   payments.paid_at     → datetime.utcnow().isoformat()   (sub_app.py:863)
    #   subscriptions.*_date → computed from datetime.utcnow() in bot.py, passed as str

    return {
        "samples": samples,
        "detected_convention": "UTC-naive ISO 8601 (datetime.utcnow().isoformat())",
        "confidence": "HIGH — confirmed directly in database.py and sub_app.py source code",
        "implication": (
            "All SQL period boundaries must be expressed in UTC. "
            "Business-TZ midnight is converted to UTC before passing to SQLite."
        ),
    }


# ── Users ─────────────────────────────────────────────────────────────────────

def _classify_active_paid_row(sub_plan: str, pay_plan: str) -> str:
    """
    EXACT      — sub.plan == payment.plan_key (both in PAID_PLANS)
    INFERRED   — sub.plan='trial', payment.plan_key in PAID_PLANS (Bug A)
    UNRESOLVED — any other combination
    """
    if sub_plan in PAID_PLANS and sub_plan == pay_plan:
        return "exact"
    if sub_plan == "trial" and pay_plan in PAID_PLANS:
        return "inferred"
    return "unresolved"


async def calc_users(conn: aiosqlite.Connection, b: dict) -> dict:
    """
    b["now_utc"] used for subscription-active check (end_date >= now_utc).
    """
    real_tg = await _scalar(
        conn,
        "SELECT COUNT(*) FROM users WHERE user_id > 0 AND user_id < ?",
        (GIVEAWAY_BASE,),
    )
    web = await _scalar(conn, "SELECT COUNT(*) FROM users WHERE user_id < 0")
    giveaway = await _scalar(
        conn, "SELECT COUNT(*) FROM users WHERE user_id >= ?", (GIVEAWAY_BASE,)
    )
    ever_paid = await _scalar(
        conn,
        "SELECT COUNT(DISTINCT user_id) FROM payments "
        "WHERE status='succeeded' AND user_id > 0 AND user_id < ?",
        (GIVEAWAY_BASE,),
    )

    # Fetch all active-paid rows for classification (one query, classify in Python)
    active_rows = await _fetchall(
        conn,
        """
        WITH last_pay AS (
            SELECT user_id, plan_key, amount, paid_at,
                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY paid_at DESC) AS rn
            FROM payments
            WHERE status = 'succeeded'
        )
        SELECT s.user_id, s.plan AS sub_plan, p.plan_key AS pay_plan,
               p.amount, p.paid_at, s.end_date
        FROM subscriptions s
        JOIN last_pay p ON p.user_id = s.user_id AND p.rn = 1
        WHERE s.is_active = 1
          AND s.end_date >= ?
          AND s.user_id > 0 AND s.user_id < ?
        """,
        (b["now_utc"], GIVEAWAY_BASE),
    )

    exact_users, inferred_users, unresolved_users = [], [], []
    for user_id, sub_plan, pay_plan, amount, paid_at, end_date in active_rows:
        cls = _classify_active_paid_row(sub_plan, pay_plan)
        entry = {
            "user_id": user_id, "sub_plan": sub_plan, "pay_plan": pay_plan,
            "amount": amount, "paid_at": paid_at, "end_date": end_date,
        }
        if cls == "exact":
            exact_users.append(entry)
        elif cls == "inferred":
            inferred_users.append(entry)
        else:
            unresolved_users.append(entry)

    active_total = len(exact_users) + len(inferred_users) + len(unresolved_users)
    expired_paid = max((ever_paid or 0) - active_total, 0)

    return {
        "real_tg":           real_tg or 0,
        "web":               web or 0,
        "total_real":        (real_tg or 0) + (web or 0),
        "giveaway_synthetic": giveaway or 0,
        "ever_paid":         ever_paid or 0,
        "active_paid": {
            "total":            active_total,
            "exact":            len(exact_users),
            "inferred":         len(inferred_users),
            "unresolved":       len(unresolved_users),
            "exact_detail":     exact_users,
            "inferred_detail":  inferred_users,
            "unresolved_detail": unresolved_users,
        },
        "expired_paid": expired_paid,
    }


# ── Cash Revenue ──────────────────────────────────────────────────────────────

async def calc_cash_revenue(conn: aiosqlite.Connection, b: dict) -> dict:
    """
    Sums payments.amount for status='succeeded' within each UTC-aligned period boundary.
    Period boundaries are pre-computed from business TZ midnight → UTC.
    """
    row = (
        await _fetchall(
            conn,
            """
            SELECT
                ROUND(SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN amount ELSE 0 END), 2),
                ROUND(SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN amount ELSE 0 END), 2),
                ROUND(SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN amount ELSE 0 END), 2),
                ROUND(SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN amount ELSE 0 END), 2),
                ROUND(SUM(amount), 2)
            FROM payments
            WHERE status = 'succeeded'
            """,
            (
                b["today_start"], b["tomorrow_start"],
                b["day7_start"],  b["tomorrow_start"],
                b["day30_start"], b["tomorrow_start"],
                b["month_start"], b["month_end"],
            ),
        )
    )[0]
    return {
        "today":         row[0] or 0.0,
        "last_7d":       row[1] or 0.0,
        "last_30d":      row[2] or 0.0,
        "current_month": row[3] or 0.0,
        "all_time":      row[4] or 0.0,
    }


# ── Estimated MRR ─────────────────────────────────────────────────────────────

def calc_mrr(active_paid_detail: dict) -> dict:
    """
    Compute Estimated MRR from pre-classified active paid user data.

    Resolution:
      EXACT    — sub.plan == pay.plan_key → use pay.amount / divisor
      INFERRED — sub.plan='trial', pay.plan_key ∈ PAID_PLANS → inferred amount / divisor
      UNRESOLVED → excluded from MRR total (no guessing)
    """
    exact_mrr    = 0.0
    inferred_mrr = 0.0

    for entry in active_paid_detail["exact_detail"]:
        div = MRR_DIVISORS.get(entry["pay_plan"], 1)
        exact_mrr += entry["amount"] / div

    for entry in active_paid_detail["inferred_detail"]:
        div = MRR_DIVISORS.get(entry["pay_plan"], 1)
        inferred_mrr += entry["amount"] / div

    exact_mrr    = round(exact_mrr, 2)
    inferred_mrr = round(inferred_mrr, 2)
    known_mrr    = round(exact_mrr + inferred_mrr, 2)

    total        = active_paid_detail["total"]
    covered      = active_paid_detail["exact"] + active_paid_detail["inferred"]
    unresolved   = active_paid_detail["unresolved"]
    coverage_pct = round(covered / total * 100, 1) if total else 0.0

    arppu_covered     = round(known_mrr / covered, 2) if covered else None
    arppu_lower_bound = round(known_mrr / total, 2)   if total   else None

    return {
        "exact_mrr":          exact_mrr,
        "inferred_mrr":       inferred_mrr,
        "known_mrr":          known_mrr,
        "covered_users":      covered,
        "unresolved_users":   unresolved,
        "coverage_pct":       coverage_pct,
        "unresolved_detail":  active_paid_detail["unresolved_detail"],
        "arppu_covered":      arppu_covered,
        "arppu_lower_bound":  arppu_lower_bound,
    }


# ── New Payers ────────────────────────────────────────────────────────────────

async def calc_new_payers(conn: aiosqlite.Connection, b: dict) -> dict:
    """
    New payer = user whose FIRST succeeded payment falls within the period.
    Period boundaries in UTC, matching DB storage.
    """
    rows = await _fetchall(
        conn,
        """
        WITH first_pay AS (
            SELECT user_id, MIN(paid_at) AS first_paid
            FROM payments
            WHERE status = 'succeeded'
              AND user_id > 0 AND user_id < ?
            GROUP BY user_id
        )
        SELECT
            SUM(CASE WHEN first_paid >= ? AND first_paid < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN first_paid >= ? AND first_paid < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN first_paid >= ? AND first_paid < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN first_paid >= ? AND first_paid < ? THEN 1 ELSE 0 END)
        FROM first_pay
        """,
        (
            GIVEAWAY_BASE,
            b["today_start"],  b["tomorrow_start"],
            b["day7_start"],   b["tomorrow_start"],
            b["day30_start"],  b["tomorrow_start"],
            b["month_start"],  b["month_end"],
        ),
    )
    r = rows[0] if rows else (0, 0, 0, 0)
    return {
        "today":         r[0] or 0,
        "last_7d":       r[1] or 0,
        "last_30d":      r[2] or 0,
        "current_month": r[3] or 0,
    }


# ── Renewals ──────────────────────────────────────────────────────────────────

async def calc_renewals(conn: aiosqlite.Connection, b: dict) -> dict:
    """
    Renewal event  = any succeeded payment after the user's FIRST succeeded payment.
    Renewing users = distinct users with ≥1 renewal event in the period.
    """
    rows = await _fetchall(
        conn,
        """
        WITH pay_ranked AS (
            SELECT user_id, paid_at,
                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY paid_at) AS rn
            FROM payments
            WHERE status = 'succeeded'
              AND user_id > 0 AND user_id < ?
        ),
        renewals AS (
            SELECT user_id, paid_at FROM pay_ranked WHERE rn > 1
        )
        SELECT
            -- Events (raw count of renewal payments in period)
            SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN 1 ELSE 0 END),
            -- Users (distinct users with ≥1 renewal in period)
            COUNT(DISTINCT CASE WHEN paid_at >= ? AND paid_at < ? THEN user_id END),
            COUNT(DISTINCT CASE WHEN paid_at >= ? AND paid_at < ? THEN user_id END),
            COUNT(DISTINCT CASE WHEN paid_at >= ? AND paid_at < ? THEN user_id END),
            COUNT(DISTINCT CASE WHEN paid_at >= ? AND paid_at < ? THEN user_id END)
        FROM renewals
        """,
        (
            GIVEAWAY_BASE,
            # events
            b["today_start"],  b["tomorrow_start"],
            b["day7_start"],   b["tomorrow_start"],
            b["day30_start"],  b["tomorrow_start"],
            b["month_start"],  b["month_end"],
            # users
            b["today_start"],  b["tomorrow_start"],
            b["day7_start"],   b["tomorrow_start"],
            b["day30_start"],  b["tomorrow_start"],
            b["month_start"],  b["month_end"],
        ),
    )
    r = rows[0] if rows else (0,) * 8
    return {
        "events": {
            "today":         r[0] or 0,
            "last_7d":       r[1] or 0,
            "last_30d":      r[2] or 0,
            "current_month": r[3] or 0,
        },
        "users": {
            "today":         r[4] or 0,
            "last_7d":       r[5] or 0,
            "last_30d":      r[6] or 0,
            "current_month": r[7] or 0,
        },
    }


# ── Payment Frequency ─────────────────────────────────────────────────────────

async def calc_payment_frequency(conn: aiosqlite.Connection) -> dict:
    """
    Distribution of succeeded payment count per real TG user.
    Avg and median computed in Python from raw distribution.
    """
    rows = await _fetchall(
        conn,
        """
        SELECT cnt, COUNT(*) AS users
        FROM (
            SELECT user_id, COUNT(*) AS cnt
            FROM payments
            WHERE status = 'succeeded'
              AND user_id > 0 AND user_id < ?
            GROUP BY user_id
        )
        GROUP BY cnt
        ORDER BY cnt
        """,
        (GIVEAWAY_BASE,),
    )

    distribution: dict[str, int] = {}
    all_counts: list[int] = []

    for cnt, users in rows:
        key = str(cnt) if cnt < 5 else "5+"
        distribution[key] = distribution.get(key, 0) + users
        all_counts.extend([cnt] * users)

    avg    = round(statistics.mean(all_counts), 2)  if all_counts else None
    median = statistics.median(all_counts)           if all_counts else None

    return {
        "distribution": distribution,
        "avg":          avg,
        "median":       median,
    }


# ── Purchase Plan Mix ─────────────────────────────────────────────────────────

async def calc_purchase_plan_mix(conn: aiosqlite.Connection, b: dict) -> dict:
    """
    Count of succeeded payment transactions by plan_key per period.
    Source: payments table (ground truth for what was actually purchased).
    """
    rows = await _fetchall(
        conn,
        """
        SELECT plan_key,
            SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN 1 ELSE 0 END),
            SUM(CASE WHEN paid_at >= ? AND paid_at < ? THEN 1 ELSE 0 END),
            COUNT(*) AS all_time
        FROM payments
        WHERE status = 'succeeded'
          AND plan_key IN ('1m', '3m', '1y')
          AND user_id > 0 AND user_id < ?
        GROUP BY plan_key
        """,
        (
            b["today_start"],  b["tomorrow_start"],
            b["day7_start"],   b["tomorrow_start"],
            b["day30_start"],  b["tomorrow_start"],
            b["month_start"],  b["month_end"],
            GIVEAWAY_BASE,
        ),
    )

    empty = {"1m": 0, "3m": 0, "1y": 0}
    periods = {
        "today":         dict(empty),
        "last_7d":       dict(empty),
        "last_30d":      dict(empty),
        "current_month": dict(empty),
        "all_time":      dict(empty),
    }
    for plan, today, d7, d30, cur_m, all_t in rows:
        periods["today"][plan]         = today or 0
        periods["last_7d"][plan]       = d7    or 0
        periods["last_30d"][plan]      = d30   or 0
        periods["current_month"][plan] = cur_m or 0
        periods["all_time"][plan]      = all_t or 0

    return periods


# ── Active Plan Mix ───────────────────────────────────────────────────────────

def calc_active_plan_mix(active_paid_detail: dict) -> dict:
    """
    Derived from the pre-classified active paid users.
    For each plan: exact count vs inferred count.
    Unresolved listed separately.
    """
    mix: dict[str, dict] = {
        p: {"exact": 0, "inferred": 0} for p in PAID_PLANS
    }

    for entry in active_paid_detail["exact_detail"]:
        p = entry["pay_plan"]
        if p in mix:
            mix[p]["exact"] += 1

    for entry in active_paid_detail["inferred_detail"]:
        p = entry["pay_plan"]
        if p in mix:
            mix[p]["inferred"] += 1

    return {
        "by_plan":    mix,
        "exact":      active_paid_detail["exact"],
        "inferred":   active_paid_detail["inferred"],
        "unresolved": active_paid_detail["unresolved"],
    }


# ── Customer Status ───────────────────────────────────────────────────────────

def calc_customer_status(users: dict, integrity: dict) -> dict:
    """Pure function — derived from already-fetched users + integrity data."""
    total_real    = users["total_real"]
    ever_paid     = users["ever_paid"]
    active_paid   = users["active_paid"]["total"]
    active_free   = integrity["active_free_without_payment"]["count"]
    never_paid    = max(total_real - ever_paid, 0)
    inactive_paid = max(ever_paid - active_paid, 0)

    return {
        "total_real":    total_real,
        "never_paid":    never_paid,
        "active_free":   active_free,
        "ever_paid":     ever_paid,
        "active_paid":   active_paid,
        "inactive_paid": inactive_paid,
    }


# ── Buyer Metrics ─────────────────────────────────────────────────────────────

def calc_buyer_metrics(users: dict, cash: dict, pay_freq: dict) -> dict:
    """Pure function — derived from already-fetched data. No DB access."""
    total_real  = users["total_real"]
    ever_paid   = users["ever_paid"]
    active_paid = users["active_paid"]["total"]

    dist        = pay_freq["distribution"]
    users_2plus = sum(dist.get(k, 0) for k in ["2", "3", "4", "5+"])
    users_3plus = sum(dist.get(k, 0) for k in ["3", "4", "5+"])
    users_4plus = sum(dist.get(k, 0) for k in ["4", "5+"])
    users_5plus = dist.get("5+", 0)

    def _pct(num: int, den: int) -> Optional[float]:
        return round(num / den * 100, 1) if den else None

    all_time_cash = cash["all_time"]

    return {
        "buyer_conversion": {
            "ever_paid_of_real":   _pct(ever_paid, total_real),
            "active_paid_of_real": _pct(active_paid, total_real),
        },
        "active_buyer_rate": _pct(active_paid, ever_paid),
        "repeat_buyer_rate": _pct(users_2plus, ever_paid),
        "high_frequency_buyers": {
            "3plus": {
                "count": users_3plus,
                "pct_of_ever_paid": _pct(users_3plus, ever_paid) or 0.0,
            },
            "4plus": {
                "count": users_4plus,
                "pct_of_ever_paid": _pct(users_4plus, ever_paid) or 0.0,
            },
            "5plus": {
                "count": users_5plus,
                "pct_of_ever_paid": _pct(users_5plus, ever_paid) or 0.0,
            },
        },
        "cash_arppu_historical": round(all_time_cash / ever_paid, 2) if ever_paid else None,
        "all_time_cash": all_time_cash,
        "ever_paid":     ever_paid,
    }


# ── Payment Entitlement ───────────────────────────────────────────────────────

async def calc_payment_entitlement(conn: aiosqlite.Connection) -> dict:
    """
    For each succeeded real-TG payment, check whether a subscription start_date
    falls within [-1h, +24h] of paid_at.

      confirmed    — matching subscription start found in the window
      suspicious   — user has subscription(s) but no start within window
                     (most are renewals: end_date is extended, not a new start_date)
      unverifiable — user has NO subscription record at all, or paid_at is NULL
    """
    payments = await _fetchall(
        conn,
        "SELECT user_id, paid_at FROM payments "
        "WHERE status='succeeded' AND user_id > 0 AND user_id < ?",
        (GIVEAWAY_BASE,),
    )

    sub_start_rows = await _fetchall(
        conn,
        "SELECT user_id, start_date FROM subscriptions WHERE user_id > 0 AND user_id < ?",
        (GIVEAWAY_BASE,),
    )
    sub_starts: dict[int, list] = {}
    for uid, start in sub_start_rows:
        sub_starts.setdefault(uid, []).append(start)

    confirmed = suspicious = unverifiable = 0

    for uid, paid_at in payments:
        if paid_at is None or uid not in sub_starts:
            unverifiable += 1
            continue
        try:
            paid_dt = datetime.fromisoformat(paid_at)
        except (ValueError, TypeError):
            unverifiable += 1
            continue

        window_lo = paid_dt - timedelta(hours=1)
        window_hi = paid_dt + timedelta(hours=24)

        found = False
        for start in sub_starts[uid]:
            if start is None:
                continue
            try:
                if window_lo <= datetime.fromisoformat(start) <= window_hi:
                    found = True
                    break
            except (ValueError, TypeError):
                continue

        if found:
            confirmed += 1
        else:
            suspicious += 1

    total = len(payments)
    return {
        "total_payments": total,
        "confirmed":      confirmed,
        "suspicious":     suspicious,
        "unverifiable":   unverifiable,
        "confirmed_pct":  round(confirmed   / total * 100, 1) if total else 0.0,
        "suspicious_pct": round(suspicious  / total * 100, 1) if total else 0.0,
        "note": (
            "'suspicious' = payment exists but no subscription start within [-1h,+24h] of paid_at. "
            "Most are renewals (end_date extended, not a new start_date). "
            "Not necessarily an error."
        ),
    }


# ── Pricing Simulator ─────────────────────────────────────────────────────────

def simulate_pricing(active_plan_mix: dict, prices: list) -> dict:
    """
    Pure function — no DB access.
    Computes effective ARPU and simulated MRR using current active plan mix proportions.
    prices: [price_1m, price_3m, price_1y]
    """
    price_1m, price_3m, price_1y = float(prices[0]), float(prices[1]), float(prices[2])

    monthly = {
        "1m": price_1m,
        "3m": price_3m / 3.0,
        "1y": price_1y / 12.0,
    }

    plan_counts = {
        p: active_plan_mix["by_plan"][p]["exact"] + active_plan_mix["by_plan"][p]["inferred"]
        for p in PAID_PLANS
    }
    covered = sum(plan_counts.values())

    if covered == 0:
        return {"error": "no covered users in active plan mix"}

    effective_arpu = sum(monthly[p] * plan_counts[p] for p in PAID_PLANS) / covered
    effective_arpu = round(effective_arpu, 2)
    simulated_mrr  = round(effective_arpu * covered, 2)

    mrr_targets = [10_000, 25_000, 50_000, 100_000, 150_000, 1_000_000]
    customers_for_target = {
        t: math.ceil(t / effective_arpu) if effective_arpu > 0 else None
        for t in mrr_targets
    }

    return {
        "input_prices":    {"1m": price_1m, "3m": price_3m, "1y": price_1y},
        "monthly_equiv":   {p: round(monthly[p], 2) for p in PAID_PLANS},
        "plan_mix_counts": plan_counts,
        "plan_mix_pct":    {p: round(plan_counts[p] / covered * 100, 1) for p in PAID_PLANS},
        "covered_users":   covered,
        "effective_arpu":  effective_arpu,
        "simulated_mrr":   simulated_mrr,
        "customers_for_mrr_target": customers_for_target,
    }


# ── Data Integrity ────────────────────────────────────────────────────────────

async def calc_data_integrity(conn: aiosqlite.Connection, b: dict) -> dict:
    """
    All checks are COUNT + user_id lists only. Nothing is modified.

    v0.2 changes vs v0.1:
      - Removed: succeeded_payment_without_active_subscription
        (normal churn — user paid and subscription later expired; not an error)
      - Split: active_subscription_without_any_succeeded_payment
        → active_free_without_payment (trial/giveaway — NORMAL)
        → paid_plan_without_payment   (1m/3m/1y — actual ERROR)
    """
    now_utc = b["now_utc"]

    # 1a. active sub without payment — free plans (trial/giveaway) — NORMAL
    rows = await _fetchall(
        conn,
        """
        SELECT DISTINCT s.user_id
        FROM subscriptions s
        WHERE s.is_active = 1 AND s.end_date >= ?
          AND s.user_id > 0 AND s.user_id < ?
          AND NOT EXISTS (
              SELECT 1 FROM payments p
              WHERE p.user_id = s.user_id AND p.status = 'succeeded'
          )
          AND (s.plan = 'trial' OR s.plan LIKE 'giveaway%')
        ORDER BY s.user_id
        """,
        (now_utc, GIVEAWAY_BASE),
    )
    active_free_no_pay = [r[0] for r in rows]

    # 1b. active sub without payment — paid plan — ACTUAL ERROR
    rows = await _fetchall(
        conn,
        """
        SELECT DISTINCT s.user_id
        FROM subscriptions s
        WHERE s.is_active = 1 AND s.end_date >= ?
          AND s.user_id > 0 AND s.user_id < ?
          AND NOT EXISTS (
              SELECT 1 FROM payments p
              WHERE p.user_id = s.user_id AND p.status = 'succeeded'
          )
          AND s.plan IN ('1m', '3m', '1y')
        ORDER BY s.user_id
        """,
        (now_utc, GIVEAWAY_BASE),
    )
    paid_plan_no_pay = [r[0] for r in rows]

    # 2. paid user with active subscription tagged plan='trial' (Bug A)
    rows = await _fetchall(
        conn,
        """
        SELECT DISTINCT s.user_id
        FROM subscriptions s
        JOIN payments p ON p.user_id = s.user_id AND p.status = 'succeeded'
        WHERE s.is_active = 1 AND s.end_date >= ?
          AND s.plan = 'trial'
          AND s.user_id > 0 AND s.user_id < ?
        ORDER BY s.user_id
        """,
        (now_utc, GIVEAWAY_BASE),
    )
    paid_plan_trial = [r[0] for r in rows]

    # 3. duplicate active subscriptions per user
    rows = await _fetchall(
        conn,
        """
        SELECT user_id
        FROM subscriptions
        WHERE is_active = 1 AND end_date >= ?
        GROUP BY user_id HAVING COUNT(*) > 1
        ORDER BY user_id
        """,
        (now_utc,),
    )
    dup_active = [r[0] for r in rows]

    # 4. subscription duration > 400 days (non-giveaway, real TG users)
    rows = await _fetchall(
        conn,
        """
        SELECT user_id, plan, start_date, end_date,
               CAST(julianday(end_date) - julianday(start_date) AS INTEGER) AS days
        FROM subscriptions
        WHERE (julianday(end_date) - julianday(start_date)) > 400
          AND plan NOT LIKE 'giveaway%'
          AND user_id > 0 AND user_id < ?
        ORDER BY days DESC
        """,
        (GIVEAWAY_BASE,),
    )
    suspicious_gt400 = [
        {"user_id": r[0], "plan": r[1], "start_date": r[2], "end_date": r[3], "duration_days": r[4]}
        for r in rows
    ]

    # 5. succeeded payments with NULL paid_at
    no_paid_at = await _scalar(
        conn,
        "SELECT COUNT(*) FROM payments WHERE status = 'succeeded' AND paid_at IS NULL",
    )

    # 6. active subscription with end_date < now (scheduler missed it)
    rows = await _fetchall(
        conn,
        """
        SELECT user_id FROM subscriptions
        WHERE is_active = 1 AND end_date < ?
          AND user_id > 0 AND user_id < ?
        ORDER BY user_id
        """,
        (now_utc, GIVEAWAY_BASE),
    )
    active_but_expired = [r[0] for r in rows]

    # 7. plan mismatch: active sub.plan != latest payment plan_key
    #    (excluding trial mismatch = Bug A, which is separately tracked)
    rows = await _fetchall(
        conn,
        """
        WITH last_pay AS (
            SELECT user_id, plan_key, amount, paid_at,
                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY paid_at DESC) AS rn
            FROM payments WHERE status = 'succeeded'
        )
        SELECT s.user_id, s.plan AS sub_plan, p.plan_key AS pay_plan,
               p.amount, p.paid_at, s.end_date
        FROM subscriptions s
        JOIN last_pay p ON p.user_id = s.user_id AND p.rn = 1
        WHERE s.is_active = 1 AND s.end_date >= ?
          AND s.user_id > 0 AND s.user_id < ?
          AND s.plan != p.plan_key
          AND s.plan NOT IN ('trial')
          AND s.plan NOT LIKE 'giveaway%'
        ORDER BY s.user_id
        """,
        (now_utc, GIVEAWAY_BASE),
    )
    plan_mismatch = [
        {
            "user_id": r[0], "sub_plan": r[1], "pay_plan": r[2],
            "amount": r[3], "paid_at": r[4], "sub_end": r[5],
            "note": "needs_manual_review",
        }
        for r in rows
    ]

    return {
        "active_free_without_payment": {
            "count":    len(active_free_no_pay),
            "user_ids": active_free_no_pay,
            "note":     "Normal — trial/giveaway access, not an error",
        },
        "paid_plan_without_payment": {
            "count":    len(paid_plan_no_pay),
            "user_ids": paid_plan_no_pay,
            "note":     "ERROR — active paid plan with no recorded payment",
        },
        "paid_user_with_active_plan_trial": {
            "count":    len(paid_plan_trial),
            "user_ids": paid_plan_trial,
            "note":     "Bug A — plan stored as 'trial' despite payment; triage only",
        },
        "duplicate_active_subscriptions_per_user": {
            "count": len(dup_active), "user_ids": dup_active,
        },
        "suspicious_subscription_duration_gt_400_days": {
            "count": len(suspicious_gt400), "detail": suspicious_gt400,
        },
        "succeeded_payments_without_paid_at": {
            "count": no_paid_at or 0,
        },
        "active_subscription_expired_by_date": {
            "count": len(active_but_expired), "user_ids": active_but_expired,
        },
        "plan_mismatch_needs_manual_review": {
            "count": len(plan_mismatch), "detail": plan_mismatch,
        },
    }


# ── Sanity notes ──────────────────────────────────────────────────────────────

def build_sanity_notes(users: dict) -> list[str]:
    notes = []
    checks = [
        ("total_real",           users["total_real"],              5),
        ("ever_paid",            users["ever_paid"],               5),
        ("active_paid (total)",  users["active_paid"]["total"],    5),
    ]
    for label, actual, tolerance in checks:
        expected = _SANITY_BASELINE.get(label.split()[0], None)
        if expected is None:
            continue
        diff = actual - expected
        if abs(diff) > tolerance:
            notes.append(
                f"{label}: got {actual}, expected ≈{expected} "
                f"(diff={diff:+d}, tolerance ±{tolerance})"
            )
    if not notes:
        notes.append("All key counts within ±5 of manual audit baseline (2026-08-25).")
    return notes


# ── Master collect ────────────────────────────────────────────────────────────

async def collect_metrics(
    db_path: str,
    tz_name: str = BUSINESS_TIMEZONE,
    simulate_prices: Optional[list] = None,
) -> dict:
    """
    Open DB in query-only mode, compute all metrics, return structured dict.
    No writes are performed.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    b = compute_boundaries(tz_name)

    async with aiosqlite.connect(db_path) as conn:
        # Enforce read-only at the SQLite level — any write attempt raises OperationalError
        await conn.execute("PRAGMA query_only = ON")

        ts_analysis = await analyse_timestamps(conn)
        users       = await calc_users(conn, b)
        cash        = await calc_cash_revenue(conn, b)
        new_payers  = await calc_new_payers(conn, b)
        renewals    = await calc_renewals(conn, b)
        pay_freq    = await calc_payment_frequency(conn)
        plan_mix    = await calc_purchase_plan_mix(conn, b)
        integrity   = await calc_data_integrity(conn, b)
        entitlement = await calc_payment_entitlement(conn)

    # Derived (from already-fetched data — no extra DB round-trip)
    mrr             = calc_mrr(users["active_paid"])
    act_mix         = calc_active_plan_mix(users["active_paid"])
    customer_status = calc_customer_status(users, integrity)
    buyer_metrics   = calc_buyer_metrics(users, cash, pay_freq)
    sanity          = build_sanity_notes(users)

    pricing_simulation = simulate_pricing(act_mix, simulate_prices) if simulate_prices else None

    return {
        "meta": {
            "generated_at_utc":       datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "business_timezone":      tz_name,
            "business_date":          b["business_date"],
            "db_path":                db_path,
            "db_timestamp_convention": ts_analysis["detected_convention"],
        },
        "timestamp_analysis": ts_analysis,
        "boundaries": {
            "today_start":    b["today_start"],
            "tomorrow_start": b["tomorrow_start"],
            "day7_start":     b["day7_start"],
            "day30_start":    b["day30_start"],
            "month_start":    b["month_start"],
            "month_end":      b["month_end"],
            "now_utc":        b["now_utc"],
        },
        "users":               users,
        "customer_status":     customer_status,
        "cash_revenue":        cash,
        "estimated_mrr":       mrr,
        "new_payers":          new_payers,
        "renewals":            renewals,
        "payment_frequency":   pay_freq,
        "purchase_plan_mix":   plan_mix,
        "active_plan_mix":     act_mix,
        "buyer_metrics":       buyer_metrics,
        "payment_entitlement": entitlement,
        "data_integrity":      integrity,
        "pricing_simulation":  pricing_simulation,
        "sanity":              sanity,
    }


# ── Text rendering ────────────────────────────────────────────────────────────

def _rub(v: float) -> str:
    return f"{v:>10,.2f} ₽"


def _sec(title: str) -> str:
    return f"\n{'─' * 62}\n  {title}\n{'─' * 62}"


def _pct_str(val) -> str:
    return f"{val}%" if val is not None else "N/A"


def render_text(m: dict) -> str:
    lines: list[str] = []
    ap  = m["users"]["active_paid"]
    mrr = m["estimated_mrr"]
    di  = m["data_integrity"]
    apm = m["active_plan_mix"]
    ppm = m["purchase_plan_mix"]
    pf  = m["payment_frequency"]
    np_ = m["new_payers"]
    rv  = m["renewals"]
    b   = m["boundaries"]
    cs  = m["customer_status"]
    bm  = m["buyer_metrics"]
    ent = m["payment_entitlement"]

    lines += [
        "",
        "═" * 62,
        "  SWAGA METRICS V0.2",
        f"  Generated : {m['meta']['generated_at_utc'][:16]} UTC",
        f"  Biz date  : {m['meta']['business_date']}  ({m['meta']['business_timezone']})",
        f"  Database  : {m['meta']['db_path']}",
        "═" * 62,
    ]

    # ── TIMESTAMP STORAGE ANALYSIS
    lines.append(_sec("TIMESTAMP STORAGE ANALYSIS"))
    ts = m["timestamp_analysis"]
    lines.append(f"  {'payments.paid_at':30s}: {ts['samples']['payments.paid_at'][0] if ts['samples']['payments.paid_at'] else 'n/a'}")
    lines.append(f"  {'payments.created_at':30s}: {ts['samples']['payments.created_at'][0] if ts['samples']['payments.created_at'] else 'n/a'}")
    lines.append(f"  {'subscriptions.end_date':30s}: {ts['samples']['subscriptions.end_date'][0] if ts['samples']['subscriptions.end_date'] else 'n/a'}")
    lines.append(f"  {'users.reg_date':30s}: {ts['samples']['users.reg_date'][0] if ts['samples']['users.reg_date'] else 'n/a'}")
    lines.append(f"  Detected convention : {ts['detected_convention']}")
    lines.append(f"  Confidence          : {ts['confidence']}")
    lines.append(f"  Period boundaries   : UTC-naive → business TZ midnight converted to UTC")
    lines.append(f"    today_start (UTC) : {b['today_start']}")
    lines.append(f"    month_start (UTC) : {b['month_start']}")

    # ── USERS
    lines.append(_sec("USERS"))
    u = m["users"]
    lines.append(f"  Total real users   : {u['total_real']}")
    lines.append(f"    Telegram         : {u['real_tg']}")
    lines.append(f"    Web              : {u['web']}")
    lines.append(f"  Giveaway synthetic : {u['giveaway_synthetic']}")
    lines.append(f"  Ever paid          : {u['ever_paid']}")
    lines.append(f"  Expired paid       : {u['expired_paid']}")

    # ── CUSTOMER STATUS
    lines.append(_sec("CUSTOMER STATUS"))
    lines.append(f"  Total real users : {cs['total_real']}")
    lines.append(f"  Never paid       : {cs['never_paid']}")
    lines.append(f"  Active free      : {cs['active_free']}  (trial/giveaway, no payment — normal)")
    lines.append(f"  Ever paid        : {cs['ever_paid']}")
    lines.append(f"  Active paid      : {cs['active_paid']}")
    lines.append(f"  Inactive paid    : {cs['inactive_paid']}  (ever paid, subscription now expired)")

    # ── ACTIVE PAID (classification)
    lines.append(_sec("ACTIVE PAID"))
    lines.append(f"  Total      : {ap['total']}")
    lines.append(f"  Exact      : {ap['exact']:>3}  (sub.plan == payment.plan_key)")
    lines.append(f"  Inferred   : {ap['inferred']:>3}  (Bug A: sub.plan='trial', payment is paid plan)")
    lines.append(f"  Unresolved : {ap['unresolved']:>3}  (plan mismatch, cannot reliably determine current tier)")
    if ap["unresolved_detail"]:
        lines.append("  Unresolved users:")
        for e in ap["unresolved_detail"]:
            lines.append(f"    uid={e['user_id']}  sub={e['sub_plan']}  last_pay={e['pay_plan']}  "
                         f"amount={e['amount']}  end={e['end_date'][:10]}")

    # ── CASH REVENUE
    lines.append(_sec("CASH REVENUE  (payments.amount, status='succeeded')"))
    cr = m["cash_revenue"]
    lines.append(f"  Today           : {_rub(cr['today'])}")
    lines.append(f"  Last 7 days     : {_rub(cr['last_7d'])}")
    lines.append(f"  Last 30 days    : {_rub(cr['last_30d'])}")
    lines.append(f"  Current month   : {_rub(cr['current_month'])}")
    lines.append(f"  All time        : {_rub(cr['all_time'])}")

    # ── ESTIMATED MRR
    lines.append(_sec("ESTIMATED MRR  (normalised monthly revenue, active paid subs)"))
    lines.append(f"  Exact MRR       : {_rub(mrr['exact_mrr'])}")
    lines.append(f"  Inferred MRR    : {_rub(mrr['inferred_mrr'])}  ← Bug-A users, plan inferred from payment")
    lines.append(f"  Known MRR total : {_rub(mrr['known_mrr'])}")
    lines.append(f"  Covered users   : {mrr['covered_users']} / {ap['total']}")
    lines.append(f"  MRR coverage    : {mrr['coverage_pct']}%")
    if mrr["unresolved_detail"]:
        lines.append(f"  Unresolved (excluded from MRR):")
        for e in mrr["unresolved_detail"]:
            lines.append(
                f"    uid={e['user_id']}  sub={e['sub_plan']}  last_pay={e['pay_plan']}  "
                f"amount={e['amount']}  paid={e['paid_at'][:10] if e['paid_at'] else '?'}"
            )

    # ── ARPPU
    lines.append(_sec("ARPPU"))
    if mrr["arppu_covered"] is not None:
        lines.append(f"  Estimated ARPPU (covered users)  : {_rub(mrr['arppu_covered'])}")
        lines.append(f"    = Known MRR {_rub(mrr['known_mrr'])} / {mrr['covered_users']} covered users")
    lines.append(f"  Minimum blended ARPPU (all paid) : {_rub(mrr['arppu_lower_bound']) if mrr['arppu_lower_bound'] else 'N/A'}")
    lines.append(f"    = Known MRR / {ap['total']} total active paid (lower bound: unresolved excluded from numerator)")

    # ── BUYER METRICS
    lines.append(_sec("BUYER METRICS"))
    bc = bm["buyer_conversion"]
    lines.append(f"  BUYER CONVERSION")
    lines.append(f"    Ever paid / total real   : {_pct_str(bc['ever_paid_of_real'])}  ({cs['ever_paid']}/{cs['total_real']})")
    lines.append(f"    Active paid / total real : {_pct_str(bc['active_paid_of_real'])}  ({cs['active_paid']}/{cs['total_real']})")
    lines.append(f"")
    lines.append(f"  ACTIVE BUYER RATE  (active paid / ever paid — NOT retention)")
    lines.append(f"    {_pct_str(bm['active_buyer_rate'])}  ({cs['active_paid']}/{cs['ever_paid']})")
    lines.append(f"")
    lines.append(f"  REPEAT BUYER RATE  (2+ payments / ever paid — NOT renewal rate)")
    lines.append(f"    {_pct_str(bm['repeat_buyer_rate'])}")
    lines.append(f"")
    hfb = bm["high_frequency_buyers"]
    lines.append(f"  HIGH-FREQUENCY BUYERS  (of {cs['ever_paid']} ever paid)")
    lines.append(f"    3+ payments : {hfb['3plus']['count']} users  ({hfb['3plus']['pct_of_ever_paid']}%)")
    lines.append(f"    4+ payments : {hfb['4plus']['count']} users  ({hfb['4plus']['pct_of_ever_paid']}%)")
    lines.append(f"    5+ payments : {hfb['5plus']['count']} users  ({hfb['5plus']['pct_of_ever_paid']}%)")
    lines.append(f"")
    lines.append(f"  CASH ARPPU HISTORICAL  (Realized Revenue per Historical Payer)")
    arppu_hist = bm["cash_arppu_historical"]
    if arppu_hist is not None:
        lines.append(f"    {_rub(arppu_hist)}")
        lines.append(f"    = {_rub(bm['all_time_cash'])} all-time / {bm['ever_paid']} ever-paid users")
    else:
        lines.append(f"    N/A")

    # ── NEW PAYERS
    lines.append(_sec("NEW PAYERS  (first succeeded payment in period)"))
    lines.append(f"  Today          : {np_['today']}")
    lines.append(f"  Last 7 days    : {np_['last_7d']}")
    lines.append(f"  Last 30 days   : {np_['last_30d']}")
    lines.append(f"  Current month  : {np_['current_month']}")

    # ── RENEWAL EVENTS
    lines.append(_sec("RENEWAL EVENTS  (each non-first payment = 1 event)"))
    re = rv["events"]
    lines.append(f"  Today          : {re['today']}")
    lines.append(f"  Last 7 days    : {re['last_7d']}")
    lines.append(f"  Last 30 days   : {re['last_30d']}")
    lines.append(f"  Current month  : {re['current_month']}")

    # ── RENEWING USERS
    lines.append(_sec("RENEWING USERS  (distinct users with ≥1 renewal event in period)"))
    ru = rv["users"]
    lines.append(f"  Today          : {ru['today']}")
    lines.append(f"  Last 7 days    : {ru['last_7d']}")
    lines.append(f"  Last 30 days   : {ru['last_30d']}")
    lines.append(f"  Current month  : {ru['current_month']}")

    # ── PAYMENT FREQUENCY
    lines.append(_sec("PAYMENT FREQUENCY  (succeeded payments per paying user)"))
    for key in ["1", "2", "3", "4", "5+"]:
        cnt = pf["distribution"].get(key, 0)
        lines.append(f"  {key} payment{'s' if key != '1' else ' '}  : {cnt} users")
    if pf["avg"]    is not None: lines.append(f"  Average        : {pf['avg']}")
    if pf["median"] is not None: lines.append(f"  Median         : {pf['median']}")

    # ── PURCHASE PLAN MIX
    lines.append(_sec("PURCHASE PLAN MIX  (transactions, payments.plan_key)"))
    header = f"  {'Period':<18} {'1m':>6} {'3m':>6} {'1y':>6}"
    lines.append(header)
    lines.append("  " + "─" * 38)
    for period_key, label in [
        ("today", "Today"), ("last_7d", "Last 7d"), ("last_30d", "Last 30d"),
        ("current_month", "Current month"), ("all_time", "All time"),
    ]:
        d = ppm[period_key]
        lines.append(f"  {label:<18} {d['1m']:>6} {d['3m']:>6} {d['1y']:>6}")

    # ── ACTIVE PLAN MIX
    lines.append(_sec("ACTIVE PLAN MIX  (current active paid users by effective plan)"))
    lines.append(f"  {'Plan':<6} {'Exact':>6} {'Inferred':>9}  {'Total':>6}")
    lines.append("  " + "─" * 32)
    for plan in PAID_PLANS:
        d = apm["by_plan"][plan]
        total_plan = d["exact"] + d["inferred"]
        inf_note = f" [{d['inferred']} inferred]" if d["inferred"] else ""
        lines.append(f"  {plan:<6} {d['exact']:>6} {d['inferred']:>9}  {total_plan:>6}{inf_note}")
    lines.append(f"  {'TOTAL':<6} {apm['exact']:>6} {apm['inferred']:>9}  {apm['exact']+apm['inferred']:>6}")
    lines.append(f"  Unresolved : {apm['unresolved']}")

    # ── PAYMENT ENTITLEMENT
    lines.append(_sec("PAYMENT ENTITLEMENT  (payment ↔ subscription start match)"))
    lines.append(f"  Total payments : {ent['total_payments']}")
    lines.append(f"  Confirmed      : {ent['confirmed']}  ({ent['confirmed_pct']}%)  — sub start within [-1h,+24h] of paid_at")
    lines.append(f"  Suspicious     : {ent['suspicious']}  ({ent['suspicious_pct']}%)  — no matching sub start (mostly renewals)")
    lines.append(f"  Unverifiable   : {ent['unverifiable']}  — NULL paid_at or no subscription record")
    lines.append(f"  Note: {ent['note']}")

    # ── DATA INTEGRITY
    lines.append(_sec("DATA INTEGRITY"))

    di_af = di["active_free_without_payment"]
    lines.append(f"  Active free sub, no payment (trial/giveaway — NORMAL)")
    lines.append(f"    Count: {di_af['count']}  |  {di_af['note']}")
    if di_af["user_ids"]:
        lines.append(f"    uids: {di_af['user_ids']}")

    di_pp = di["paid_plan_without_payment"]
    lines.append(f"  Active paid plan, no payment (ERROR)")
    lines.append(f"    Count: {di_pp['count']}  |  {di_pp['note']}")
    if di_pp["user_ids"]:
        lines.append(f"    uids: {di_pp['user_ids']}")

    checks = [
        ("paid_user_with_active_plan_trial",        "Paid user with active plan='trial' (Bug A)"),
        ("duplicate_active_subscriptions_per_user", "Duplicate active subscriptions per user"),
        ("succeeded_payments_without_paid_at",      "Succeeded payments without paid_at"),
        ("active_subscription_expired_by_date",     "Active sub expired by date (scheduler gap)"),
    ]
    for key, label in checks:
        entry  = di[key]
        cnt    = entry["count"]
        ids    = entry.get("user_ids", [])
        id_str = f"  uids: {ids}" if ids else ""
        lines.append(f"  {label:<50}: {cnt}{id_str}")

    lines.append(f"  {'Subscription duration >400d (non-giveaway)':<50}: "
                 f"{di['suspicious_subscription_duration_gt_400_days']['count']}")
    for row in di["suspicious_subscription_duration_gt_400_days"]["detail"]:
        lines.append(
            f"    uid={row['user_id']}  plan={row['plan']}  "
            f"{row['start_date'][:10]}→{row['end_date'][:10]}  ({row['duration_days']}d)"
        )

    mm = di["plan_mismatch_needs_manual_review"]
    lines.append(f"  {'Plan mismatch (needs manual review)':<50}: {mm['count']}")
    for row in mm["detail"]:
        lines.append(
            f"    uid={row['user_id']}  sub={row['sub_plan']}  last_pay={row['pay_plan']}  "
            f"amount={row['amount']}  paid={row['paid_at'][:10] if row['paid_at'] else '?'}  "
            f"end={row['sub_end'][:10]}"
        )

    # ── PRICING SIMULATOR (only if --simulate-pricing was passed)
    ps = m.get("pricing_simulation")
    if ps is not None:
        if "error" in ps:
            lines.append(_sec("PRICING SIMULATOR"))
            lines.append(f"  ERROR: {ps['error']}")
        else:
            lines.append(_sec(
                f"PRICING SIMULATOR  "
                f"(1m={ps['input_prices']['1m']:.0f} ₽  "
                f"3m={ps['input_prices']['3m']:.0f} ₽  "
                f"1y={ps['input_prices']['1y']:.0f} ₽)"
            ))
            lines.append(f"  Monthly-equivalent prices & active mix:")
            for p in PAID_PLANS:
                cnt = ps["plan_mix_counts"][p]
                pct = ps["plan_mix_pct"][p]
                mth = ps["monthly_equiv"][p]
                lines.append(f"    {p}: {mth:>7.2f} ₽/mo  ({cnt} users, {pct}% of mix)")
            lines.append(f"  Covered users (exact + inferred) : {ps['covered_users']}")
            lines.append(f"  Effective ARPU  : {_rub(ps['effective_arpu'])}")
            lines.append(f"  Simulated MRR   : {_rub(ps['simulated_mrr'])}  (at current {ps['covered_users']} paying users)")
            lines.append(f"")
            lines.append(f"  Customers needed to hit MRR target:")
            for target, needed in ps["customers_for_mrr_target"].items():
                t_str      = f"{target:>9,.0f} ₽/mo"
                needed_str = f"{needed:>7}" if needed is not None else "    N/A"
                lines.append(f"    {t_str} → {needed_str} paying users")

    # ── SANITY CHECK
    lines.append(_sec("SANITY CHECK  (vs manual audit baseline 2026-08-25)"))
    for note in m["sanity"]:
        prefix = "  ✓" if note.startswith("All key") else "  ⚠"
        lines.append(f"{prefix} {note}")

    # ── RELIABILITY NOTES
    lines.append(_sec("RELIABILITY NOTES"))
    lines.append("  RELIABLE (no inference):")
    for item in [
        "Cash Revenue — direct sum of payments.amount",
        "Ever paid — COUNT DISTINCT from payments",
        "Active paid total — succeeded payment + active subscription JOIN",
        "New payers — MIN(paid_at) per user, unambiguous",
        "Renewal events/users — payment rank > 1, unambiguous",
        "Payment frequency — COUNT per user, unambiguous",
        "Customer status — derived from above counts",
        "Buyer metrics — derived from above counts",
        "Data integrity — pure SELECTs, no mutation",
    ]:
        lines.append(f"    ✓ {item}")

    lines.append("  PARTIALLY RELIABLE (inference documented inline):")
    for item in [
        "MRR inferred (14 users): sub.plan='trial'; last payment used as proxy",
        "Active plan mix: same 14 users classified from payment.plan_key",
        "Payment entitlement 'suspicious': renewals have no new sub start_date (expected)",
    ]:
        lines.append(f"    ~ {item}")

    lines.append("  NOT RELIABLY COMPUTABLE from current schema:")
    for item in [
        "Renewal Rate % — denominator not defined (annual users not yet renewal-eligible)",
        "Trial→Paid conversion — trial_used flag polluted by giveaway/web paths",
        "Promo impact — net amount only; discount not stored separately",
        "Per-server revenue — server_id set at payment creation, not updated on migration",
        "LTV — insufficient longitudinal data; no churn model",
    ]:
        lines.append(f"    ✗ {item}")

    lines += ["", "═" * 62, ""]
    return "\n".join(lines)


# ── JSON serialisation ────────────────────────────────────────────────────────

def _make_serializable(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable types."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def render_json(m: dict) -> str:
    return _json.dumps(_make_serializable(m), ensure_ascii=False, indent=2)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SWAGA VPN Metrics v0.2 — read-only analytics"
    )
    parser.add_argument("--db",   default=DB_PATH, help="Path to vpn_bot.db")
    parser.add_argument("--tz",   default=BUSINESS_TIMEZONE, help="Business timezone (IANA name)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of text")
    parser.add_argument(
        "--simulate-pricing",
        nargs=3, type=float, metavar=("P1M", "P3M", "P1Y"),
        help="Pricing simulation: monthly prices for 1m, 3m, 1y plans (e.g. 149 419 1390)",
    )
    args = parser.parse_args()

    metrics = asyncio.run(collect_metrics(args.db, args.tz, args.simulate_pricing))

    if args.json:
        print(render_json(metrics))
    else:
        print(render_text(metrics))


if __name__ == "__main__":
    main()
