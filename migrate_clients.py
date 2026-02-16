#!/usr/bin/env python3
"""
Скрипт миграции клиентов между серверами.

Использование:
    python migrate_clients.py --from de1 --to fi1 --dry-run
    python migrate_clients.py --from de1,lv1 --to fi1
    python migrate_clients.py --from de1 --to fi1 --delete-source

Возможности:
- Миграция всех активных клиентов с одного или нескольких серверов на целевой сервер
- Обновление записей в базе данных
- Сохранение UUID клиентов (для бесшовной миграции)
- Опциональное удаление клиентов с исходных серверов
- Генерация отчета о миграции
- Dry-run режим для проверки без фактической миграции
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Импорты из проекта
from src.database.session import get_session, init_db
from src.database.models import User, Server, Subscription, Key
from src.services.xui import ThreeXUIClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("migration.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class MigrationStats:
    """Статистика миграции."""

    def __init__(self):
        self.total_users = 0
        self.successful = 0
        self.failed = 0
        self.skipped = 0
        self.errors: List[Dict] = []
        self.migrated_users: List[Dict] = []

    def to_dict(self) -> Dict:
        return {
            "total_users": self.total_users,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": round(self.successful / max(self.total_users, 1) * 100, 2),
            "errors": self.errors,
            "migrated_users": self.migrated_users,
        }


async def get_server_xui_client(server: Server) -> ThreeXUIClient:
    """Создать 3X-UI клиента для сервера."""
    # Определить протокол (HTTPS для стандартных портов)
    https_ports = (443, 2053, 2083, 2096, 8443, 334)
    protocol = "https" if server.api_url.startswith("http") else (
        "https" if any(str(port) in server.api_url for port in https_ports) else "http"
    )

    # Если api_url уже полный, используем его
    if server.api_url.startswith("http"):
        base_url = server.api_url.rstrip("/")
    else:
        # Извлекаем host и port из api_url или составляем из отдельных полей
        base_url = server.api_url.rstrip("/")

    return ThreeXUIClient(
        base_url=base_url,
        username=server.username,
        password=server.password,
        inbound_id=server.inbound_id,
        flow=server.flow,
    )


async def migrate_client(
    source_client: ThreeXUIClient,
    target_client: ThreeXUIClient,
    key: Key,
    user: User,
    subscription: Subscription,
    dry_run: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Мигрировать одного клиента.

    Args:
        source_client: 3X-UI клиент исходного сервера
        target_client: 3X-UI клиент целевого сервера
        key: Ключ клиента из БД
        user: Пользователь
        subscription: Подписка
        dry_run: Если True, не выполнять реальную миграцию

    Returns:
        (success, error_message)
    """
    try:
        # Получить информацию о клиенте с исходного сервера
        async with source_client.session():
            source_client_data = await source_client.find_client_by_email(key.email)

            if not source_client_data:
                return False, f"Client {key.email} not found on source server"

            uuid = source_client_data.get("id") or source_client_data.get("uuid")
            expiry_time = source_client_data.get("expiryTime", 0)

            logger.info(
                f"  Found client: {key.email} (UUID: {uuid[:8]}..., "
                f"expires: {datetime.fromtimestamp(expiry_time/1000) if expiry_time > 0 else 'never'})"
            )

        if dry_run:
            logger.info(f"  [DRY-RUN] Would migrate client {key.email}")
            return True, None

        # Добавить клиента на целевой сервер
        async with target_client.session():
            await target_client.ensure_client(
                uuid=uuid,
                email=key.email,
                expiry_ms=expiry_time,
            )

            # Проверить что клиент создан
            target_client_data = await target_client.find_client_by_email(key.email)
            if not target_client_data:
                return False, f"Failed to verify client {key.email} on target server"

        logger.info(f"  ✓ Client {key.email} migrated successfully")
        return True, None

    except Exception as e:
        error_msg = f"Failed to migrate client {key.email}: {e}"
        logger.error(f"  ✗ {error_msg}")
        return False, error_msg


async def migrate_clients_between_servers(
    source_server_ids: List[str],
    target_server_id: str,
    delete_source: bool = False,
    dry_run: bool = False,
) -> MigrationStats:
    """
    Мигрировать клиентов между серверами.

    Args:
        source_server_ids: ID исходных серверов
        target_server_id: ID целевого сервера
        delete_source: Удалять ли клиентов с исходных серверов после миграции
        dry_run: Режим проверки без фактической миграции

    Returns:
        Статистика миграции
    """
    stats = MigrationStats()

    async for session in get_session():
        # Получить серверы из БД
        result = await session.execute(select(Server))
        servers_db = {s.id: s for s in result.scalars().all()}

        # Проверить что серверы существуют
        for server_id in source_server_ids:
            if server_id not in servers_db:
                logger.error(f"Source server '{server_id}' not found in database")
                return stats

        if target_server_id not in servers_db:
            logger.error(f"Target server '{target_server_id}' not found in database")
            return stats

        source_servers = [servers_db[sid] for sid in source_server_ids]
        target_server = servers_db[target_server_id]

        logger.info(f"Migration plan:")
        logger.info(f"  Source servers: {', '.join(s.name for s in source_servers)}")
        logger.info(f"  Target server: {target_server.name}")
        logger.info(f"  Delete from source: {delete_source}")
        logger.info(f"  Dry run: {dry_run}")
        logger.info("")

        # Создать 3X-UI клиентов
        source_clients = {}
        for server in source_servers:
            source_clients[server.id] = await get_server_xui_client(server)

        target_client = await get_server_xui_client(target_server)

        # Получить все ключи для миграции
        for source_server in source_servers:
            logger.info(f"\nMigrating from {source_server.name}...")

            result = await session.execute(
                select(Key)
                .join(Subscription)
                .join(User)
                .where(Key.server_id == source_server.id)
                .where(Subscription.is_active == True)
            )
            keys = result.scalars().all()

            logger.info(f"Found {len(keys)} active keys on {source_server.name}")
            stats.total_users += len(keys)

            for key in keys:
                # Получить связанные данные
                result = await session.execute(
                    select(Subscription).where(Subscription.id == key.subscription_id)
                )
                subscription = result.scalar_one()

                result = await session.execute(
                    select(User).where(User.id == subscription.user_id)
                )
                user = result.scalar_one()

                logger.info(f"\nMigrating user @{user.username or user.telegram_id}...")

                # Мигрировать клиента
                success, error = await migrate_client(
                    source_clients[source_server.id],
                    target_client,
                    key,
                    user,
                    subscription,
                    dry_run,
                )

                if success:
                    stats.successful += 1
                    stats.migrated_users.append({
                        "telegram_id": user.telegram_id,
                        "username": user.username,
                        "email": key.email,
                        "uuid": key.key_uuid,
                        "from_server": source_server.name,
                        "to_server": target_server.name,
                    })

                    if not dry_run:
                        # Обновить запись ключа в БД
                        key.server_id = target_server.id
                        key.synced_to_panel = True
                        key.last_sync_at = datetime.utcnow()
                        key.sync_error = None
                        await session.commit()

                        # Удалить с исходного сервера если нужно
                        if delete_source:
                            try:
                                async with source_clients[source_server.id].session():
                                    await source_clients[source_server.id].delete_client(
                                        key.key_uuid
                                    )
                                logger.info(f"  ✓ Deleted from source server")
                            except Exception as e:
                                logger.warning(f"  ! Failed to delete from source: {e}")
                else:
                    stats.failed += 1
                    stats.errors.append({
                        "telegram_id": user.telegram_id,
                        "username": user.username,
                        "email": key.email,
                        "error": error,
                    })

        # Закрыть клиенты
        for client in source_clients.values():
            await client.close()
        await target_client.close()

    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Migrate VPN clients between servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run migration from DE to FI
  python migrate_clients.py --from de1 --to fi1 --dry-run

  # Migrate from multiple servers to FI
  python migrate_clients.py --from de1,lv1 --to fi1

  # Migrate and delete from source
  python migrate_clients.py --from de1 --to fi1 --delete-source
        """
    )

    parser.add_argument(
        "--from",
        dest="source",
        required=True,
        help="Source server ID(s), comma-separated (e.g., de1,lv1)"
    )
    parser.add_argument(
        "--to",
        dest="target",
        required=True,
        help="Target server ID (e.g., fi1)"
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="Delete clients from source server after migration"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without making changes"
    )

    args = parser.parse_args()

    # Парсинг исходных серверов
    source_servers = [s.strip() for s in args.source.split(",")]

    logger.info("=" * 60)
    logger.info("VPN CLIENT MIGRATION TOOL")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("")

    # Инициализация БД
    await init_db()

    # Выполнить миграцию
    stats = await migrate_clients_between_servers(
        source_server_ids=source_servers,
        target_server_id=args.target,
        delete_source=args.delete_source,
        dry_run=args.dry_run,
    )

    # Вывести итоги
    logger.info("\n" + "=" * 60)
    logger.info("MIGRATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total users: {stats.total_users}")
    logger.info(f"Successful: {stats.successful}")
    logger.info(f"Failed: {stats.failed}")
    logger.info(f"Skipped: {stats.skipped}")
    logger.info(f"Success rate: {stats.to_dict()['success_rate']}%")

    if stats.errors:
        logger.info(f"\nErrors ({len(stats.errors)}):")
        for error in stats.errors:
            logger.info(f"  - @{error['username'] or error['telegram_id']}: {error['error']}")

    # Сохранить отчет
    report_filename = f"migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_filename, "w", encoding="utf-8") as f:
        json.dump(stats.to_dict(), f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"\nFull report saved to: {report_filename}")

    if not args.dry_run and stats.successful > 0:
        logger.info(f"\n✓ Successfully migrated {stats.successful} users")
        logger.info(f"  Users will need to update their VPN configuration")
        logger.info(f"  Consider notifying users about the server change")

    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
