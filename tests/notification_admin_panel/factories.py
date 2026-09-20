import uuid
from django.contrib.auth import get_user_model
from notifications.models import MessageTemplate, Campaign, NotificationContent, Notification

User = get_user_model()


def create_user(**kwargs):
    # По умолчанию создаём обычного пользователя, но позволяем переопределить is_staff
    defaults = {"username": f"user_{uuid.uuid4().hex[:8]}", "password": "testpass", "is_staff": False}
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def create_template(save=True, **kwargs):
    defaults = {
        "name": f"Template {uuid.uuid4().hex[:6]}",
        "channel": "email",
        "subject": "Test subject",
        "body": "<p>Hello, {{ user.name }}!</p>",
        "available_variables": ["user.name"],
        "is_active": True,
    }
    defaults.update(kwargs)
    instance = MessageTemplate(**defaults)
    if save:
        instance.save()
    return instance


def create_campaign(template=None, save=True, **kwargs):
    if template is None:
        template = create_template()
    defaults = {
        "name": f"Campaign {uuid.uuid4().hex[:6]}",
        "template": template,
        "delivery_channel": "email",
        "schedule_type": "immediate",
        "recipient_ids": [str(uuid.uuid4()) for _ in range(3)],
        "status": "draft",
    }
    defaults.update(kwargs)
    instance = Campaign(**defaults)
    if save:
        instance.save()
    return instance


def random_uuids(n: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(n)]