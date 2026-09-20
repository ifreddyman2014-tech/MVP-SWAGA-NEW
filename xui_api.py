"""
Клиент для работы с 3X-UI Panel API (Xray/VLESS).
Использует requests.Session для сохранения cookie-сессии.
"""

import json
import logging
import os
from enum import Enum

import urllib3

import requests

from config import XUI_HOST, XUI_PORT, XUI_WEB_PATH, XUI_USER, XUI_PASS

# Отключаем предупреждения о самоподписанных сертификатах
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Подстроки в msg ответа, означающие «клиент с таким UUID не найден».
# Используются в add_or_update_client для fallback на addClient.
_NOT_FOUND_MARKERS = ("record not found", "not found", "no client")


class LiveXUIAccessDenied(RuntimeError):
    """Raised when live XUI panel access is attempted without explicit opt-in.

    Set SWAGA_ALLOW_LIVE_XUI=1 in the production systemd service environment
    to permit real network calls. Tests and worktrees must NOT set this flag.
    """


def _check_live_xui_access() -> None:
    """Fail-closed guard: deny live XUI network access unless explicitly enabled.

    Only SWAGA_ALLOW_LIVE_XUI=1 (exact string) grants access.
    Absent, '0', 'true', 'yes', or any other value → denied.
    """
    if os.environ.get("SWAGA_ALLOW_LIVE_XUI") != "1":
        raise LiveXUIAccessDenied(
            "Live XUI network access is disabled in this environment. "
            "Set SWAGA_ALLOW_LIVE_XUI=1 only in the production systemd service."
        )


class EnsureResult(Enum):
    CREATED = "created"
    UPDATED = "updated"
    ALREADY_OK = "already_ok"
    CONFLICT = "conflict"
    FAILED = "failed"


def _parse_api_response(resp: requests.Response) -> dict:
    """
    Безопасно парсит JSON-ответ панели.
    Если тело — HTML или пустое, возвращает dict с диагностикой,
    не раскрывая содержимое ответа (там могут быть CSRF-токены).
    """
    ct = resp.headers.get("Content-Type", "")
    if "json" not in ct:
        logger.error(
            "3X-UI: ожидался JSON, получен %s (HTTP %s, Content-Type: %s)",
            "HTML" if "html" in ct else "не-JSON",
            resp.status_code,
            ct,
        )
        return {"success": False, "msg": f"non-json response: HTTP {resp.status_code}"}
    try:
        return resp.json()
    except ValueError as exc:
        logger.error("3X-UI: не удалось распарсить JSON (HTTP %s): %s", resp.status_code, exc)
        return {"success": False, "msg": f"json parse error: HTTP {resp.status_code}"}


class XUIAPI:
    """Обёртка над REST API панели 3X-UI."""

    def __init__(self) -> None:
        self.session = requests.Session()
        # Используем HTTPS для порта 443, HTTP для остальных
        protocol = "https" if XUI_PORT == "443" else "http"
        self.base_url = f"{protocol}://{XUI_HOST}:{XUI_PORT}{XUI_WEB_PATH}"
        self._logged_in = False

    # ── Аутентификация ────────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        """Строит URL без двойных слешей (защита от trailing slash в base_url)."""
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    def login(self, username: str = None, password: str = None) -> bool:
        """Авторизация в панели. Возвращает True при успехе."""
        _check_live_xui_access()
        import re as _re
        url = self._url("login")
        user = username or XUI_USER
        pwd = password or XUI_PASS
        try:
            # Получаем CSRF-токен (нужен в 3X-UI v3+)
            try:
                page = self.session.get(self.base_url.rstrip("/") + "/", verify=False, timeout=8)
                m = _re.search(r'csrf-token" content="([^"]+)"', page.text)
                if m:
                    # Сохраняем в сессии — будет отправляться со всеми последующими запросами
                    self.session.headers.update({"X-Csrf-Token": m.group(1)})
            except Exception:
                pass

            resp = self.session.post(
                url,
                data={"username": user, "password": pwd},
                verify=False,
                timeout=10,
            )
            data = _parse_api_response(resp)
            if data.get("success"):
                self._logged_in = True
                logger.info("3X-UI: авторизация успешна")
                return True
            logger.error("3X-UI: ошибка авторизации — %s", data.get("msg", data))
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

    def _client_payload(
        self,
        inbound_id: int,
        uuid: str,
        email: str,
        sub_id: str,
        expiry_time: int,
        flow: str,
    ) -> dict:
        """Собирает payload для addClient / updateClient."""
        settings = json.dumps({
            "clients": [
                {
                    "id": uuid,
                    "email": email,
                    "enable": True,
                    "expiryTime": expiry_time,
                    "flow": flow,
                    "limitIp": 3,
                    "totalGB": 0,
                    "subId": sub_id,
                }
            ]
        })
        return {"id": inbound_id, "settings": settings}

    def add_client(
        self,
        inbound_id: int,
        uuid: str,
        email: str,
        sub_id: str = "",
        expiry_time: int = 0,
        flow: str = "",
    ) -> bool:
        """
        Добавить клиента к inbound.
        email используется как уникальный идентификатор внутри 3X-UI.
        sub_id — идентификатор подписки для subscription URL.
        expiry_time — timestamp в миллисекундах (0 = бессрочно).
        """
        self._ensure_login()
        url = self._url("panel/api/inbounds/addClient")
        payload = self._client_payload(inbound_id, uuid, email, sub_id, expiry_time, flow)
        try:
            resp = self.session.post(url, json=payload, verify=False, timeout=10)
            data = _parse_api_response(resp)
            if data.get("success"):
                logger.info("3X-UI: клиент добавлен — %s", email)
                return True
            logger.error("3X-UI: ошибка добавления клиента — %s", data)
            return False
        except Exception as e:
            logger.error("3X-UI: ошибка при добавлении клиента — %s", e)
            return False

    def update_client(
        self,
        inbound_id: int,
        uuid: str,
        email: str,
        sub_id: str = "",
        expiry_time: int = 0,
        flow: str = "",
    ) -> bool:
        """
        Обновить параметры клиента (например, срок действия).
        Идентификация — по UUID, не по email.
        """
        self._ensure_login()
        url = self._url(f"panel/api/inbounds/updateClient/{uuid}")
        payload = self._client_payload(inbound_id, uuid, email, sub_id, expiry_time, flow)
        try:
            resp = self.session.post(url, json=payload, verify=False, timeout=10)
            data = _parse_api_response(resp)
            if data.get("success"):
                logger.info("3X-UI: клиент обновлён — %s, expiry=%s", email, expiry_time)
                return True
            logger.error("3X-UI: ошибка обновления клиента — %s", data)
            return False
        except Exception as e:
            logger.error("3X-UI: ошибка при обновлении клиента — %s", e)
            return False

    def add_or_update_client(
        self,
        inbound_id: int,
        uuid: str,
        email: str,
        sub_id: str = "",
        expiry_time: int = 0,
        flow: str = "",
    ) -> bool:
        """
        Идемпотентная синхронизация клиента:
        — пробует update_client (по UUID);
        — если панель отвечает «not found», делает add_client;
        — ошибки авторизации, таймаут и не-JSON НЕ считаются «not found»
          и не приводят к попытке создания.

        Используется при синхронизации на вторичные серверы, чтобы
        при повторном вызове (продление, retry) не получать Duplicate email.
        """
        self._ensure_login()
        url = self._url(f"panel/api/inbounds/updateClient/{uuid}")
        payload = self._client_payload(inbound_id, uuid, email, sub_id, expiry_time, flow)
        try:
            resp = self.session.post(url, json=payload, verify=False, timeout=10)
            data = _parse_api_response(resp)
        except requests.exceptions.Timeout:
            logger.error("3X-UI: таймаут при updateClient — %s", email)
            return False
        except Exception as e:
            logger.error("3X-UI: ошибка при updateClient — %s", e)
            return False

        if data.get("success"):
            logger.info("3X-UI: клиент обновлён (add_or_update) — %s, expiry=%s", email, expiry_time)
            return True

        # Если это не-JSON ответ (HTML, 502) — не пытаемся добавить, это проблема связи.
        msg = str(data.get("msg", "")).lower()
        if msg.startswith("non-json") or msg.startswith("json parse"):
            logger.error("3X-UI: non-JSON при updateClient, не делаем addClient — %s", email)
            return False

        # Если панель ответила «клиент не найден» — клиент ещё не существует, добавляем.
        if any(marker in msg for marker in _NOT_FOUND_MARKERS):
            logger.info("3X-UI: клиент не найден на сервере, делаем addClient — %s", email)
            return self.add_client(inbound_id, uuid, email, sub_id=sub_id,
                                   expiry_time=expiry_time, flow=flow)

        # Любая другая ошибка (wrong inbound, Duplicate email на update и т.д.) — логируем.
        logger.error("3X-UI: ошибка add_or_update_client — %s (email=%s)", data, email)
        return False

    def delete_client(self, inbound_id: int, uuid: str) -> bool:
        """Удалить клиента из inbound по UUID."""
        self._ensure_login()
        url = self._url(f"panel/api/inbounds/{inbound_id}/delClient/{uuid}")
        try:
            resp = self.session.post(url, verify=False, timeout=10)
            data = _parse_api_response(resp)
            if data.get("success"):
                logger.info("3X-UI: клиент удалён — %s", uuid)
                return True
            logger.error("3X-UI: ошибка удаления клиента — %s", data)
            return False
        except Exception as e:
            logger.error("3X-UI: ошибка при удалении клиента — %s", e)
            return False

    # ── Read-first provisioning ───────────────────────────────────────────────

    # ── UK1 fork adapter (non-standard panel) ─────────────────────────────────

    def get_inbound_clients_uk1(self, inbound_id: int):
        """
        Read client list for UK1-fork panels where settings is a dict (not JSON string).
        Returns list[dict] on success, None on any failure.
        """
        self._ensure_login()
        url = self._url("panel/api/inbounds/list")
        try:
            resp = self.session.get(url, verify=False, timeout=10)
            data = _parse_api_response(resp)
        except Exception as e:
            logger.error("3X-UI UK1: read inbounds/list error — %s", e)
            return None
        if not data.get("success"):
            logger.error("3X-UI UK1: get_inbound_clients_uk1 failed — %s", data.get("msg"))
            return None
        for inbound in (data.get("obj") or []):
            if inbound.get("id") != inbound_id:
                continue
            settings = inbound.get("settings")
            if not isinstance(settings, dict):
                logger.error(
                    "3X-UI UK1: expected dict settings for inbound %s, got %s",
                    inbound_id, type(settings),
                )
                return None
            return settings.get("clients") or []
        logger.warning("3X-UI UK1: inbound %s not found", inbound_id)
        return None

    def _uk1_client_payload(
        self,
        uuid: str,
        email: str,
        sub_id: str,
        expiry_time: int,
        flow: str,
    ) -> dict:
        return {
            "id": uuid,
            "uuid": uuid,
            "email": email,
            "enable": True,
            "expiryTime": expiry_time,
            "flow": flow,
            "limitIp": 3,
            "totalGB": 0,
            "subId": sub_id,
            "tgId": 0,
            "reset": 0,
        }

    def _uk1_add_client(
        self,
        inbound_id: int,
        uuid: str,
        email: str,
        sub_id: str,
        expiry_time: int,
        flow: str,
    ) -> bool:
        self._ensure_login()
        url = self._url("panel/api/clients/add")
        payload = {
            "client": self._uk1_client_payload(uuid, email, sub_id, expiry_time, flow),
            "inboundIds": [inbound_id],
        }
        try:
            resp = self.session.post(url, json=payload, verify=False, timeout=10)
            data = _parse_api_response(resp)
            if data.get("success"):
                logger.info("3X-UI UK1: client added — %s", email)
                return True
            logger.error("3X-UI UK1: add error — %s", data)
            return False
        except Exception as e:
            logger.error("3X-UI UK1: add exception — %s", e)
            return False

    def _uk1_update_client(
        self,
        uuid: str,
        email: str,
        sub_id: str,
        expiry_time: int,
        flow: str,
    ) -> bool:
        import urllib.parse as _urlparse
        self._ensure_login()
        url = self._url(f"panel/api/clients/update/{_urlparse.quote(email, safe='')}")
        payload = self._uk1_client_payload(uuid, email, sub_id, expiry_time, flow)
        try:
            resp = self.session.post(url, json=payload, verify=False, timeout=10)
            data = _parse_api_response(resp)
            if data.get("success"):
                logger.info("3X-UI UK1: client updated — %s expiry=%s", email, expiry_time)
                return True
            logger.error("3X-UI UK1: update error — %s", data)
            return False
        except Exception as e:
            logger.error("3X-UI UK1: update exception — %s", e)
            return False

    def ensure_client_uk1(
        self,
        inbound_id: int,
        uuid: str,
        email: str,
        sub_id: str = "",
        expiry_time: int = 0,
        flow: str = "",
    ) -> "EnsureResult":
        """
        Read-first idempotent provisioning for UK1-fork panels.

        Routes differ from standard 3X-UI:
          CREATE: POST /panel/api/clients/add  {client: {id, uuid, email, ...}, inboundIds}
          UPDATE: POST /panel/api/clients/update/{email}  (email-keyed, not UUID-keyed)

        Panel honors the UUID passed in both 'id' and 'uuid' fields.
        On UUID found: preserves existing panel email (never silently renames).
        """
        clients = self.get_inbound_clients_uk1(inbound_id)
        if clients is None:
            logger.error(
                "ensure_client_uk1: panel state unreadable, refusing write — %s", email,
            )
            return EnsureResult.FAILED

        for c in clients:
            if c.get("id") == uuid:
                use_email = c.get("email") or email
                # No-shrink: if panel already holds a later (or equal) expiry, leave it.
                panel_expiry = c.get("expiryTime") or 0
                if expiry_time > 0 and panel_expiry > 0 and panel_expiry >= expiry_time:
                    return EnsureResult.ALREADY_OK
                ok = self._uk1_update_client(uuid, use_email, sub_id, expiry_time, flow)
                return EnsureResult.UPDATED if ok else EnsureResult.FAILED

        for c in clients:
            if c.get("email") == email:
                logger.warning(
                    "ensure_client_uk1: email %s exists with different UUID — CONFLICT "
                    "(target UUID: %s)",
                    email, uuid,
                )
                return EnsureResult.CONFLICT

        ok = self._uk1_add_client(inbound_id, uuid, email, sub_id, expiry_time, flow)
        return EnsureResult.CREATED if ok else EnsureResult.FAILED

    # ── Standard panel provisioning ───────────────────────────────────────────

    def get_inbound_clients(self, inbound_id: int):
        """
        Read the client list for an inbound from the panel.
        Returns list[dict] on success, or None on any failure.
        CRITICAL: None != []. None means the panel state could not be read;
        empty list means the inbound exists but has zero clients.
        Returns None for UK1-style panels where settings is a dict (not JSON string).
        """
        self._ensure_login()
        url = self._url("panel/api/inbounds/list")
        try:
            resp = self.session.get(url, verify=False, timeout=10)
            data = _parse_api_response(resp)
        except Exception as e:
            logger.error("3X-UI: ошибка чтения inbounds/list — %s", e)
            return None

        if not data.get("success"):
            logger.error("3X-UI: get_inbound_clients failed — %s", data.get("msg"))
            return None

        for inbound in (data.get("obj") or []):
            if inbound.get("id") != inbound_id:
                continue
            settings = inbound.get("settings")
            if isinstance(settings, dict):
                # Non-standard panel (e.g. UK1): settings is already a dict.
                # The write path is also incompatible, so refuse to read as well.
                logger.warning(
                    "3X-UI: settings field is dict (non-standard panel), "
                    "cannot read clients for inbound %s", inbound_id,
                )
                return None
            if not isinstance(settings, str):
                logger.error(
                    "3X-UI: unexpected settings type %s for inbound %s",
                    type(settings), inbound_id,
                )
                return None
            try:
                parsed = json.loads(settings)
            except ValueError as e:
                logger.error(
                    "3X-UI: cannot parse settings JSON for inbound %s: %s",
                    inbound_id, e,
                )
                return None
            return parsed.get("clients") or []

        logger.warning("3X-UI: inbound %s not found in panel list", inbound_id)
        return None

    def ensure_client(
        self,
        inbound_id: int,
        uuid: str,
        email: str,
        sub_id: str = "",
        expiry_time: int = 0,
        flow: str = "",
        extra_conflict_emails: "list[str] | None" = None,
    ) -> "EnsureResult":
        """
        Read-first idempotent client provisioning.

        Steps:
          1. Read current client list — returns FAILED if None (never writes blind).
          2. UUID found → updateClient using existing panel email (never silently renames).
          3. UUID absent, email or extra_conflict_emails taken by another UUID → CONFLICT.
          4. Both absent → addClient → CREATED / FAILED.

        extra_conflict_emails: additional emails to treat as conflict signals when UUID
        is absent (used for per-inbound alias schemes where the base email must also be
        checked against the target inbound).
        """
        clients = self.get_inbound_clients(inbound_id)
        if clients is None:
            logger.error(
                "ensure_client: panel state unreadable, refusing write — %s", email,
            )
            return EnsureResult.FAILED

        for c in clients:
            if c.get("id") == uuid:
                # Preserve existing panel email — never silently rename a client.
                use_email = c.get("email") or email
                # No-shrink: if panel already holds a later (or equal) expiry, leave it.
                panel_expiry = c.get("expiryTime") or 0
                if expiry_time > 0 and panel_expiry > 0 and panel_expiry >= expiry_time:
                    return EnsureResult.ALREADY_OK
                ok = self.update_client(
                    inbound_id, uuid, use_email,
                    sub_id=sub_id, expiry_time=expiry_time, flow=flow,
                )
                return EnsureResult.UPDATED if ok else EnsureResult.FAILED

        # UUID absent: check for email conflicts.
        conflict_set = {email}
        if extra_conflict_emails:
            conflict_set.update(extra_conflict_emails)

        for c in clients:
            if c.get("email") in conflict_set:
                logger.warning(
                    "ensure_client: email %s exists with different UUID %s "
                    "(target UUID: %s) — CONFLICT",
                    c.get("email"), c.get("id"), uuid,
                )
                return EnsureResult.CONFLICT

        ok = self.add_client(
            inbound_id, uuid, email,
            sub_id=sub_id, expiry_time=expiry_time, flow=flow,
        )
        return EnsureResult.CREATED if ok else EnsureResult.FAILED
