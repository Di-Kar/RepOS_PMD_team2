"""
Запускается cron каждую минуту.
Проверяет повторяющиеся рассылки, у которых next_run <= now,
создаёт новую партию уведомлений и сдвигает next_run.
"""

from croniter import croniter
from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import Campaign, NotificationSchedule
from notifications.services import send_campaign_notifications


class Command(BaseCommand):
    help = "Обработка повторяющихся рассылок (cron)"

    def handle(self, *args, **options):
        now = timezone.now()
        schedules = NotificationSchedule.objects.select_related("campaign").filter(
            is_active=True,
            next_run__lte=now,
        )

        for sched in schedules:
            campaign = sched.campaign
            if campaign.status == Campaign.Status.CANCELLED:
                sched.is_active = False
                sched.save(update_fields=["is_active"])
                continue

            self.stdout.write(
                f"Запуск recurring-рассылки: {campaign.name} (cron: {sched.cron_expression})"
            )

            # Отправляем заявку в notification_api
            result = send_campaign_notifications(campaign)

            self.stdout.write(
                self.style.SUCCESS(
                    f"  → отправлено в notification_api: accepted={result['accepted_count']}"
                )
            )

            # Сдвигаем next_run
            cron = croniter(sched.cron_expression, now)
            sched.next_run = cron.get_next(timezone.datetime)
            sched.last_run = now
            sched.save(update_fields=["next_run", "last_run"])

            self.stdout.write(f"  → следующий запуск: {sched.next_run:%Y-%m-%d %H:%M}")

        if not schedules.exists():
            self.stdout.write("Нет повторяющихся рассылок для запуска")
