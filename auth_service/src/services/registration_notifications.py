"""Оркестратор welcome-уведомления при регистрации: создаёт короткую ссылку
подтверждения email через link_shortener_service и встраивает её в письмо,
отправляемое через notification_api.

Если создать ссылку не удалось (link_shortener_service недоступен) — письмо
всё равно уходит, просто без упоминания подтверждения. Полное молчание после
успешной регистрации хуже: это единственное уведомление пользователю, что
аккаунт вообще создан, а стиль деградации везде в этом файле — "отправить,
что можем", не "молчать" (см. notification_client.py)."""

import logging
import uuid

from src.services.link_client import create_email_confirmation_link
from src.services.notification_client import send_notification

logger = logging.getLogger(__name__)

WELCOME_SUBJECT = "Регистрация завершена"


async def send_welcome_with_confirmation(user_id: uuid.UUID) -> None:
    confirm_url = await create_email_confirmation_link(user_id)
    if confirm_url:
        text = (
            "Добро пожаловать! Ваш аккаунт создан.\n\n"
            f"Пожалуйста, подтвердите email по ссылке: {confirm_url}\n"
            "Ссылка действительна ограниченное время."
        )
    else:
        logger.warning(
            "email confirmation link unavailable for user_id=%s, "
            "sending plain welcome email without it",
            user_id,
        )
        text = "Добро пожаловать! Ваш аккаунт создан."
    await send_notification(recipient_id=user_id, subject=WELCOME_SUBJECT, text=text)
