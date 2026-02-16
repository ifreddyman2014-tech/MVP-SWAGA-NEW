#!/usr/bin/env python3
"""
Sync servers from servers.json to database.

This script reads servers.json and creates/updates Server records in the database.
Run this script after modifying servers.json to sync changes.

Usage:
    python sync_servers.py
    python sync_servers.py --dry-run
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import settings
from src.database.session import init_db, get_session
from src.database.models import Server

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_servers_config(config_path: str = "servers.json") -> List[Dict]:
    """Load servers from JSON config."""
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("servers", [])


def build_api_url(srv: Dict) -> str:
    """Build API URL from server config."""
    https_ports = (443, 2053, 2083, 2096, 8443, 334)
    protocol = "https" if srv["xui_port"] in https_ports else "http"
    web_path = srv["xui_web_path"].rstrip("/")
    return f"{protocol}://{srv['xui_host']}:{srv['xui_port']}{web_path}"


async def sync_servers(dry_run: bool = False):
    """
    Sync servers from servers.json to database.

    Args:
        dry_run: If True, show changes without applying them
    """
    logger.info("=" * 60)
    logger.info("SWAGA VPN - Server Synchronization")
    logger.info("=" * 60)
    logger.info(f"Dry run: {dry_run}")
    logger.info("")

    # Load servers from JSON
    try:
        servers_config = load_servers_config()
        logger.info(f"Loaded {len(servers_config)} servers from servers.json")
    except Exception as e:
        logger.error(f"Failed to load servers.json: {e}")
        return 1

    if not servers_config:
        logger.warning("No servers found in servers.json")
        return 1

    # Initialize database
    await init_db()

    stats = {"created": 0, "updated": 0, "unchanged": 0, "errors": 0}

    async for session in get_session():
        for srv in servers_config:
            server_id = srv["id"]
            server_name = srv["name"]

            try:
                logger.info(f"\nProcessing: {server_name} ({server_id})")

                # Check if server exists
                result = await session.execute(
                    select(Server).where(Server.name == server_name)
                )
                existing = result.scalar_one_or_none()

                # Build API URL
                api_url = build_api_url(srv)

                # Build server data
                server_data = {
                    "name": server_name,
                    "is_active": srv.get("enabled", True),
                    "api_url": api_url,
                    "username": srv["xui_username"],
                    "password": srv["xui_password"],
                    "inbound_id": srv.get("inbound_id", 1),
                    "host": srv["host"],
                    "port": srv.get("vpn_port", 443),
                    "public_key": srv.get("reality_pbk", ""),
                    "short_ids": srv.get("reality_sid", ""),
                    "domain": srv.get("reality_sni", ""),
                    "security": "reality",
                    "network_type": srv.get("transport", "xhttp"),
                    "flow": "xtls-rprx-vision",
                    "fingerprint": srv.get("reality_fp", "chrome"),
                    "spider_x": "/",
                    "xhttp_host": srv.get("transport_host", ""),
                    "xhttp_path": srv.get("transport_path", ""),
                    "xhttp_mode": srv.get("xhttp_mode", "packet-up"),
                }

                if existing:
                    # Check if update needed
                    needs_update = False
                    changes = []

                    for key, new_value in server_data.items():
                        old_value = getattr(existing, key)
                        if old_value != new_value:
                            needs_update = True
                            changes.append(f"  {key}: {old_value} → {new_value}")

                    if needs_update:
                        logger.info(f"  Changes detected:")
                        for change in changes:
                            logger.info(change)

                        if not dry_run:
                            for key, value in server_data.items():
                                setattr(existing, key, value)
                            await session.commit()
                            logger.info(f"  ✓ Updated server: {server_name}")
                        else:
                            logger.info(f"  [DRY-RUN] Would update server: {server_name}")

                        stats["updated"] += 1
                    else:
                        logger.info(f"  ✓ Server unchanged")
                        stats["unchanged"] += 1

                else:
                    # Create new server
                    logger.info(f"  Creating new server: {server_name}")
                    logger.info(f"    Host: {srv['host']}")
                    logger.info(f"    Port: {srv.get('vpn_port', 443)}")
                    logger.info(f"    API: {api_url}")
                    logger.info(f"    Transport: {srv.get('transport', 'xhttp')}")
                    logger.info(f"    Reality SNI: {srv.get('reality_sni', 'N/A')}")

                    if not dry_run:
                        new_server = Server(**server_data)
                        session.add(new_server)
                        await session.commit()
                        await session.refresh(new_server)
                        logger.info(f"  ✓ Created server: {server_name} (DB ID: {new_server.id})")
                    else:
                        logger.info(f"  [DRY-RUN] Would create server: {server_name}")

                    stats["created"] += 1

            except Exception as e:
                logger.error(f"  ✗ Error processing {server_name}: {e}")
                stats["errors"] += 1
                continue

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("SYNCHRONIZATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Created: {stats['created']}")
    logger.info(f"Updated: {stats['updated']}")
    logger.info(f"Unchanged: {stats['unchanged']}")
    logger.info(f"Errors: {stats['errors']}")
    logger.info("")

    if dry_run:
        logger.info("DRY RUN MODE - No changes were made")
        logger.info("Run without --dry-run to apply changes")
    else:
        logger.info("✓ Synchronization completed")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Restart the bot to pick up changes")
        logger.info("2. New users will get keys on all active servers")
        logger.info("3. Existing users can get new keys via /start")

    logger.info("")

    return 0 if stats["errors"] == 0 else 1


async def list_servers():
    """List all servers in database."""
    logger.info("=" * 60)
    logger.info("SERVERS IN DATABASE")
    logger.info("=" * 60)
    logger.info("")

    await init_db()

    async for session in get_session():
        result = await session.execute(select(Server))
        servers = result.scalars().all()

        if not servers:
            logger.info("No servers found in database")
            logger.info("Run 'python sync_servers.py' to sync from servers.json")
            return

        for i, server in enumerate(servers, 1):
            logger.info(f"{i}. {server.name}")
            logger.info(f"   ID: {server.id}")
            logger.info(f"   Active: {server.is_active}")
            logger.info(f"   Host: {server.host}:{server.port}")
            logger.info(f"   API: {server.api_url}")
            logger.info(f"   Transport: {server.network_type}")
            logger.info(f"   Reality SNI: {server.domain}")
            logger.info("")

        logger.info(f"Total servers: {len(servers)}")


async def main():
    parser = argparse.ArgumentParser(
        description="Sync servers from servers.json to database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes without applying
  python sync_servers.py --dry-run

  # Apply changes
  python sync_servers.py

  # List servers in database
  python sync_servers.py --list
        """
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all servers in database"
    )

    args = parser.parse_args()

    if args.list:
        await list_servers()
        return 0

    return await sync_servers(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
