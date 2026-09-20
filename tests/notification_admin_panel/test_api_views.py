import uuid
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from notifications.models import Campaign, MessageTemplate
from .factories import create_user, create_template, random_uuids


class TemplateAPITest(TestCase):
    """CRUD шаблонов через API с проверкой прав."""

    def setUp(self):
        self.client = APIClient()
        # ВАЖНО: Пользователь ДОЛЖЕН быть администратором или в группе 'notification_managers'
        self.user = create_user(is_staff=True) 
        self.client.force_authenticate(user=self.user)

    def test_create_template_valid(self):
        response = self.client.post("/api/v1/templates/", {
            "name": "Test", "channel": "email",
            "subject": "Hi {{ user.name }}", "body": "<p>{{ user.name }}</p>",
            "available_variables": ["user.name"],
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unauthorized_user_gets_403(self):
        """Обычный пользователь без прав получает 403 Forbidden."""
        regular_user = create_user(is_staff=False)
        self.client.force_authenticate(user=regular_user)
        
        response = self.client.get("/api/v1/templates/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CampaignAPITest(TestCase):
    """CRUD кампаний через API."""

    def setUp(self):
        self.client = APIClient()
        self.user = create_user(is_staff=True)
        self.client.force_authenticate(user=self.user)
        self.template = create_template()

    def test_create_immediate_campaign(self):
        response = self.client.post("/api/v1/campaigns/", {
            "name": "Test", "template_id": self.template.pk,
            "delivery_channel": "email", "schedule_type": "immediate",
            "recipient_ids": random_uuids(2),
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        campaign = Campaign.objects.get(pk=response.data["id"])
        self.assertEqual(campaign.status, "scheduled")

    def test_cancel_campaign(self):
        campaign = Campaign.objects.create(
            name="Test", template=self.template, delivery_channel="email",
            schedule_type="immediate", recipient_ids=random_uuids(1), status="scheduled",
        )
        response = self.client.delete(f"/api/v1/campaigns/{campaign.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "cancelled")