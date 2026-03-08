"""Application configuration using Pydantic Settings."""

from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Database
    database_url: str = Field(..., description="PostgreSQL connection URL")

    # Telegram Bot
    bot_token: str = Field(..., description="Telegram Bot API token")
    admin_chat_id: Optional[int] = Field(None, description="Admin Telegram chat ID")
    admin_ids: str = Field("", description="Comma-separated list of admin Telegram IDs")
    support_bot_username: str = Field("SWAGASupport_bot", description="Support bot username")
    bot_username: str = Field("Swaga_vpnbot", description="Main bot username for subscription profile link")

    # 3X-UI Panel
    xui_base: str = Field(..., description="3X-UI panel base URL")
    xui_username: str = Field(..., description="3X-UI admin username")
    xui_password: str = Field(..., description="3X-UI admin password")
    xui_inbound_id: int = Field(1, description="3X-UI inbound ID")

    # VPN Configuration
    vpn_flow: str = Field("xtls-rprx-vision", description="VLESS flow control")

    # YooKassa
    yookassa_shop_id: str = Field(..., description="YooKassa shop ID")
    yookassa_secret: str = Field(..., description="YooKassa secret key")
    yookassa_webhook_secret: Optional[str] = Field(None, description="Webhook validation secret")

    # Pricing (RUB)
    price_m1: int = Field(130, description="1-month subscription price")
    price_m3: int = Field(350, description="3-month subscription price")
    price_m12: int = Field(800, description="12-month subscription price")

    # Webhook Server
    webhook_host: str = Field("0.0.0.0", description="Webhook server bind host")
    webhook_port: int = Field(8000, description="Webhook server bind port")
    webhook_base_url: str = Field(..., description="Public webhook base URL")

    # Trial
    trial_days: int = Field(7, description="Trial period duration in days")

    # Logging
    log_level: str = Field("INFO", description="Logging level")

    @field_validator("xui_base")
    @classmethod
    def validate_xui_base(cls, v: str) -> str:
        """Ensure XUI_BASE has protocol and no trailing slash."""
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("XUI_BASE must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("webhook_base_url")
    @classmethod
    def validate_webhook_base_url(cls, v: str) -> str:
        """Ensure webhook base URL has no trailing slash."""
        return v.rstrip("/")

    @property
    def admin_id_list(self) -> List[int]:
        """Parse admin_ids string into a list of integers."""
        ids: List[int] = []
        if self.admin_chat_id:
            ids.append(self.admin_chat_id)
        for part in self.admin_ids.split(","):
            part = part.strip()
            if part.isdigit():
                admin_id = int(part)
                if admin_id not in ids:
                    ids.append(admin_id)
        return ids

    @property
    def yookassa_return_url(self) -> str:
        """Generate return URL for YooKassa payments."""
        return f"https://t.me/{self.support_bot_username}"

    @property
    def webhook_path(self) -> str:
        """YooKassa webhook endpoint path."""
        return "/webhook/yookassa"

    @property
    def webhook_full_url(self) -> str:
        """Full webhook URL for YooKassa configuration."""
        return f"{self.webhook_base_url}{self.webhook_path}"


# Global settings instance
settings = Settings()
