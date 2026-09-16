from django.contrib import admin

from .models import (
    Campaign,
    MessageTemplate,
    Notification,
    NotificationContent,
    NotificationHistory,
    NotificationSchedule,
)


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "channel", "is_active", "updated_at")
    list_filter = ("channel", "is_active")
    search_fields = ("name", "subject")


@admin.register(NotificationContent)
class NotificationContentAdmin(admin.ModelAdmin):
    list_display = ("content_id", "template", "created_at")
    readonly_fields = ("content_id",)


class NotificationScheduleInline(admin.StackedInline):
    model = NotificationSchedule
    extra = 0


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "template",
        "schedule_type",
        "status",
        "created_by",
        "created_at",
    )
    list_filter = ("status", "schedule_type", "delivery_channel")
    search_fields = ("name",)
    inlines = [NotificationScheduleInline]
    readonly_fields = ("created_by",)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "notification_id",
        "user_id",
        "channel",
        "status",
        "scheduled_at",
        "sent_at",
    )
    list_filter = ("status", "channel")
    search_fields = ("notification_id", "user_id")
    readonly_fields = ("notification_id", "content")


@admin.register(NotificationHistory)
class NotificationHistoryAdmin(admin.ModelAdmin):
    list_display = ("notification", "status", "sent_at", "delivery_provider")
    list_filter = ("status",)
    readonly_fields = ("notification", "status", "sent_at", "error_message")
