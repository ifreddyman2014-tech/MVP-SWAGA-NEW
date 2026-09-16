#!/usr/bin/env python3
"""
Dry-run tool: compare DB subscription expiry vs 3X-UI actual expiry.

Reads active subscriptions from DB, fetches client list from each 3X-UI
panel, and reports mismatches. US2/us2-ws are NEVER touched.

WS servers are excluded because they store no expiry in the 3X-UI panel:
their expiry lives only in the DB and the standalone xray-ws config.
Reconciling WS clients requires ws_manager, not this script.

Usage:
    python scripts/reconcile_expiry.py [--server SERVER_ID]
    python scripts/reconcile_expiry.py --apply UUID --server SERVER_ID

Options:
    --apply UUID      Apply expiry fix for a single client.
                      Requires --server (UUID is not unique across servers).
    --server SERVER   Limit report to one server ID. Required with --apply.

Exit codes: 0 = no mismatches, 1 = mismatches found, 2 = error

Safety rules enforced in --apply mode:
  1. UUID must be unambiguous (either one server has it, or --server is given).
  2. DB state is re-read immediately before writing to the panel.
  3. Panel expiry is NEVER shrunk: fix is skipped if panel already >= DB end_date.
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
        data = json.load(f)
    # servers.json may be {"servers": [...]} or a bare list
    return data.get("servers", data) if isinstance(data, dict) else data


def _fetch_inbound_clients(server: dict) -> list[dict] | None:
    """
    Fetch client list from 3X-UI panel for the given server dict.
    Returns list of client dicts (with 'id', 'email', 'expiryTime', 'enable')
    or None on error.

    Returns None for WS transport: WS servers don't store expiry in the panel.
    Expiry for WS clients lives in the standalone xray-ws config (ws_manager).
    """
    from xui_api import XUIAPI
    import requests

    transport = server.get("transport", "tcp")
    if transport == "ws":
        return None

    xui = XUIAPI.__new__(XUIAPI)
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


async def _reread_db_end_date(db_path: str, vless_uuid: str) -> str | None:
    """Re-read the current end_date for a UUID from DB immediately before applying."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT end_date FROM subscriptions
            WHERE vless_uuid = ? AND is_active = 1
            ORDER BY end_date DESC LIMIT 1
        """, (vless_uuid,))
        row = await cur.fetchone()
        return row["end_date"] if row else None


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
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", metavar="UUID",
                        help="Apply expiry fix for this UUID (dry-run is the default). Requires --server.")
    parser.add_argument("--server", metavar="SERVER_ID",
                        help="Limit report to a specific server ID. Required with --apply.")
    args = parser.parse_args()

    if args.apply and not args.server:
        print("[ERROR] --apply requires --server (UUID is not unique across servers).",
              file=sys.stderr)
        sys.exit(2)

    servers = _load_servers()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(here, "vpn_bot.db")

    db_subs = asyncio.run(_load_db_subscriptions(db_path))

    # Records where DB end_date > panel expiry (panel needs updating — safe to apply)
    mismatches = []
    # Records where panel expiry > DB end_date (informational — never apply)
    panel_ahead = []
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
            print("  [SKIP] could not fetch clients (WS server or auth error)")
            continue
        print(f"  {len(clients)} clients in panel")

        panel_by_uuid = {c["id"]: c for c in clients}

        for sub in db_subs:
            uuid = sub["vless_uuid"]
            if uuid not in panel_by_uuid:
                if sub["server_id"] == srv["id"]:
                    missing_in_panel.append({
                        "server": srv["id"],
                        "uuid": uuid,
                        "email": sub.get("xui_email", ""),
                        "db_end": sub["end_date"],
                        "plan": sub["plan"],
                    })
                continue

            panel_client = panel_by_uuid[uuid]
            panel_expiry_ms = panel_client.get("expiryTime", 0)
            db_expiry_ms = _end_date_to_ms(sub["end_date"])

            diff_ms = db_expiry_ms - panel_expiry_ms
            if abs(diff_ms) <= TOLERANCE_SECONDS * 1000:
                continue  # within tolerance

            entry = {
                "server": srv["id"],
                "uuid": uuid,
                "email": sub.get("xui_email", ""),
                "plan": sub["plan"],
                "db_end_date": sub["end_date"],
                "db_expiry_ms": db_expiry_ms,
                "panel_expiry_ms": panel_expiry_ms,
                "diff_days": diff_ms / 86_400_000,
                "inbound_id": srv["inbound_id"],
                "sub_id": sub.get("xui_sub_id", ""),
                "flow": srv.get("flow", ""),
                "srv": srv,
            }
            if diff_ms > 0:
                mismatches.append(entry)   # DB ahead → panel needs update
            else:
                panel_ahead.append(entry)  # panel ahead → informational only

    print("\n" + "=" * 60)
    print(f"SUMMARY — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print(f"Servers checked    : {len(target_servers)}")
    print(f"DB active subs     : {len(db_subs)}")
    print(f"Panel behind DB    : {len(mismatches)}  ← can --apply")
    print(f"Panel ahead of DB  : {len(panel_ahead)}  ← informational, never apply")
    print(f"Missing in panel   : {len(missing_in_panel)}")

    if mismatches:
        print("\n── Panel behind DB (expiry too early) ──")
        for m in mismatches:
            db_str = _ms_to_str(m["db_expiry_ms"])
            pan_str = _ms_to_str(m["panel_expiry_ms"])
            print(f"  [{m['server']}] {m['email']} | "
                  f"DB: {db_str} | Panel: {pan_str} | "
                  f"Δ +{m['diff_days']:.1f}d | plan={m['plan']}")

    if panel_ahead:
        print("\n── Panel ahead of DB (do NOT apply — would shrink) ──")
        for m in panel_ahead:
            db_str = _ms_to_str(m["db_expiry_ms"])
            pan_str = _ms_to_str(m["panel_expiry_ms"])
            print(f"  [{m['server']}] {m['email']} | "
                  f"DB: {db_str} | Panel: {pan_str} | "
                  f"Δ {m['diff_days']:.1f}d | plan={m['plan']}")

    if missing_in_panel:
        print("\n── Missing in panel (primary server) ──")
        for m in missing_in_panel:
            print(f"  [{m['server']}] {m['email']} | DB end: {m['db_end']} | plan={m['plan']}")

    # Apply mode
    if args.apply:
        uuid = args.apply
        # Find all mismatches for this UUID (should be exactly one if --server was given)
        targets = [m for m in mismatches if m["uuid"] == uuid]
        if not targets:
            print(f"\n[ERROR] UUID {uuid} not found in mismatches for server={args.server}. "
                  "Run without --apply first to see the mismatch list.", file=sys.stderr)
            sys.exit(2)
        if len(targets) > 1:
            servers_list = [t["server"] for t in targets]
            print(f"\n[ERROR] UUID {uuid} appears in mismatches on multiple servers: {servers_list}. "
                  "Specify --server to disambiguate.", file=sys.stderr)
            sys.exit(2)

        target = targets[0]
        srv = target["srv"]
        print(f"\n── Applying fix for {uuid} on {srv['id']} ──")
        print(f"  DB end_date  : {target['db_end_date']} ({_ms_to_str(target['db_expiry_ms'])})")
        print(f"  Panel expiry : {_ms_to_str(target['panel_expiry_ms'])}")
        print(f"  Delta        : +{target['diff_days']:.1f} days")

        # Re-read DB end_date immediately before writing (state may have changed since scan)
        current_end_date = asyncio.run(_reread_db_end_date(db_path, uuid))
        if not current_end_date:
            print("[ERROR] Sub no longer active in DB — refusing to apply.", file=sys.stderr)
            sys.exit(2)
        current_db_ms = _end_date_to_ms(current_end_date)
        if current_db_ms != target["db_expiry_ms"]:
            print(f"[INFO] DB end_date changed since scan: was {target['db_end_date']}, "
                  f"now {current_end_date}. Using current value.")
            target["db_expiry_ms"] = current_db_ms

        # Never shrink: if panel is already at or past DB date, skip
        if target["panel_expiry_ms"] >= target["db_expiry_ms"]:
            print("[SKIP] Panel expiry is already >= DB end_date. Nothing to do.")
            sys.exit(0)

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
