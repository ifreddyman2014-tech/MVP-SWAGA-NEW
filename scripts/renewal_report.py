"""
H5-MINI Renewal Attribution Report — read-only, never writes to DB.

Usage:
    python3 scripts/renewal_report.py

Output:
    Historical baseline (pre-H3): renewal rate within [-14d, +7d] window
    Post-H3 attribution: breakdown by renew_source for attributed payments
"""
import sys, os, sqlite3
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vpn_bot.db")

_WINDOW_DAYS_BEFORE = 14
_WINDOW_DAYS_AFTER = 7

# H3 deployed ~2026-09-18 (first commit with renew_cta_kb)
H3_DEPLOY_DATE = "2026-09-18"


def _conn():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def historical_baseline(con: sqlite3.Connection) -> dict:
    """
    Pre-H3 renewal rate.
    Eligible cycle: paid plan (1m/3m/1y), prior paid payment exists,
    observation window complete (end_date + 7d <= today).
    Renewed: another succeeded payment in [end_date - 14d, end_date + 7d].
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = con.execute("""
        SELECT
            s.user_id,
            s.plan,
            s.end_date,
            (SELECT COUNT(*) FROM payments p2
             WHERE p2.user_id = s.user_id
               AND p2.status = 'succeeded'
               AND p2.plan_key IN ('1m','3m','1y')
               AND p2.paid_at < s.start_date
            ) AS prior_payments,
            (SELECT COUNT(*) FROM payments p3
             WHERE p3.user_id = s.user_id
               AND p3.status = 'succeeded'
               AND p3.plan_key IN ('1m','3m','1y')
               AND p3.paid_at >= date(s.end_date, '-14 days')
               AND p3.paid_at <= date(s.end_date, '+7 days')
               AND p3.created_at < ?
            ) AS renewals_in_window
        FROM subscriptions s
        WHERE s.plan IN ('1m','3m','1y')
          AND date(s.end_date, '+7 days') < ?
          AND s.start_date < ?
    """, (H3_DEPLOY_DATE, today, H3_DEPLOY_DATE)).fetchall()

    eligible = [r for r in rows if r["prior_payments"] > 0]
    renewed = [r for r in eligible if r["renewals_in_window"] > 0]
    return {
        "total_cycles": len(rows),
        "eligible": len(eligible),
        "renewed": len(renewed),
        "rate": f"{len(renewed)/len(eligible)*100:.0f}%" if eligible else "n/a (0 eligible)",
    }


def attribution_breakdown(con: sqlite3.Connection) -> list[dict]:
    """
    Post-H3: group succeeded payments by renew_source.
    NULL = ordinary purchase or unattributed.
    """
    rows = con.execute("""
        SELECT
            COALESCE(renew_source, 'NULL (unattributed)') AS source,
            COUNT(*) AS payments,
            SUM(amount) AS revenue
        FROM payments
        WHERE status = 'succeeded'
          AND plan_key IN ('1m','3m','1y')
          AND paid_at >= ?
        GROUP BY renew_source
        ORDER BY payments DESC
    """, (H3_DEPLOY_DATE,)).fetchall()
    return [dict(r) for r in rows]


def pending_first_cohort(con: sqlite3.Connection) -> list[dict]:
    """
    Pending payments (not yet succeeded) with a renew_source — first attributed cohort.
    """
    rows = con.execute("""
        SELECT payment_id, user_id, plan_key, renew_source, created_at
        FROM payments
        WHERE status = 'pending'
          AND renew_source IS NOT NULL
          AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT 20
    """, (H3_DEPLOY_DATE,)).fetchall()
    return [dict(r) for r in rows]


def main():
    with _conn() as con:
        con.execute("PRAGMA query_only = ON")

        bl = historical_baseline(con)
        attr = attribution_breakdown(con)
        pending = pending_first_cohort(con)

    print("=" * 60)
    print("H5-MINI RENEWAL ATTRIBUTION REPORT")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print("=" * 60)

    print("\n── HISTORICAL BASELINE (pre-H3, before 2026-09-18) ──")
    print(f"  Subscription cycles examined : {bl['total_cycles']}")
    print(f"  Eligible (prior paid payment): {bl['eligible']}")
    print(f"  Renewed in [-14d, +7d] window: {bl['renewed']}")
    print(f"  Renewal rate                 : {bl['rate']}")

    print("\n── POST-H3 ATTRIBUTION (succeeded payments, by renew_source) ──")
    if attr:
        print(f"  {'Source':<28} {'Payments':>8} {'Revenue':>10}")
        print(f"  {'-'*28} {'-'*8} {'-'*10}")
        for row in attr:
            print(f"  {row['source']:<28} {row['payments']:>8} {row['revenue']:>9.0f}₽")
    else:
        print("  No succeeded payments since H3 deploy.")

    print("\n── PENDING ATTRIBUTED PAYMENTS (first cohort) ──")
    if pending:
        for row in pending:
            print(f"  {row['payment_id'][:20]:<22} user={row['user_id']:<12} "
                  f"plan={row['plan_key']:<4} source={row['renew_source']}")
    else:
        print("  None yet.")

    print()


if __name__ == "__main__":
    main()
