"""
Вспомогательные утилиты.
"""

import secrets
import string
import uuid
from datetime import datetime
from urllib.parse import quote


def generate_uuid() -> str:
    """Сгенерировать новый UUID v4."""
    return str(uuid.uuid4())


def generate_sub_id(length: int = 16) -> str:
    """Сгенерировать случайный subId для подписки 3X-UI."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def format_date(dt) -> str:
    """Привести дату к формату ДД.ММ.ГГГГ."""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.strftime("%d.%m.%Y")


def build_vless_link(
    uuid_str: str,
    host: str,
    port: int,
    transport: str,
    path: str,
    camouflage_host: str,
    xhttp_mode: str,
    reality_pbk: str,
    reality_sid: str,
    reality_fp: str,
    reality_sni: str,
    reality_spx: str,
    remark: str = "SWAGA VPN",
    flow: str = "",
) -> str:
    """Сформировать VLESS Reality ссылку для подключения (TCP или xHTTP)."""
    enc_spx = quote(reality_spx, safe="")
    enc_remark = quote(remark, safe="")

    # Базовая часть ссылки
    base = f"vless://{uuid_str}@{host}:{port}?security=reality"

    # Добавляем параметры в зависимости от транспорта
    if transport == "tcp":
        # TCP транспорт: используем flow вместо xhttp параметров
        flow_param = f"&flow={flow}" if flow else ""
        params = (
            f"{flow_param}"
            f"&pbk={reality_pbk}"
            f"&fp={reality_fp}"
            f"&sni={reality_sni}"
            f"&sid={reality_sid}"
            f"&spx={enc_spx}"
        )
    else:
        # xHTTP или другой транспорт: используем старые параметры
        enc_path = quote(path, safe="")
        params = (
            f"&type={transport}"
            f"&path={enc_path}"
            f"&host={camouflage_host}"
            f"&mode={xhttp_mode}"
            f"&pbk={reality_pbk}"
            f"&fp={reality_fp}"
            f"&sni={reality_sni}"
            f"&sid={reality_sid}"
            f"&spx={enc_spx}"
        )

    return f"{base}{params}#{enc_remark}"
