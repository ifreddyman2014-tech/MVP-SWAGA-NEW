#!/usr/bin/env python3
"""
Dry-run migration: fix plan='trial' for users who have paid.

Identifies active subscriptions where plan='trial' but the user has a
succeeded payment, then proposes correcting the plan field to match
the last succeeded payment's plan_key.

Rules:
  - Only considers active subscriptions (is_active=1).
  - Never changes end_date.
  - If a user has multiple payments with different plan_keys, flags
    as AMBIGUOUS and skips (manual review required).
  - Idempotent: safe to run multiple times.
  - Default mode: DRY RUN (prints proposed changes, no DB writes).
  - Pass --apply to commit changes inside a transaction with a pre-check.

Usage:
    python scripts/migration_fix_plan.py [--apply] [--user USER_ID]

Exit codes: 0 = nothing to fix, 1 = fixes proposed/applied, 2 = error
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiosqlite


async def run(db_path: str, apply: bool, target_user: int | None):
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Active trial subscriptions
        cur = await db.execute("""
            SELECT s.sub_id, s.user_id, s.plan, s.end_date, s.is_active
            FROM subscriptions s
            WHERE s.plan = 'trial'
              AND s.is_active = 1
              AND (? IS NULL OR s.user_id = ?)
        """, (target_user, target_user))
        trial_subs = [dict(r) for r in await cur.fetchall()]

        if not trial_subs:
            print("No active trial subscriptions found.")
            return 0

        print(f"Active trial subs found: {len(trial_subs)}")

        to_fix = []
        ambiguous = []
        no_payment = []

        for sub in trial_subs:
            uid = sub["user_id"]
            # Get all succeeded payments for this user
            cur = await db.execute("""
                SELECT plan_key, paid_at, amount
                FROM payments
                WHERE user_id = ?
                  AND status = 'succeeded'
                ORDER BY paid_at DESC
            """, (uid,))
            payments = [dict(r) for r in await cur.fetchall()]

            if not payments:
                no_payment.append(sub)
                continue

            # Distinct paid plan_keys (excluding 'trial' if somehow present)
            paid_plans = list(dict.fromkeys(
                p["plan_key"] for p in payments
                if p["plan_key"] not in ("trial", "giveaway_7d", "giveaway_365d")
            ))

            if not paid_plans:
                no_payment.append(sub)
                continue

            if len(paid_plans) > 1:
                ambiguous.append({
                    "sub": sub,
                    "paid_plans": paid_plans,
                    "payments": payments,
                })
                continue

            to_fix.append({
                "sub_id": sub["sub_id"],
                "user_id": uid,
                "current_plan": sub["plan"],
                "new_plan": paid_plans[0],
                "end_date": sub["end_date"],
                "last_payment": payments[0],
            })

        print(f"\n── Results ──")
        print(f"  To fix      : {len(to_fix)}")
        print(f"  Ambiguous   : {len(ambiguous)}  ← manual review needed")
        print(f"  No payment  : {len(no_payment)}  ← legitimately free / trial")

        if to_fix:
            print(f"\n── Proposed fixes ──")
            for fix in to_fix:
                lp = fix["last_payment"]
                print(f"  user={fix['user_id']} sub={fix['sub_id']} "
                      f"plan: trial → {fix['new_plan']} "
                      f"(end={fix['end_date']}, last_paid={lp['paid_at']}, {lp['amount']}₽)")

        if ambiguous:
            print(f"\n── Ambiguous (SKIPPED — manual review) ──")
            for item in ambiguous:
                sub = item["sub"]
                print(f"  user={sub['user_id']} sub={sub['sub_id']} "
                      f"end={sub['end_date']} plans={item['paid_plans']}")

        if not to_fix:
            print("\nNothing to apply.")
            return 0

        if not apply:
            print(f"\n[DRY RUN] Pass --apply to commit {len(to_fix)} change(s).")
            return 1

        # Apply inside a transaction with pre-check
        print(f"\nApplying {len(to_fix)} fix(es) inside transaction...")
        async with db.execute("BEGIN") as _:
            pass  # aiosqlite: use explicit transaction
        await db.execute("BEGIN")
        try:
            applied = 0
            for fix in to_fix:
                # Pre-check: still trial and still active
                cur = await db.execute("""
                    SELECT plan, is_active FROM subscriptions WHERE sub_id = ?
                """, (fix["sub_id"],))
                row = await cur.fetchone()
                if not row:
                    print(f"  [SKIP] sub {fix['sub_id']} not found")
                    continue
                if row["is_active"] != 1:
                    print(f"  [SKIP] sub {fix['sub_id']} no longer active")
                    continue
                if row["plan"] != "trial":
                    print(f"  [SKIP] sub {fix['sub_id']} plan already changed to {row['plan']}")
                    continue

                await db.execute("""
                    UPDATE subscriptions SET plan = ? WHERE sub_id = ?
                """, (fix["new_plan"], fix["sub_id"]))
                print(f"  ✅ user={fix['user_id']} sub={fix['sub_id']} "
                      f"trial → {fix['new_plan']}")
                applied += 1

            await db.commit()
            print(f"\n{applied} row(s) updated. Transaction committed.")
            return 1 if applied > 0 else 0

        except Exception as e:
            await db.rollback()
            print(f"\n[ERROR] Rolling back: {e}", file=sys.stderr)
            return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes (default is dry-run)")
    parser.add_argument("--user", type=int, metavar="USER_ID",
                        help="Limit to a specific user_id")
    args = parser.parse_args()

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(here, "vpn_bot.db")

    if not os.path.exists(db_path):
        print(f"[ERROR] DB not found: {db_path}", file=sys.stderr)
        sys.exit(2)

    if args.apply:
        answer = input(
            f"About to write to {db_path}. "
            "Type 'yes' to continue: "
        ).strip().lower()
        if answer != "yes":
            print("Cancelled.")
            sys.exit(0)

    rc = asyncio.run(run(db_path, args.apply, args.user))
    sys.exit(rc)


if __name__ == "__main__":
    main()
