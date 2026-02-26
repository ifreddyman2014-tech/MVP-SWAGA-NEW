"""
3X-UI Panel API Client (MHSanaei fork).

CRITICAL: The MHSanaei fork requires the 'settings' field in addClient/updateClient
to be a JSON-serialized STRING inside the main JSON body.

Example correct payload:
{
    "id": 1,
    "settings": "{\"clients\": [{\"id\": \"uuid-here\", ...}]}"
}
"""

import asyncio
import json
import logging
import random
import string
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import aiohttp

logger = logging.getLogger(__name__)


class ThreeXUIError(Exception):
    """Base exception for 3X-UI API errors."""
    pass


class ThreeXUIAuthError(ThreeXUIError):
    """Authentication failed."""
    pass


class ThreeXUIClientNotFoundError(ThreeXUIError):
    """Client not found on panel."""
    pass


class ThreeXUIClient:
    """
    Async client for 3X-UI panel API (MHSanaei fork).

    Features:
    - Automatic session management and re-authentication
    - Retry logic with exponential backoff
    - Proper JSON serialization for settings field
    - VLESS-Reality + xtls-rprx-vision support
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        inbound_id: int = 1,
        flow: str = "xtls-rprx-vision",
        timeout: int = 30,
        max_retries: int = 3,
        verify_ssl: bool = False,
    ):
        """
        Initialize 3X-UI client.

        Args:
            base_url: Panel URL (e.g., https://panel.example.com)
            username: Admin username
            password: Admin password
            inbound_id: Inbound ID to manage
            flow: VLESS flow control (default: xtls-rprx-vision)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            verify_ssl: Verify SSL certificates (default: False)
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.inbound_id = inbound_id
        self.flow = flow
        self.timeout = aiohttp.ClientTimeout(total=timeout, connect=10)
        self.max_retries = max_retries
        self.verify_ssl = verify_ssl

        self._session: Optional[aiohttp.ClientSession] = None
        self._authenticated = False

        # Extract origin and referer for headers
        parsed = urlsplit(self.base_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.referer = f"{self.base_url}/"

    @asynccontextmanager
    async def session(self):
        """Context manager for session lifecycle."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self.verify_ssl)
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                timeout=self.timeout,
                connector=connector,
            )
            self._authenticated = False

        try:
            if not self._authenticated:
                await self._login()
            yield self
        finally:
            pass  # Keep session alive for reuse

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._authenticated = False

    def _get_headers(self) -> Dict[str, str]:
        """Get common headers for API requests."""
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.origin,
            "Referer": self.referer,
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for aiohttp request

        Returns:
            Response object

        Raises:
            ThreeXUIError: On request failure after retries
        """
        url = f"{self.base_url}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers.update(self._get_headers())

        last_error = None
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"3X-UI {method} {url} (attempt {attempt + 1}/{self.max_retries})")
                async with self._session.request(method, url, headers=headers, **kwargs) as response:
                    logger.debug(f"3X-UI response: {response.status}")

                    # Handle 401 - re-authenticate and retry once
                    if response.status == 401:
                        logger.warning("3X-UI session expired, re-authenticating...")
                        self._authenticated = False
                        await self._login()
                        # Retry request after re-auth
                        async with self._session.request(method, url, headers=headers, **kwargs) as retry_response:
                            return retry_response

                    return response

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                logger.warning(f"3X-UI request failed (attempt {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.5 * (2 ** attempt))  # Exponential backoff
                continue

        raise ThreeXUIError(f"Request failed after {self.max_retries} attempts: {last_error}")

    async def _login(self):
        """Authenticate with 3X-UI panel."""
        url = f"{self.base_url}/login"
        payload = {"username": self.username, "password": self.password}

        logger.info("Authenticating with 3X-UI panel...")

        try:
            async with self._session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.timeout,
            ) as response:
                data = await self._parse_response(response, url)

                if isinstance(data, dict) and data.get("success"):
                    self._authenticated = True
                    logger.info("3X-UI authentication successful")
                    return

                # Try form-data authentication (fallback)
                async with self._session.post(
                    url,
                    data=payload,
                    headers=self._get_headers(),
                    timeout=self.timeout,
                ) as response2:
                    data2 = await self._parse_response(response2, url)

                    if isinstance(data2, dict) and data2.get("success"):
                        self._authenticated = True
                        logger.info("3X-UI authentication successful (form-data)")
                        return

                raise ThreeXUIAuthError(f"Authentication failed: {data}")

        except aiohttp.ClientError as e:
            raise ThreeXUIAuthError(f"Authentication request failed: {e}")

    async def _parse_response(self, response: aiohttp.ClientResponse, url: str) -> Any:
        """Parse response, handle both JSON and non-JSON responses."""
        text = await response.text()

        # Try JSON parsing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # For mutation endpoints, empty response with 200 is success
        is_mutation = any(k in url.lower() for k in ("addclient", "delclient", "update"))
        if response.status == 200 and text.strip() == "" and is_mutation:
            return {"success": True, "raw": text}

        # Return raw response info
        return {
            "success": response.status == 200,
            "raw": text,
            "status": response.status,
            "url": url,
            "content_type": response.headers.get("Content-Type", ""),
        }

    def _generate_sub_id(self) -> str:
        """Generate random subId (16 chars: lowercase letters + digits)."""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

    def _build_client_object(
        self,
        uuid: str,
        email: str,
        expiry_ms: int,
        flow: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build client object for 3X-UI panel.

        Args:
            uuid: Client UUID
            email: Client email (unique identifier)
            expiry_ms: Expiry timestamp in milliseconds
            flow: VLESS flow (default: xtls-rprx-vision)

        Returns:
            Client object dict
        """
        return {
            "id": uuid,
            "uuid": uuid,
            "email": email,
            "enable": True,
            "expiryTime": int(expiry_ms),
            "totalGB": 0,
            "limitIp": 0,
            "flow": flow or self.flow,
            "reset": 0,
            "subId": self._generate_sub_id(),
            "tgId": "",
            "comment": "",
        }

    async def get_inbound(self, inbound_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get inbound configuration.

        Args:
            inbound_id: Inbound ID (defaults to self.inbound_id)

        Returns:
            Inbound configuration dict

        Raises:
            ThreeXUIError: On failure
        """
        if inbound_id is None:
            inbound_id = self.inbound_id

        # Try multiple endpoint variations
        endpoints = [
            f"/panel/api/inbounds/get/{inbound_id}",
            f"/xui/api/inbounds/get/{inbound_id}",
            f"/xui/inbounds/get/{inbound_id}",
            f"/panel/inbounds/get/{inbound_id}",
        ]

        for endpoint in endpoints:
            try:
                response = await self._request("GET", endpoint)
                data = await self._parse_response(response, endpoint)

                if isinstance(data, dict) and data.get("success"):
                    # Extract inbound object
                    inbound = data.get("obj") or data.get("data") or {}
                    if isinstance(inbound, dict):
                        return inbound

            except Exception as e:
                logger.debug(f"Failed to get inbound via {endpoint}: {e}")
                continue

        raise ThreeXUIError(f"Failed to get inbound {inbound_id}")

    async def list_clients(self, inbound_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List all clients in an inbound.

        Args:
            inbound_id: Inbound ID (defaults to self.inbound_id)

        Returns:
            List of client dicts

        Raises:
            ThreeXUIError: On failure
        """
        inbound = await self.get_inbound(inbound_id)

        # Extract clients from settings
        settings = inbound.get("settings")
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except json.JSONDecodeError:
                logger.error("Failed to parse inbound settings JSON")
                return []

        if isinstance(settings, dict):
            clients = settings.get("clients") or []
            return clients if isinstance(clients, list) else []

        return []

    async def find_client_by_email(self, email: str, inbound_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Find client by email.

        Args:
            email: Client email
            inbound_id: Inbound ID (defaults to self.inbound_id)

        Returns:
            Client dict or None if not found
        """
        clients = await self.list_clients(inbound_id)
        for client in clients:
            if isinstance(client, dict) and client.get("email") == email:
                return client
        return None

    async def find_client_by_uuid(self, uuid: str, inbound_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Find client by UUID.

        Args:
            uuid: Client UUID
            inbound_id: Inbound ID (defaults to self.inbound_id)

        Returns:
            Client dict or None if not found
        """
        clients = await self.list_clients(inbound_id)
        for client in clients:
            if isinstance(client, dict) and (client.get("id") == uuid or client.get("uuid") == uuid):
                return client
        return None

    async def add_client(
        self,
        uuid: str,
        email: str,
        expiry_ms: int,
        inbound_id: Optional[int] = None,
        flow: Optional[str] = None,
    ) -> None:
        """
        Add a new client to the inbound.

        CRITICAL: Uses JSON-serialized string for settings field (MHSanaei fork requirement).

        Args:
            uuid: Client UUID
            email: Client email (unique identifier)
            expiry_ms: Expiry timestamp in milliseconds
            inbound_id: Inbound ID (defaults to self.inbound_id)
            flow: VLESS flow (defaults to self.flow)

        Raises:
            ThreeXUIError: On failure
        """
        if inbound_id is None:
            inbound_id = self.inbound_id

        # Check if client already exists
        existing = await self.find_client_by_email(email, inbound_id)
        if existing:
            logger.info(f"Client {email} already exists, skipping add")
            return

        client_obj = self._build_client_object(uuid, email, expiry_ms, flow)

        # CRITICAL: Serialize settings as JSON STRING
        settings_json_str = json.dumps({"clients": [client_obj]}, ensure_ascii=False)

        endpoints = [
            "/panel/api/inbounds/addClient",
            "/xui/api/inbounds/addClient",
            "/xui/inbounds/addClient",
            "/panel/inbounds/addClient",
        ]

        payloads = [
            # Variant 1: JSON with settings as string
            ({"id": inbound_id, "settings": settings_json_str}, "json"),
            # Variant 2: Form-data with settings as string
            ({"id": str(inbound_id), "settings": settings_json_str}, "data"),
        ]

        last_error = None

        for endpoint in endpoints:
            for payload, payload_type in payloads:
                try:
                    kwargs = {"json": payload} if payload_type == "json" else {"data": payload}
                    response = await self._request("POST", endpoint, **kwargs)
                    data = await self._parse_response(response, endpoint)

                    msg = ""
                    if isinstance(data, dict):
                        msg = str(data.get("msg") or data.get("message") or "").lower()

                    # Success or duplicate (treat as success)
                    if data.get("success") or "duplicate" in msg:
                        # Verify client was added
                        await asyncio.sleep(1)
                        if await self.find_client_by_email(email, inbound_id):
                            logger.info(f"Client {email} added successfully")
                            return

                    last_error = data

                except Exception as e:
                    last_error = e
                    logger.debug(f"Add client failed via {endpoint}: {e}")
                    continue

        raise ThreeXUIError(f"Failed to add client {email}: {last_error}")

    async def update_client_expiry(
        self,
        uuid: str,
        expiry_ms: int,
        email: Optional[str] = None,
        inbound_id: Optional[int] = None,
    ) -> bool:
        """
        Update client expiry time.

        Args:
            uuid: Client UUID
            expiry_ms: New expiry timestamp in milliseconds
            email: Client email (optional hint)
            inbound_id: Inbound ID (defaults to self.inbound_id)

        Returns:
            True if updated successfully, False otherwise
        """
        if inbound_id is None:
            inbound_id = self.inbound_id

        endpoints = [
            "/panel/api/inbounds/updateClient",
            "/xui/api/inbounds/updateClient",
            "/xui/inbounds/updateClient",
            "/panel/inbounds/updateClient",
        ]

        payloads = []
        for key, value in [("uuid", uuid), ("email", email or "")]:
            if value:
                payloads.extend([
                    ({"id": inbound_id, key: value, "enable": True, "expiryTime": int(expiry_ms)}, "json"),
                    ({"id": str(inbound_id), key: value, "enable": "true", "expiryTime": str(int(expiry_ms))}, "data"),
                ])

        for endpoint in endpoints:
            for payload, payload_type in payloads:
                try:
                    kwargs = {"json": payload} if payload_type == "json" else {"data": payload}
                    response = await self._request("POST", endpoint, **kwargs)
                    data = await self._parse_response(response, endpoint)

                    if data.get("success"):
                        logger.info(f"Client {uuid} expiry updated successfully")
                        return True

                except Exception as e:
                    logger.debug(f"Update client expiry failed via {endpoint}: {e}")
                    continue

        return False

    async def delete_client(
        self,
        uuid: str,
        inbound_id: Optional[int] = None,
    ) -> None:
        """
        Delete a client from the inbound.

        Args:
            uuid: Client UUID
            inbound_id: Inbound ID (defaults to self.inbound_id)

        Raises:
            ThreeXUIError: On failure
        """
        if inbound_id is None:
            inbound_id = self.inbound_id

        endpoints = [
            "/panel/api/inbounds/delClient",
            "/xui/api/inbounds/delClient",
            "/xui/inbounds/delClient",
            "/panel/inbounds/delClient",
        ]

        payloads = [
            ({"id": inbound_id, "clientId": uuid}, "json"),
            ({"id": str(inbound_id), "clientId": uuid}, "data"),
        ]

        for endpoint in endpoints:
            for payload, payload_type in payloads:
                try:
                    kwargs = {"json": payload} if payload_type == "json" else {"data": payload}
                    response = await self._request("POST", endpoint, **kwargs)
                    await self._parse_response(response, endpoint)

                    # Verify deletion
                    await asyncio.sleep(0.5)
                    if not await self.find_client_by_uuid(uuid, inbound_id):
                        logger.info(f"Client {uuid} deleted successfully")
                        return

                except Exception as e:
                    logger.debug(f"Delete client failed via {endpoint}: {e}")
                    continue

        raise ThreeXUIError(f"Failed to delete client {uuid}")

    async def ensure_client(
        self,
        uuid: str,
        email: str,
        expiry_ms: int,
        inbound_id: Optional[int] = None,
        flow: Optional[str] = None,
    ) -> str:
        """
        Ensure client exists with given expiry (add or update).

        Args:
            uuid: Client UUID
            email: Client email
            expiry_ms: Expiry timestamp in milliseconds
            inbound_id: Inbound ID (defaults to self.inbound_id)
            flow: VLESS flow (defaults to self.flow)

        Returns:
            Client UUID

        Raises:
            ThreeXUIError: On failure
        """
        # Check if client exists by email
        existing = await self.find_client_by_email(email, inbound_id)

        if existing:
            existing_uuid = existing.get("id") or existing.get("uuid")
            # Update expiry
            updated = await self.update_client_expiry(existing_uuid, expiry_ms, email, inbound_id)
            if updated:
                return existing_uuid
            else:
                logger.warning(f"Failed to update client {email}, will try to re-add")

        # Add new client
        await self.add_client(uuid, email, expiry_ms, inbound_id, flow)
        return uuid
