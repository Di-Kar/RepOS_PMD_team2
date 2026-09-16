"""
Запускается cron каждую минуту.
"""

from django.core.management.base import BaseCommand

from notifications.services import process_pending_campaigns


class Command(BaseCommand):
    help = "Отправка pending-кампаний в notification_api (cron)"

    def handle(self, *args, **options):
        count = process_pending_campaigns()
        if count:
            self.stdout.write(
                self.style.SUCCESS(f"Отправлено {count} кампаний в notification_api")
            )
        else:
            self.stdout.write("Нет кампаний для отправки")
