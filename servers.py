"""
Мультисервер: управление несколькими VPN-серверами.
Поддерживает балансировку нагрузки и автоматический failover.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Путь к файлу конфигурации серверов
SERVERS_CONFIG_PATH = os.getenv("SERVERS_CONFIG_PATH", "./servers.json")


@dataclass
class VPNServer:
    """Конфигурация одного VPN-сервера."""
    id: str                          # Уникальный ID сервера
    name: str                        # Название (напр. "Германия 1")
    host: str                        # IP или домен для подключения клиентов
    xui_host: str                    # IP для API (обычно 127.0.0.1 или внешний)
    xui_port: int                    # Порт 3X-UI API
    xui_web_path: str                # Web path панели
    xui_username: str                # Логин панели
    xui_password: str                # Пароль панели
    vpn_port: int = 443              # Порт VPN
    inbound_id: int = 1              # ID inbound в панели
    max_users: int = 100             # Максимум пользователей
    priority: int = 1                # Приоритет (выше = предпочтительнее)
    enabled: bool = True             # Включён ли сервер
    location: str = ""               # Геолокация (DE, NL, US...)

    # VPN transport настройки
    transport: str = "xhttp"         # Транспорт (tcp, xhttp, ws...)
    transport_path: str = ""         # Путь для xhttp/ws
    transport_host: str = ""         # Host header
    xhttp_mode: str = "packet-up"    # Режим xhttp
    flow: str = ""                   # Flow для TCP (xtls-rprx-vision)

    # Reality настройки
    reality_pbk: str = ""            # Public Key
    reality_sid: str = ""            # Short ID
    reality_sni: str = ""            # SNI (домен маскировки)
    reality_fp: str = "chrome"       # Fingerprint

    # Runtime состояние
    is_healthy: bool = True
    current_users: int = 0
    last_check: Optional[datetime] = None
    last_error: Optional[str] = None


class ServerManager:
    """Менеджер серверов с health-check и балансировкой."""

    def __init__(self):
        self.servers: dict[str, VPNServer] = {}
        self._health_check_interval = 60  # секунд
        self._health_check_task: Optional[asyncio.Task] = None

    def load_config(self, config_path: str = SERVERS_CONFIG_PATH) -> bool:
        """Загрузить конфигурацию серверов из JSON."""
        try:
            if not os.path.exists(config_path):
                logger.warning("Файл конфигурации серверов не найден: %s", config_path)
                return False

            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.servers.clear()
            for srv_data in data.get("servers", []):
                server = VPNServer(**srv_data)
                self.servers[server.id] = server
                logger.info("Загружен сервер: %s (%s)", server.name, server.id)

            return True
        except Exception as e:
            logger.error("Ошибка загрузки конфигурации серверов: %s", e)
            return False

    def save_config(self, config_path: str = SERVERS_CONFIG_PATH) -> bool:
        """Сохранить конфигурацию серверов в JSON."""
        try:
            data = {
                "servers": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "host": s.host,
                        "xui_host": s.xui_host,
                        "xui_port": s.xui_port,
                        "xui_web_path": s.xui_web_path,
                        "xui_username": s.xui_username,
                        "xui_password": s.xui_password,
                        "vpn_port": s.vpn_port,
                        "inbound_id": s.inbound_id,
                        "max_users": s.max_users,
                        "priority": s.priority,
                        "enabled": s.enabled,
                        "location": s.location,
                        "transport": s.transport,
                        "transport_path": s.transport_path,
                        "transport_host": s.transport_host,
                        "xhttp_mode": s.xhttp_mode,
                        "reality_pbk": s.reality_pbk,
                        "reality_sid": s.reality_sid,
                        "reality_sni": s.reality_sni,
                        "reality_fp": s.reality_fp,
                    }
                    for s in self.servers.values()
                ]
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error("Ошибка сохранения конфигурации серверов: %s", e)
            return False

    def add_server(self, server: VPNServer) -> bool:
        """Добавить новый сервер."""
        if server.id in self.servers:
            logger.warning("Сервер с ID %s уже существует", server.id)
            return False
        self.servers[server.id] = server
        self.save_config()
        return True

    def remove_server(self, server_id: str) -> bool:
        """Удалить сервер."""
        if server_id not in self.servers:
            return False
        del self.servers[server_id]
        self.save_config()
        return True

    def get_server(self, server_id: str) -> Optional[VPNServer]:
        """Получить сервер по ID."""
        return self.servers.get(server_id)

    def get_best_server(self) -> Optional[VPNServer]:
        """
        Выбрать лучший сервер для нового пользователя.
        Критерии: enabled, healthy, не перегружен, приоритет.
        """
        available = [
            s for s in self.servers.values()
            if s.enabled and s.is_healthy and s.current_users < s.max_users
        ]

        if not available:
            # Fallback: любой включённый сервер
            available = [s for s in self.servers.values() if s.enabled]

        if not available:
            return None

        # Сортировка: приоритет (desc), загруженность (asc)
        available.sort(key=lambda s: (-s.priority, s.current_users / max(s.max_users, 1)))
        return available[0]

    def get_all_servers(self) -> list[VPNServer]:
        """Получить список всех серверов."""
        return list(self.servers.values())

    def get_healthy_servers(self) -> list[VPNServer]:
        """Получить список здоровых серверов."""
        return [s for s in self.servers.values() if s.enabled and s.is_healthy]

    async def check_server_health(self, server: VPNServer) -> bool:
        """Проверить доступность сервера."""
        # Всегда используем HTTPS — 3X-UI панели редиректят с HTTP на HTTPS
        web_path = server.xui_web_path.rstrip("/")
        url = f"https://{server.xui_host}:{server.xui_port}{web_path}/login"

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json={"username": server.xui_username, "password": server.xui_password},
                    ssl=False,
                ) as resp:
                    data = await resp.json()
                    is_healthy = data.get("success", False)

                    server.is_healthy = is_healthy
                    server.last_check = datetime.utcnow()
                    server.last_error = None if is_healthy else data.get("msg", "Unknown error")

                    return is_healthy
        except Exception as e:
            server.is_healthy = False
            server.last_check = datetime.utcnow()
            server.last_error = str(e)
            logger.warning("Health check failed for %s: %s", server.name, e)
            return False

    async def check_all_servers(self) -> dict[str, bool]:
        """Проверить все серверы."""
        results = {}
        tasks = [self.check_server_health(s) for s in self.servers.values()]
        health_results = await asyncio.gather(*tasks, return_exceptions=True)

        for server, health in zip(self.servers.values(), health_results):
            if isinstance(health, Exception):
                results[server.id] = False
            else:
                results[server.id] = health

        return results

    async def _health_check_loop(self):
        """Фоновый цикл проверки здоровья серверов."""
        while True:
            try:
                await self.check_all_servers()
                healthy_count = len(self.get_healthy_servers())
                total_count = len(self.servers)
                logger.debug("Health check: %d/%d серверов онлайн", healthy_count, total_count)
            except Exception as e:
                logger.error("Ошибка health check: %s", e)

            await asyncio.sleep(self._health_check_interval)

    def start_health_checks(self):
        """Запустить фоновую проверку серверов."""
        if self._health_check_task is None or self._health_check_task.done():
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            logger.info("Health check запущен")

    def stop_health_checks(self):
        """Остановить фоновую проверку."""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            logger.info("Health check остановлен")

    def get_stats(self) -> dict:
        """Получить статистику по серверам."""
        total = len(self.servers)
        enabled = len([s for s in self.servers.values() if s.enabled])
        healthy = len(self.get_healthy_servers())
        total_users = sum(s.current_users for s in self.servers.values())
        total_capacity = sum(s.max_users for s in self.servers.values() if s.enabled)

        return {
            "total_servers": total,
            "enabled_servers": enabled,
            "healthy_servers": healthy,
            "total_users": total_users,
            "total_capacity": total_capacity,
            "load_percent": round(total_users / max(total_capacity, 1) * 100, 1),
        }


# Глобальный экземпляр менеджера
server_manager = ServerManager()
