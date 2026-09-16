"""
Бизнес-логика: создание уведомлений, рендеринг, «отправка».
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import DateTimeField, ExpressionWrapper, F
from django.utils import timezone

from .models import Campaign, CampaignSendLog
from .notification_api_client import get_notification_api_client

logger = logging.getLogger(__name__)


def send_campaign_notifications(campaign: Campaign) -> dict:
    """Отправляет заявку в notification_api для всей кампании."""
    client = get_notification_api_client()

    recipient_ids = campaign.get_recipient_list()
    if not recipient_ids:
        logger.warning("Campaign %s has no recipients", campaign.pk)
        return {
            "success": False,
            "error": "No recipients",
            "accepted_count": 0,
        }

    result = client.send_notification_request(
        channel=campaign.delivery_channel,
        recipient_ids=recipient_ids,
        occurred_at=timezone.now().isoformat(),
        template_id=str(campaign.template_id),
        campaign_id=str(campaign.id),
        request_id=campaign.request_id,
        context={},
    )

    campaign.last_send_status = "api_accepted" if result.is_success else "api_rejected"
    campaign.last_send_accepted_count = result.accepted_count
    campaign.last_send_at = timezone.now()
    campaign.last_send_errors = result.errors
    campaign.save(
        update_fields=[
            "last_send_status",
            "last_send_accepted_count",
            "last_send_at",
            "last_send_errors",
        ]
    )

    CampaignSendLog.objects.create(
        campaign=campaign,
        request_id=result.request_id,
        status=result.status,
        accepted_count=result.accepted_count,
        rejected_count=len(result.rejected_recipients),
        errors=result.errors
        + [f"{r['user_id']}: {r['reason']}" for r in result.rejected_recipients],
    )

    logger.info(
        "Campaign %s sent to notification_api: request_id=%s, accepted=%d, rejected=%d",
        campaign.pk,
        result.request_id,
        result.accepted_count,
        len(result.rejected_recipients),
    )

    return {
        "success": result.is_success,
        "request_id": result.request_id,
        "accepted_count": result.accepted_count,
        "rejected_count": len(result.rejected_recipients),
        "errors": result.errors,
    }


def process_pending_campaigns() -> int:
    """
    Обрабатывает кампании с schedule_type=immediate или delayed,
    у которых пришло время отправки.
    """
    now = timezone.now()

    # Немедленные кампании (созданы, но ещё не отправлены)
    immediate_campaigns = Campaign.objects.filter(
        schedule_type=Campaign.ScheduleType.IMMEDIATE,
        last_send_status="pending",
    )

    # Отложенные кампании — используем annotate для вычисления времени отправки
    # created_at + delay_hours <= now
    delayed_campaigns = (
        Campaign.objects.filter(
            schedule_type=Campaign.ScheduleType.DELAYED,
            last_send_status="pending",
        )
        .annotate(
            send_time=ExpressionWrapper(
                F("created_at") + F("delay_hours") * timedelta(hours=1),
                output_field=DateTimeField(),
            )
        )
        .filter(send_time__lte=now)
    )

    sent_count = 0
    for campaign in list(immediate_campaigns) + list(delayed_campaigns):
        result = send_campaign_notifications(campaign)
        if result["success"]:
            sent_count += 1

    return sent_count
