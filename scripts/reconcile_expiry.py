#!/usr/bin/env python3
"""
Dry-run tool: compare DB subscription expiry vs 3X-UI actual expiry.

Reads active subscriptions from DB, fetches client list from each 3X-UI
panel, and reports mismatches. US2/us2-ws are never touched.

Usage:
    python scripts/reconcile_expiry.py [--apply UUID] [--server SERVER_ID]

Options:
    --apply UUID      Apply fix for a single client (only after dry-run review)
    --server SERVER   Limit report to one server ID

Exit codes: 0 = no mismatches, 1 = mismatches found, 2 = error
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import aiosqlite

# Protected servers — never reconcile or apply
EXCLUDED_SERVER_IDS = {"us2", "us2-ws"}

# Tolerance: differences below this are ignored (clock skew, rounding)
TOLERANCE_SECONDS = 300


def _load_servers():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "servers.json")
    with open(path) as f:
        return json.load(f)


def _fetch_inbound_clients(server: dict) -> list[dict] | None:
    """
    Fetch client list from 3X-UI panel for the given server dict.
    Returns list of client dicts (with 'id', 'email', 'expiryTime', 'enable')
    or None on error.
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from xui_api import XUIAPI

    transport = server.get("transport", "tcp")
    if transport == "ws":
        return None  # WS servers don't store expiry in panel

    xui = XUIAPI.__new__(XUIAPI)
    import requests
    xui.session = requests.Session()
    protocol = "https" if server.get("xui_ssl", True) else "http"
    xui.base_url = f"{protocol}://{server['xui_host']}:{server['xui_port']}{server['xui_web_path']}"
    xui._logged_in = False

    if not xui.login(server["xui_username"], server["xui_password"]):
        print(f"  [ERROR] auth failed on {server['id']}", file=sys.stderr)
        return None

    inbound_id = server["inbound_id"]
    try:
        resp = xui.session.get(
            xui._url(f"panel/api/inbounds/get/{inbound_id}"),
            verify=False, timeout=15,
        )
        data = resp.json()
        if not data.get("success"):
            print(f"  [ERROR] get inbound failed on {server['id']}: {data.get('msg')}", file=sys.stderr)
            return None
        obj = data.get("obj", {})
        settings_raw = obj.get("settings", "{}")
        settings = json.loads(settings_raw)
        return settings.get("clients", [])
    except Exception as e:
        print(f"  [ERROR] exception fetching inbound {server['id']}: {e}", file=sys.stderr)
        return None


async def _load_db_subscriptions(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT sub_id, user_id, vless_uuid, xui_email, xui_sub_id,
                   server_id, end_date, plan, is_active
            FROM subscriptions
            WHERE is_active = 1
              AND vless_uuid IS NOT NULL
              AND vless_uuid != ''
        """)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


def _end_date_to_ms(end_date_str: str) -> int:
    """Convert ISO datetime string (no tz) to UTC milliseconds."""
    dt = datetime.fromisoformat(end_date_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _ms_to_str(ms: int) -> str:
    if ms <= 0:
        return "unlimited"
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", metavar="UUID",
                        help="Apply expiry fix for this UUID (dry-run is the default)")
    parser.add_argument("--server", metavar="SERVER_ID",
                        help="Limit to a specific server ID")
    args = parser.parse_args()

    servers = _load_servers()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(here, "vpn_bot.db")

    db_subs = asyncio.run(_load_db_subscriptions(db_path))
    db_by_uuid = {s["vless_uuid"]: s for s in db_subs}

    mismatches = []
    missing_in_panel = []

    target_servers = [
        s for s in servers
        if s["id"] not in EXCLUDED_SERVER_IDS
        and s.get("enabled", True)
        and s.get("transport", "tcp") != "ws"
        and (args.server is None or s["id"] == args.server)
    ]

    for srv in target_servers:
        print(f"\n── Server: {srv['id']} ({srv.get('name', '')}) ──")
        clients = _fetch_inbound_clients(srv)
        if clients is None:
            print("  [SKIP] could not fetch clients")
            continue
        print(f"  {len(clients)} clients in panel")

        panel_by_uuid = {c["id"]: c for c in clients}

        # Check each DB subscription against panel
        for sub in db_subs:
            if sub["server_id"] != srv["id"] and sub.get("vless_uuid") not in panel_by_uuid:
                continue  # different primary server, skip if not in this panel
            if sub["vless_uuid"] not in panel_by_uuid:
                if sub["server_id"] == srv["id"]:
                    missing_in_panel.append({
                        "server": srv["id"],
                        "uuid": sub["vless_uuid"],
                        "email": sub.get("xui_email", ""),
                        "db_end": sub["end_date"],
                        "plan": sub["plan"],
                    })
                continue

            panel_client = panel_by_uuid[sub["vless_uuid"]]
            panel_expiry_ms = panel_client.get("expiryTime", 0)
            db_expiry_ms = _end_date_to_ms(sub["end_date"])

            diff_s = abs(panel_expiry_ms - db_expiry_ms) / 1000
            if diff_s > TOLERANCE_SECONDS:
                mismatches.append({
                    "server": srv["id"],
                    "uuid": sub["vless_uuid"],
                    "email": sub.get("xui_email", ""),
                    "plan": sub["plan"],
                    "db_end_date": sub["end_date"],
                    "db_expiry_ms": db_expiry_ms,
                    "panel_expiry_ms": panel_expiry_ms,
                    "diff_days": (db_expiry_ms - panel_expiry_ms) / 86400000,
                    "inbound_id": srv["inbound_id"],
                    "sub_id": sub.get("xui_sub_id", ""),
                    "flow": srv.get("flow", ""),
                    "srv": srv,
                })

    print("\n" + "=" * 60)
    print(f"SUMMARY — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print(f"Servers checked : {len(target_servers)}")
    print(f"DB active subs  : {len(db_subs)}")
    print(f"Expiry mismatches: {len(mismatches)}")
    print(f"Missing in panel : {len(missing_in_panel)}")

    if mismatches:
        print("\n── Expiry mismatches ──")
        for m in mismatches:
            db_str = _ms_to_str(m["db_expiry_ms"])
            pan_str = _ms_to_str(m["panel_expiry_ms"])
            diff = m["diff_days"]
            sign = "+" if diff > 0 else ""
            print(f"  [{m['server']}] {m['email']} | "
                  f"DB: {db_str} | Panel: {pan_str} | "
                  f"Δ {sign}{diff:.1f}d | plan={m['plan']}")

    if missing_in_panel:
        print("\n── Missing in panel (primary server) ──")
        for m in missing_in_panel:
            print(f"  [{m['server']}] {m['email']} | DB end: {m['db_end']} | plan={m['plan']}")

    # Apply mode
    if args.apply:
        uuid = args.apply
        target = next((m for m in mismatches if m["uuid"] == uuid), None)
        if not target:
            print(f"\n[ERROR] UUID {uuid} not found in mismatches list.", file=sys.stderr)
            sys.exit(2)
        srv = target["srv"]
        print(f"\n── Applying fix for {uuid} on {srv['id']} ──")
        answer = input("Confirm (yes/no): ").strip().lower()
        if answer != "yes":
            print("Cancelled.")
            sys.exit(0)
        from xui_api import XUIAPI
        import requests
        xui = XUIAPI.__new__(XUIAPI)
        xui.session = requests.Session()
        protocol = "https" if srv.get("xui_ssl", True) else "http"
        xui.base_url = f"{protocol}://{srv['xui_host']}:{srv['xui_port']}{srv['xui_web_path']}"
        xui._logged_in = False
        if not xui.login(srv["xui_username"], srv["xui_password"]):
            print("[ERROR] auth failed", file=sys.stderr)
            sys.exit(2)
        ok = xui.update_client(
            target["inbound_id"], uuid, target["email"],
            sub_id=target["sub_id"],
            expiry_time=target["db_expiry_ms"],
            flow=target["flow"],
        )
        print("Done." if ok else "[FAILED]")
        sys.exit(0 if ok else 2)

    sys.exit(1 if (mismatches or missing_in_panel) else 0)


if __name__ == "__main__":
    main()
