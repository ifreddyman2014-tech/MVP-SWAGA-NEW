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
) -> str:
    """Сформировать VLESS Reality + XHTTP ссылку для подключения."""
    enc_path = quote(path, safe="")
    enc_spx = quote(reality_spx, safe="")
    return (
        f"vless://{uuid_str}@{host}:{port}"
        f"?type={transport}"
        f"&path={enc_path}"
        f"&host={camouflage_host}"
        f"&mode={xhttp_mode}"
        f"&security=reality"
        f"&pbk={reality_pbk}"
        f"&fp={reality_fp}"
        f"&sni={reality_sni}"
        f"&sid={reality_sid}"
        f"&spx={enc_spx}"
        f"#VPN-SWAGA"
    )
