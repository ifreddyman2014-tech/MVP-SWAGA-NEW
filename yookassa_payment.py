"""
Интеграция с YooKassa для приёма платежей.
Документация: https://yookassa.ru/developers/api
"""

import logging
import uuid
from typing import Optional

from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification

from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, BOT_USERNAME

logger = logging.getLogger(__name__)

# Инициализация YooKassa
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY


def create_payment(
    amount: float,
    user_id: int,
    plan_key: str,
    server_id: str = "",
    description: str = "SWAGA VPN подписка",
) -> Optional[dict]:
    """
    Создать платёж в YooKassa.

    Возвращает:
        {
            "payment_id": str,
            "confirmation_url": str,  # Ссылка для оплаты
        }
    """
    try:
        idempotence_key = str(uuid.uuid4())

        # Метаданные для идентификации платежа в webhook
        metadata = {
            "user_id": str(user_id),
            "plan_key": plan_key,
            "server_id": server_id,
        }

        payment = Payment.create({
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": f"https://t.me/{BOT_USERNAME}"
            },
            "capture": True,  # Автоматическое подтверждение платежа
            "description": description,
            "metadata": metadata,
        }, idempotence_key)

        logger.info(
            "Создан платёж: id=%s, user=%s, amount=%s, plan=%s",
            payment.id, user_id, amount, plan_key
        )

        return {
            "payment_id": payment.id,
            "confirmation_url": payment.confirmation.confirmation_url,
        }

    except Exception as e:
        logger.error("Ошибка создания платежа: %s", e)
        return None


def check_payment_status(payment_id: str) -> Optional[str]:
    """
    Проверить статус платежа.

    Возвращает: "pending", "waiting_for_capture", "succeeded", "canceled" или None
    """
    try:
        payment = Payment.find_one(payment_id)
        return payment.status
    except Exception as e:
        logger.error("Ошибка проверки статуса платежа %s: %s", payment_id, e)
        return None


def parse_webhook(request_body: str) -> Optional[dict]:
    """
    Распарсить webhook от YooKassa.

    Возвращает:
        {
            "event": str,  # "payment.succeeded", "payment.canceled", etc.
            "payment_id": str,
            "status": str,
            "amount": float,
            "user_id": int,
            "plan_key": str,
            "server_id": str,
        }
    """
    try:
        notification = WebhookNotification(request_body)
        payment = notification.object

        metadata = payment.metadata or {}

        return {
            "event": notification.event,
            "payment_id": payment.id,
            "status": payment.status,
            "amount": float(payment.amount.value),
            "user_id": int(metadata.get("user_id", 0)),
            "plan_key": metadata.get("plan_key", ""),
            "server_id": metadata.get("server_id", ""),
        }

    except Exception as e:
        logger.error("Ошибка парсинга webhook: %s", e)
        return None


def get_payment_info(payment_id: str) -> Optional[dict]:
    """
    Получить полную информацию о платеже.
    """
    try:
        payment = Payment.find_one(payment_id)
        metadata = payment.metadata or {}

        return {
            "payment_id": payment.id,
            "status": payment.status,
            "amount": float(payment.amount.value),
            "currency": payment.amount.currency,
            "description": payment.description,
            "user_id": int(metadata.get("user_id", 0)),
            "plan_key": metadata.get("plan_key", ""),
            "server_id": metadata.get("server_id", ""),
            "created_at": payment.created_at,
            "paid": payment.paid,
        }

    except Exception as e:
        logger.error("Ошибка получения информации о платеже %s: %s", payment_id, e)
        return None
