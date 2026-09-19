# Добавляет статус 'skipped' в Notification.Status — пишет
# notification_worker (S10_T3, issue #96), когда пользователь неактивен
# либо канал ещё не реализован. Не требует ALTER TABLE на уровне БД —
# status остаётся обычным CharField без db-level CHECK-ограничения, эта
# миграция только обновляет метаданные поля (choices) для консистентности
# с админкой (list_filter/форма).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_alter_campaignsendlog_options_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Ожидает'),
                    ('sending', 'Отправляется'),
                    ('sent', 'Отправлено'),
                    ('failed', 'Ошибка'),
                    ('skipped', 'Пропущено'),
                ],
                default='pending',
                max_length=20,
                verbose_name='Статус',
            ),
        ),
    ]
