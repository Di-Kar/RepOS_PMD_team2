"""Тесты REST API endpoints."""

from django.test import TestCase
from notifications.models import Campaign
from rest_framework import status
from rest_framework.test import APIClient

from tests.notification_admin_panel.factories import (
    create_template,
    create_user,
    random_uuids,
)


class TemplateAPITest(TestCase):
    """CRUD шаблонов через API."""

    def setUp(self):
        self.client = APIClient()
        self.user = create_user()
        self.client.force_authenticate(user=self.user)

    def test_create_template_valid(self):
        response = self.client.post(
            "/api/v1/templates/",
            {
                "name": "Test",
                "channel": "email",
                "subject": "Hi {{ user.name }}",
                "body": "<p>{{ user.name }}</p>",
                "available_variables": ["user.name"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_template_invalid_syntax(self):
        response = self.client.post(
            "/api/v1/templates/",
            {
                "name": "Bad",
                "channel": "email",
                "body": "{{ user.name",
                "available_variables": ["user.name"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_templates(self):
        create_template()
        create_template()
        response = self.client.get("/api/v1/templates/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_filter_by_channel(self):
        create_template(channel="email")
        create_template(channel="sms")
        response = self.client.get("/api/v1/templates/?channel=email")
        self.assertEqual(response.data["count"], 1)

    def test_delete_template_in_use_returns_409(self):
        template = create_template()
        # Создаём активную кампанию, использующую шаблон
        Campaign.objects.create(
            name="Active",
            template=template,
            delivery_channel="email",
            schedule_type="immediate",
            recipient_ids=random_uuids(1),
            status="scheduled",
        )
        response = self.client.delete(f"/api/v1/templates/{template.pk}/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


class TemplateValidateAPITest(TestCase):
    """POST /api/v1/templates/validate/"""

    def setUp(self):
        self.client = APIClient()
        self.user = create_user()
        self.client.force_authenticate(user=self.user)

    def test_valid_template(self):
        response = self.client.post(
            "/api/v1/templates/validate/",
            {
                "body": "Hi {{ user.name }}",
                "subject": "Test",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["valid"])
        self.assertIn("Иван Иванов", response.data["rendered_preview"]["body"])

    def test_invalid_template(self):
        response = self.client.post(
            "/api/v1/templates/validate/",
            {
                "body": "{{ user.name",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")


class CampaignAPITest(TestCase):
    """CRUD кампаний через API."""

    def setUp(self):
        self.client = APIClient()
        self.user = create_user()
        self.client.force_authenticate(user=self.user)
        self.template = create_template()

    def test_create_immediate_campaign(self):
        response = self.client.post(
            "/api/v1/campaigns/",
            {
                "name": "Test",
                "template_id": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "immediate",
                "recipient_ids": random_uuids(2),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        campaign = Campaign.objects.get(pk=response.data["id"])
        self.assertEqual(campaign.status, "scheduled")

    def test_create_delayed_requires_hours(self):
        response = self.client.post(
            "/api/v1/campaigns/",
            {
                "name": "Test",
                "template_id": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "delayed",
                "recipient_ids": random_uuids(1),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_recurring_requires_cron(self):
        response = self.client.post(
            "/api/v1/campaigns/",
            {
                "name": "Test",
                "template_id": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "recurring",
                "recipient_ids": random_uuids(1),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_campaign(self):
        campaign = Campaign.objects.create(
            name="Test",
            template=self.template,
            delivery_channel="email",
            schedule_type="immediate",
            recipient_ids=random_uuids(1),
            status="scheduled",
        )
        response = self.client.delete(f"/api/v1/campaigns/{campaign.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "cancelled")

    def test_unauthorized_returns_401(self):
        client = APIClient()  # Без аутентификации
        response = client.get("/api/v1/campaigns/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class DashboardAPITest(TestCase):
    """GET /api/v1/dashboard/"""

    def setUp(self):
        self.client = APIClient()
        self.user = create_user()
        self.client.force_authenticate(user=self.user)

    def test_dashboard_stats(self):
        create_template()
        response = self.client.get("/api/v1/dashboard/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("templates_count", response.data)
        self.assertIn("campaigns_count", response.data)
        self.assertIn("pending_count", response.data)
        self.assertIn("sent_today", response.data)
