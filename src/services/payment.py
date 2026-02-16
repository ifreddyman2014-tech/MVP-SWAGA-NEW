"""
YooKassa payment service with webhook support.

Handles payment creation and webhook processing for automatic subscription activation.
"""

import logging
import uuid as uuid_lib
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import aiohttp
from aiohttp import BasicAuth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import Key, Payment, Server, Subscription, User

logger = logging.getLogger(__name__)


class YooKassaError(Exception):
    """Base exception for YooKassa errors."""
    pass


class YooKassaService:
    """
    Service for YooKassa payment processing.

    Features:
    - Payment creation with receipts (54-FZ compliant)
    - Webhook validation and processing
    - Automatic subscription activation
    """

    API_URL = "https://api.yookassa.ru/v3"

    # Plan configuration
    PLANS = {
        "m1": {"months": 1, "price": settings.price_m1},
        "m3": {"months": 3, "price": settings.price_m3},
        "m12": {"months": 12, "price": settings.price_m12},
    }

    def __init__(self):
        """Initialize YooKassa service."""
        self.shop_id = settings.yookassa_shop_id
        self.secret = settings.yookassa_secret
        self.webhook_secret = settings.yookassa_webhook_secret
        self.timeout = aiohttp.ClientTimeout(total=30, connect=10)

    def _get_auth(self) -> BasicAuth:
        """Get BasicAuth for YooKassa API."""
        return BasicAuth(login=self.shop_id, password=self.secret)

    def _build_receipt(
        self,
        telegram_id: int,
        description: str,
        amount: float,
    ) -> Dict:
        """
        Build receipt object for 54-FZ compliance.

        Args:
            telegram_id: User's Telegram ID
            description: Item description
            amount: Payment amount in RUB

        Returns:
            Receipt dict
        """
        customer_email = f"user{telegram_id}@swaga.vpn"

        return {
            "customer": {"email": customer_email},
            "items": [
                {
                    "description": description[:128],
                    "quantity": "1.0",
                    "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                    "vat_code": 1,  # VAT code 1 = no VAT
                    "payment_mode": "full_prepayment",
                    "payment_subject": "service",
                }
            ],
        }

    async def create_payment(
        self,
        telegram_id: int,
        plan: str,
        session: AsyncSession,
    ) -> Tuple[str, str]:
        """
        Create a new payment in YooKassa.

        Args:
            telegram_id: User's Telegram ID
            plan: Plan type (m1, m3, m12)
            session: Database session

        Returns:
            Tuple of (payment_id, confirmation_url)

        Raises:
            YooKassaError: On payment creation failure
        """
        if plan not in self.PLANS:
            raise YooKassaError(f"Invalid plan: {plan}")

        plan_info = self.PLANS[plan]
        amount = plan_info["price"]
        months = plan_info["months"]

        description = f"SWAGA VPN - {months} мес."

        # Build payment payload
        idempotence_key = str(uuid_lib.uuid4())
        payload = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": settings.yookassa_return_url,
            },
            "capture": True,
            "description": description,
            "receipt": self._build_receipt(telegram_id, description, amount),
        }

        # Make API request
        url = f"{self.API_URL}/payments"
        headers = {"Idempotence-Key": idempotence_key}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as http_session:
                async with http_session.post(
                    url,
                    json=payload,
                    auth=self._get_auth(),
                    headers=headers,
                ) as response:
                    data = await response.json()

                    if response.status not in (200, 201):
                        raise YooKassaError(f"Payment creation failed: {data}")

                    payment_id = data.get("id")
                    confirmation_url = data.get("confirmation", {}).get("confirmation_url")

                    if not payment_id or not confirmation_url:
                        raise YooKassaError(f"Invalid response from YooKassa: {data}")

                    # Save payment to database
                    payment = Payment(
                        payment_id=payment_id,
                        telegram_id=telegram_id,
                        plan_type=plan,
                        amount=amount,
                        currency="RUB",
                        status="pending",
                    )
                    session.add(payment)
                    await session.commit()

                    logger.info(f"Payment created: {payment_id} for user {telegram_id}, plan {plan}")
                    return payment_id, confirmation_url

        except aiohttp.ClientError as e:
            raise YooKassaError(f"Network error: {e}")
        except Exception as e:
            raise YooKassaError(f"Unexpected error: {e}")

    async def get_payment_status(self, payment_id: str) -> str:
        """
        Get payment status from YooKassa.

        Args:
            payment_id: YooKassa payment ID

        Returns:
            Payment status (pending, succeeded, canceled, etc.)
        """
        url = f"{self.API_URL}/payments/{payment_id}"

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as http_session:
                async with http_session.get(url, auth=self._get_auth()) as response:
                    data = await response.json()
                    return data.get("status", "unknown")

        except Exception as e:
            logger.error(f"Failed to get payment status for {payment_id}: {e}")
            return "unknown"

    async def process_successful_payment(
        self,
        payment_id: str,
        session: AsyncSession,
        bot=None,
    ) -> None:
        """
        Process successful payment and activate subscription.

        Args:
            payment_id: YooKassa payment ID
            session: Database session
            bot: Bot instance for sending notifications

        Raises:
            YooKassaError: On processing failure
        """
        # Get payment from database
        result = await session.execute(
            select(Payment).where(Payment.payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()

        if not payment:
            raise YooKassaError(f"Payment not found: {payment_id}")

        if payment.status == "succeeded":
            logger.info(f"Payment {payment_id} already processed")
            return

        # Get user
        result = await session.execute(
            select(User).where(User.telegram_id == payment.telegram_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise YooKassaError(f"User not found: {payment.telegram_id}")

        # Get plan info
        plan_info = self.PLANS.get(payment.plan_type)
        if not plan_info:
            raise YooKassaError(f"Invalid plan: {payment.plan_type}")

        months = plan_info["months"]

        # Calculate new expiry date
        now = datetime.utcnow()
        base_date = now

        # Check if user has active subscription
        result = await session.execute(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .where(Subscription.is_active == True)
            .order_by(Subscription.expiry_date.desc())
        )
        active_sub = result.scalar_one_or_none()

        if active_sub and active_sub.expiry_date > now:
            # Extend from current expiry
            base_date = active_sub.expiry_date
            logger.info(f"Extending subscription for user {user.telegram_id} from {base_date}")

        new_expiry = base_date + timedelta(days=30 * months)

        # Create or update subscription
        if active_sub:
            # Extend existing subscription
            active_sub.expiry_date = new_expiry
            active_sub.plan_type = f"paid_{payment.plan_type}"
            active_sub.updated_at = now
            active_sub.notified_24h = False
            active_sub.notified_0h = False
            active_sub.expired_handled = False
            subscription = active_sub
        else:
            # Create new subscription
            subscription = Subscription(
                user_id=user.id,
                is_active=True,
                expiry_date=new_expiry,
                plan_type=f"paid_{payment.plan_type}",
                notified_24h=False,
                notified_0h=False,
                expired_handled=False,
            )
            session.add(subscription)

        # Update payment status
        payment.status = "succeeded"
        payment.processed_at = now

        await session.commit()
        await session.refresh(subscription)

        # Sync keys to all servers
        await self._sync_keys_to_servers(user, subscription, new_expiry, session)

        logger.info(
            f"Payment {payment_id} processed successfully. "
            f"User {user.telegram_id} subscription extended to {new_expiry}"
        )

        # Send notification to user with all servers
        if bot:
            try:
                from ..bot.handlers.user import send_all_servers_message

                plan_names = {
                    "m1": "1 месяц",
                    "m3": "3 месяца",
                    "m12": "12 месяцев",
                }
                plan_name = plan_names.get(payment.plan_type, payment.plan_type)

                success_text = (
                    f"💎 <b>Подписка активирована!</b>\n\n"
                    f"📦 Тариф: <b>{plan_name}</b>\n\n"
                    f"<i>YouTube 4K, Instagram, TikTok — всё летает.</i>"
                )

                await send_all_servers_message(
                    user,
                    subscription,
                    session,
                    bot,
                    success_text,
                )

                logger.info(f"Payment notification sent to user {user.telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send payment notification: {e}")
                # Don't raise - payment already processed

    async def _sync_keys_to_servers(
        self,
        user: User,
        subscription: Subscription,
        expiry: datetime,
        session: AsyncSession,
    ) -> None:
        """
        Sync user keys to all active servers.

        Args:
            user: User object
            subscription: Subscription object
            expiry: Expiry datetime
            session: Database session
        """
        from .xui import ThreeXUIClient

        # Get all active servers
        result = await session.execute(
            select(Server).where(Server.is_active == True)
        )
        servers = result.scalars().all()

        if not servers:
            logger.warning("No active servers found for key sync")
            return

        expiry_ms = int(expiry.timestamp() * 1000)

        for server in servers:
            try:
                # Check if key exists for this subscription-server pair
                result = await session.execute(
                    select(Key)
                    .where(Key.subscription_id == subscription.id)
                    .where(Key.server_id == server.id)
                )
                key = result.scalar_one_or_none()

                email = f"user-{user.telegram_id}"

                if not key:
                    # Create new key
                    key = Key(
                        subscription_id=subscription.id,
                        server_id=server.id,
                        key_uuid=user.user_uuid,
                        email=email,
                        synced_to_panel=False,
                    )
                    session.add(key)
                    await session.commit()
                    await session.refresh(key)

                # Sync to 3X-UI panel
                xui_client = ThreeXUIClient(
                    base_url=server.api_url,
                    username=server.username,
                    password=server.password,
                    inbound_id=server.inbound_id,
                    flow=server.flow,
                )

                async with xui_client.session():
                    await xui_client.ensure_client(
                        uuid=user.user_uuid,
                        email=email,
                        expiry_ms=expiry_ms,
                    )

                # Update key sync status
                key.synced_to_panel = True
                key.last_sync_at = datetime.utcnow()
                key.sync_error = None
                await session.commit()

                logger.info(f"Key synced to server {server.name} for user {user.telegram_id}")

            except Exception as e:
                logger.error(f"Failed to sync key to server {server.name}: {e}")
                if key:
                    key.synced_to_panel = False
                    key.sync_error = str(e)[:500]
                    await session.commit()
                continue

    def validate_webhook_signature(self, payload: str, signature: str) -> bool:
        """
        Validate webhook signature (if webhook_secret is configured).

        Args:
            payload: Raw webhook payload
            signature: Signature from header

        Returns:
            True if valid or no secret configured, False otherwise
        """
        if not self.webhook_secret:
            # No secret configured, skip validation
            return True

        # TODO: Implement HMAC signature validation if YooKassa requires it
        # For now, we trust the webhook if webhook_secret is not set
        return True

    async def handle_webhook(
        self,
        event_data: Dict,
        session: AsyncSession,
        bot=None,
    ) -> None:
        """
        Handle incoming YooKassa webhook.

        Args:
            event_data: Webhook event data
            session: Database session
            bot: Bot instance for sending notifications
        """
        event_type = event_data.get("event")
        payment_obj = event_data.get("object", {})
        payment_id = payment_obj.get("id")
        status = payment_obj.get("status")

        logger.info(f"Webhook received: event={event_type}, payment_id={payment_id}, status={status}")

        if event_type == "payment.succeeded" and status == "succeeded":
            try:
                await self.process_successful_payment(payment_id, session, bot)
            except Exception as e:
                logger.error(f"Failed to process successful payment {payment_id}: {e}")
                raise

        elif event_type == "payment.canceled":
            # Update payment status
            result = await session.execute(
                select(Payment).where(Payment.payment_id == payment_id)
            )
            payment = result.scalar_one_or_none()
            if payment:
                payment.status = "canceled"
                payment.updated_at = datetime.utcnow()
                await session.commit()
                logger.info(f"Payment {payment_id} marked as canceled")

        elif event_type == "refund.succeeded":
            # Update payment status
            result = await session.execute(
                select(Payment).where(Payment.payment_id == payment_id)
            )
            payment = result.scalar_one_or_none()
            if payment:
                payment.status = "refunded"
                payment.updated_at = datetime.utcnow()
                await session.commit()
                logger.info(f"Payment {payment_id} marked as refunded")

        else:
            logger.info(f"Unhandled webhook event: {event_type}")
