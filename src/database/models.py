"""
SQLAlchemy 2.0 database models for SWAGA VPN Bot.

Federated Identity Schema:
    User -> Subscription -> Key -> Server

A user has one static UUID that is synced across all servers.
Each subscription can have multiple keys (one per server).
"""

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class User(Base):
    """User model - represents a Telegram user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # User's static UUID - same across all servers
    user_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid4()))

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Trial tracking
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User(telegram_id={self.telegram_id}, username={self.username})>"


class Server(Base):
    """Server model - represents a 3X-UI VPN server."""

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Server identification
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 3X-UI API credentials
    api_url: Mapped[str] = mapped_column(String(512), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    inbound_id: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # VLESS-Reality configuration
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=443, nullable=False)
    public_key: Mapped[str] = mapped_column(String(255), nullable=False)
    short_ids: Mapped[str] = mapped_column(Text, nullable=False)  # Comma-separated
    domain: Mapped[str] = mapped_column(String(255), nullable=False)  # SNI

    # Optional VLESS params
    security: Mapped[str] = mapped_column(String(50), default="reality", nullable=False)
    network_type: Mapped[str] = mapped_column(String(50), default="xhttp", nullable=False)
    flow: Mapped[str] = mapped_column(String(50), default="xtls-rprx-vision", nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(50), default="chrome", nullable=False)
    spider_x: Mapped[str] = mapped_column(String(255), default="/", nullable=False)
    location: Mapped[str] = mapped_column(String(10), default="", nullable=False)  # Country code (e.g., "FI", "DE")

    # xhttp specific
    xhttp_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    xhttp_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    xhttp_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    keys: Mapped[List["Key"]] = relationship("Key", back_populates="server", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Server(name={self.name}, host={self.host})>"

    def get_first_short_id(self) -> str:
        """Get the first short_id from comma-separated list."""
        return self.short_ids.split(",")[0].strip() if self.short_ids else ""


class Subscription(Base):
    """Subscription model - represents a user's active subscription."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Subscription details
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    expiry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Subscription type
    plan_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "trial", "paid_1m", "paid_3m", "paid_12m"

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Notification tracking
    notified_24h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified_0h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expired_handled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscriptions")
    keys: Mapped[List["Key"]] = relationship("Key", back_populates="subscription", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Subscription(id={self.id}, user_id={self.user_id}, plan={self.plan_type}, expires={self.expiry_date})>"


class Key(Base):
    """
    Key model - represents a VPN key on a specific server.

    Constraint: One key per server per subscription.
    All keys for a subscription share the same UUID (from user.user_uuid).
    """

    __tablename__ = "keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    subscription_id: Mapped[int] = mapped_column(Integer, ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)

    # Key UUID - should match user.user_uuid
    key_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 3X-UI client email (unique identifier on panel)
    email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Sync status
    synced_to_panel: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    subscription: Mapped["Subscription"] = relationship("Subscription", back_populates="keys")
    server: Mapped["Server"] = relationship("Server", back_populates="keys")

    # Unique constraint: one key per server per subscription
    __table_args__ = (
        UniqueConstraint("subscription_id", "server_id", name="uq_subscription_server"),
    )

    def __repr__(self) -> str:
        return f"<Key(id={self.id}, server_id={self.server_id}, uuid={self.key_uuid})>"


class Payment(Base):
    """Payment model - tracks YooKassa payment transactions."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Payment identification
    payment_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    # User reference
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # Payment details
    plan_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "m1", "m3", "m12"
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="RUB", nullable=False)

    # Status tracking
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    # Status values: pending, succeeded, canceled, refunded

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Payment(payment_id={self.payment_id}, status={self.status}, amount={self.amount})>"
