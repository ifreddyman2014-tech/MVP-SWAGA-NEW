"""
Бэкап и восстановление базы данных.
Хранит копии за последние 30 дней.
"""

import os
import shutil
import logging
from datetime import datetime, timedelta

from config import DB_PATH, BACKUP_DIR

logger = logging.getLogger(__name__)


def backup_now() -> str | None:
    """
    Создать резервную копию БД.
    Возвращает путь к файлу бэкапа или None при ошибке.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"backup_{timestamp}.db")
    try:
        shutil.copy2(DB_PATH, dest)
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
    """
    filename = f"backup_{date_str}.db"
    src = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(src):
        logger.error("Бэкап не найден: %s", src)
        return False
    try:
        backup_now()  # страховочная копия
        shutil.copy2(src, DB_PATH)
        logger.info("БД восстановлена из: %s", filename)
        return True
    except Exception as e:
        logger.error("Ошибка восстановления: %s", e)
        return False
