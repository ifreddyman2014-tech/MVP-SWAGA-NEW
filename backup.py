"""
Бэкап и восстановление базы данных.
Хранит копии за последние 30 дней.
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta


from config import DB_PATH, BACKUP_DIR

logger = logging.getLogger(__name__)


def backup_now() -> str | None:
    """
    Создать резервную копию БД через sqlite3.backup() (online backup API).
    Корректно работает при открытых WAL-транзакциях — в отличие от cp/shutil.copy2,
    которые могут захватить несогласованное состояние WAL.
    Возвращает путь к файлу бэкапа или None при ошибке.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"backup_{timestamp}.db")
    try:
        src_conn = sqlite3.connect(DB_PATH)
        dst_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dst_conn)
            integrity = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"integrity_check failed on backup: {integrity}")
        finally:
            dst_conn.close()
            src_conn.close()
        logger.info("Бэкап создан: %s", dest)
        _cleanup_old_backups()
        return dest
    except Exception as e:
        logger.error("Ошибка создания бэкапа: %s", e)
        return None


def _cleanup_old_backups() -> None:
    """Удалить бэкапы старше 30 дней."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    for filename in os.listdir(BACKUP_DIR):
        if not filename.startswith("backup_") or not filename.endswith(".db"):
            continue
        try:
            date_str = filename.replace("backup_", "").replace(".db", "")
            file_date = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
            if file_date < cutoff:
                path = os.path.join(BACKUP_DIR, filename)
                os.remove(path)
                logger.info("Старый бэкап удалён: %s", filename)
        except ValueError:
            continue


def restore_backup(date_str: str) -> bool:
    """
    Восстановить БД из бэкапа по дате (формат: YYYYMMDD_HHMMSS).
    Перед восстановлением создаёт страховочную копию текущей БД.

    IMPORTANT: restoring does NOT roll back payments that arrived after the
    backup was taken. Use only for code rollback, not DB rollback.
    """
    filename = f"backup_{date_str}.db"
    src = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(src):
        logger.error("Бэкап не найден: %s", src)
        return False
    try:
        backup_now()  # страховочная копия текущего состояния
        src_conn = sqlite3.connect(src)
        dst_conn = sqlite3.connect(DB_PATH)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()
        logger.info("БД восстановлена из: %s", filename)
        return True
    except Exception as e:
        logger.error("Ошибка восстановления: %s", e)
        return False
