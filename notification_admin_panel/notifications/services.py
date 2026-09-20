"""
Бизнес-логика: создание уведомлений, рендеринг, «отправка».
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.db.models import DateTimeField, ExpressionWrapper, F, Q
from django.utils import timezone

from .models import Campaign, CampaignSendLog
from .notification_api_client import get_notification_api_client

logger = logging.getLogger(__name__)


def send_campaign_notifications(
    campaign: Campaign, force_new_request_id: bool = False
) -> dict:
    """
    Отправляет заявку в notification_api для всей кампании.

    Args:
        campaign: Экземпляр кампании.
        force_new_request_id: Если True, генерирует новый request_id для этого запуска.
                              Необходимо для recurring-рассылок, чтобы
                              downstream-воркер не считал новый запуск дубликатом старого.
                              При retry временной ошибки должен быть False, чтобы
                              использовать тот же current_run_request_id.
    """
    client = get_notification_api_client()

    recipient_ids = campaign.get_recipient_list()
    if not recipient_ids:
        logger.warning("Campaign %s has no recipients", campaign.pk)
        return {
            "success": False,
            "error": "No recipients",
            "accepted_count": 0,
        }

    # --- ЛОГИКА ВЫБОРА REQUEST_ID (Проблема #3) ---
    if force_new_request_id:
        # Для recurring или ручного "Send Now" создаём новый ID запуска
        run_request_id = uuid.uuid4()
        campaign.current_run_request_id = run_request_id
    else:
        # Для retry используем сохранённый ID текущего запуска.
        # Если его ещё нет (первый запуск без force_new_request_id), инициализируем его базовым request_id кампании.
        if not campaign.current_run_request_id:
            campaign.current_run_request_id = campaign.request_id
        run_request_id = campaign.current_run_request_id

    result = client.send_notification_request(
        channel=campaign.delivery_channel,
        recipient_ids=recipient_ids,
        occurred_at=timezone.now().isoformat(),
        template_id=str(campaign.template_id),
        campaign_id=str(campaign.id),
        request_id=run_request_id,
        context={},
    )

    # --- ОБНОВЛЕНИЕ СТАТУСА С УЧЁТОМ ВРЕМЕННЫХ СБОЕВ (Проблема #5) ---
    now = timezone.now()

    if result.is_temporary_error:
        # Временный сбой (таймаут, 5xx): помечаем для повторной попытки
        campaign.last_send_status = "pending_retry"
        # Простой backoff: следующая попытка через 5 минут
        campaign.next_retry_at = now + timedelta(minutes=5)
    elif result.is_success:
        # Успех: очищаем флаг retry
        campaign.last_send_status = "api_accepted"
        campaign.next_retry_at = None
    else:
        # Постоянная ошибка (например, 400 Bad Request из-за невалидных данных): retry бесполезен
        campaign.last_send_status = "api_rejected"
        campaign.next_retry_at = None

    campaign.last_send_accepted_count = result.accepted_count
    campaign.last_send_at = now
    campaign.last_send_errors = result.errors

    campaign.save(
        update_fields=[
            "current_run_request_id",
            "last_send_status",
            "last_send_accepted_count",
            "last_send_at",
            "last_send_errors",
            "next_retry_at",
        ]
    )

    # Логирование попытки
    CampaignSendLog.objects.create(
        campaign=campaign,
        request_id=run_request_id,
        status=result.status,
        accepted_count=result.accepted_count,
        rejected_count=len(result.rejected_recipients),
        errors=result.errors
        + [f"{r['user_id']}: {r['reason']}" for r in result.rejected_recipients],
    )

    logger.info(
        "Campaign %s sent to notification_api: request_id=%s, status=%s, accepted=%d, rejected=%d, temp_error=%s",
        campaign.pk,
        run_request_id,
        result.status,
        result.accepted_count,
        len(result.rejected_recipients),
        result.is_temporary_error,
    )

    return {
        "success": result.is_success,
        "request_id": run_request_id,
        "accepted_count": result.accepted_count,
        "rejected_count": len(result.rejected_recipients),
        "errors": result.errors,
        "is_temporary_error": result.is_temporary_error,
    }


def process_pending_campaigns() -> int:
    """
    Обрабатывает кампании с schedule_type=immediate или delayed,
    у которых пришло время отправки, или которые требуют повторной попытки.
    """
    now = timezone.now()

    # --- ФИЛЬТРАЦИЯ (Проблема #4 и #5) ---
    # 1. status__in=[DRAFT, SCHEDULED]: Игнорируем CANCELLED кампании (Проблема #4)
    # 2. last_send_status: берём 'pending' (первый запуск) ИЛИ 'pending_retry' с наступившим next_retry_at (Проблема #5)

    base_queryset = Campaign.objects.filter(
        schedule_type__in=[
            Campaign.ScheduleType.IMMEDIATE,
            Campaign.ScheduleType.DELAYED,
        ],
        status__in=[Campaign.Status.DRAFT, Campaign.Status.SCHEDULED],  # <-- FIX #4
    ).filter(
        Q(last_send_status="pending")
        | Q(last_send_status="pending_retry", next_retry_at__lte=now)  # <-- FIX #5
    )

    # Для отложенных кампаний добавляем условие: время создания + задержка <= сейчас
    delayed_queryset = (
        base_queryset.filter(
            schedule_type=Campaign.ScheduleType.DELAYED,
        )
        .annotate(
            send_time=ExpressionWrapper(
                F("created_at") + F("delay_hours") * timedelta(hours=1),
                output_field=DateTimeField(),
            )
        )
        .filter(send_time__lte=now)
    )

    # Немедленные кампании (без задержки)
    immediate_queryset = base_queryset.filter(
        schedule_type=Campaign.ScheduleType.IMMEDIATE,
    )

    # Объединяем и оцениваем QuerySet
    campaigns_to_process = list(immediate_queryset) + list(delayed_queryset)

    sent_count = 0
    for campaign in campaigns_to_process:
        # Дополнительная защита от race condition: проверяем статус прямо перед отправкой
        if campaign.status == Campaign.Status.CANCELLED:
            logger.warning("Skipping cancelled campaign %s", campaign.pk)
            continue

        # force_new_request_id=False: используем сохранённый current_run_request_id для идемпотентности retry
        result = send_campaign_notifications(campaign, force_new_request_id=False)

        if result["success"]:
            sent_count += 1

    return sent_count
