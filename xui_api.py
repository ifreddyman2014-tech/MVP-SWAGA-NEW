"""
Клиент для работы с 3X-UI Panel API (Xray/VLESS).
Использует requests.Session для сохранения cookie-сессии.
"""

import json
import logging
import urllib3

import requests

from config import XUI_HOST, XUI_PORT, XUI_WEB_PATH, XUI_USER, XUI_PASS

# Отключаем предупреждения о самоподписанных сертификатах
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class XUIAPI:
    """Обёртка над REST API панели 3X-UI."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.base_url = f"http://{XUI_HOST}:{XUI_PORT}{XUI_WEB_PATH}"
        self._logged_in = False

    # ── Аутентификация ────────────────────────────────────────────────────────

    def login(self) -> bool:
        """Авторизация в панели. Возвращает True при успехе."""
        url = f"{self.base_url}/login"
        payload = {"username": XUI_USER, "password": XUI_PASS}
        try:
            resp = self.session.post(url, json=payload, verify=False, timeout=10)
            data = resp.json()
            if data.get("success"):
                self._logged_in = True
                logger.info("3X-UI: авторизация успешна")
                return True
            logger.error("3X-UI: ошибка авторизации — %s", data)
            return False
        except Exception as e:
            logger.error("3X-UI: ошибка подключения при логине — %s", e)
            return False

    def _ensure_login(self) -> None:
        """Автоматический логин при необходимости."""
        if not self._logged_in:
            if not self.login():
                raise ConnectionError("Не удалось подключиться к 3X-UI панели")

    # ── Управление клиентами ──────────────────────────────────────────────────

    def add_client(self, inbound_id: int, uuid: str, email: str, sub_id: str = "") -> bool:
        """
        Добавить клиента к inbound.
        email используется как уникальный идентификатор внутри 3X-UI.
        sub_id — идентификатор подписки для subscription URL.
        """
        self._ensure_login()
        url = f"{self.base_url}/panel/api/inbounds/addClient"
        settings = json.dumps({
            "clients": [
                {
                    "id": uuid,
                    "email": email,
                    "enable": True,
                    "expiryTime": 0,
                    "flow": "",
                    "limitIp": 0,
                    "totalGB": 0,
                    "subId": sub_id,
                }
            ]
        })
        payload = {"id": inbound_id, "settings": settings}
        try:
            resp = self.session.post(url, json=payload, verify=False, timeout=10)
            data = resp.json()
            if data.get("success"):
                logger.info("3X-UI: клиент добавлен — %s", email)
                return True
            logger.error("3X-UI: ошибка добавления клиента — %s", data)
            return False
        except Exception as e:
            logger.error("3X-UI: ошибка при добавлении клиента — %s", e)
            return False

    def delete_client(self, inbound_id: int, uuid: str) -> bool:
        """Удалить клиента из inbound по UUID."""
        self._ensure_login()
        url = f"{self.base_url}/panel/api/inbounds/{inbound_id}/delClient/{uuid}"
        try:
            resp = self.session.post(url, verify=False, timeout=10)
            data = resp.json()
            if data.get("success"):
                logger.info("3X-UI: клиент удалён — %s", uuid)
                return True
            logger.error("3X-UI: ошибка удаления клиента — %s", data)
            return False
        except Exception as e:
            logger.error("3X-UI: ошибка при удалении клиента — %s", e)
            return False
