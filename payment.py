"""
Заглушка платёжной системы (YooKassa).
В продакшене здесь будет реальное взаимодействие с API YooKassa.
"""

import logging

from database import add_transaction

logger = logging.getLogger(__name__)


async def process_payment(user_id: int, amount: float, plan: str) -> bool:
    """
    Обработка оплаты (stub).

    В реальной реализации:
      1. Создаётся платёж через YooKassa API.
      2. Пользователь перенаправляется на страницу оплаты.
      3. Webhook подтверждает успешную оплату.

    Сейчас — сразу записываем транзакцию как успешную.
    """
    logger.info(
        "Обработка платежа: user=%s, amount=%s ₽, plan=%s",
        user_id, amount, plan,
    )
    await add_transaction(user_id, amount, "success")
    return True
