from croniter import croniter
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from notifications.api.api_views import manager_required

from .forms import CampaignForm, MessageTemplateForm
from .models import Campaign, MessageTemplate, Notification, NotificationSchedule


# ── Dashboard ────────────────────────────────
@manager_required
def dashboard(request):
    ctx = {
        "templates_count": MessageTemplate.objects.filter(is_active=True).count(),
        "campaigns_count": Campaign.objects.count(),
        "pending_count": Notification.objects.filter(status="pending").count(),
        "sent_today": Notification.objects.filter(
            status="sent",
            sent_at__date=timezone.now().date(),
        ).count(),
        "recent_campaigns": Campaign.objects.all()[:10],
    }
    return render(request, "dashboard.html", ctx)  # ← изменено


# ── CRUD шаблонов ────────────────────────────
@manager_required
def template_list(request):
    return render(
        request,
        "template_list.html",
        {  # ← изменено
            "templates": MessageTemplate.objects.all(),
        },
    )


@manager_required
def template_create(request):
    if request.method == "POST":
        form = MessageTemplateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Шаблон создан.")
            return redirect("template_list")
    else:
        form = MessageTemplateForm()
    return render(
        request,
        "template_form.html",
        {  # ← изменено
            "form": form,
            "title": "Новый шаблон",
        },
    )


@manager_required
def template_edit(request, pk):
    obj = get_object_or_404(MessageTemplate, pk=pk)
    if request.method == "POST":
        form = MessageTemplateForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Шаблон обновлён.")
            return redirect("template_list")
    else:
        form = MessageTemplateForm(instance=obj)
    return render(
        request,
        "template_form.html",
        {  # ← изменено
            "form": form,
            "title": f"Редактирование: {obj.name}",
        },
    )


@manager_required
def template_delete(request, pk):
    obj = get_object_or_404(MessageTemplate, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Шаблон удалён.")
        return redirect("template_list")
    return render(
        request,
        "template_form.html",
        {  # ← изменено
            "form": None,
            "title": f"Удалить: {obj.name}?",
            "delete_obj": obj,
        },
    )


# ── Рассылки ─────────────────────────────────
@manager_required
def campaign_list(request):
    return render(
        request,
        "campaign_list.html",
        {  # ← изменено
            "campaigns": Campaign.objects.select_related("template").all(),
        },
    )


@manager_required
def campaign_create(request):
    if request.method == "POST":
        form = CampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save(commit=False)
            campaign.created_by = request.user

            # Генерируем request_id для идемпотентности
            import uuid

            campaign.request_id = uuid.uuid4()
            campaign.save()

            if campaign.schedule_type in (
                Campaign.ScheduleType.IMMEDIATE,
                Campaign.ScheduleType.DELAYED,
            ):
                campaign.status = Campaign.Status.SCHEDULED
                campaign.save(update_fields=["status"])
                messages.success(
                    request,
                    "Рассылка создана и поставлена в очередь. "
                    "Будет отправлена в notification_api в ближайшую минуту.",
                )

            elif campaign.schedule_type == Campaign.ScheduleType.RECURRING:
                if not campaign.cron_expression:
                    messages.error(request, "Укажите cron-выражение!")
                    return redirect("campaign_edit", pk=campaign.pk)
                base = timezone.now()
                cron = croniter(campaign.cron_expression, base)
                next_dt = cron.get_next(timezone.datetime)
                NotificationSchedule.objects.create(
                    campaign=campaign,
                    cron_expression=campaign.cron_expression,
                    next_run=next_dt,
                    is_active=True,
                )
                campaign.status = Campaign.Status.SCHEDULED
                campaign.save(update_fields=["status"])
                messages.success(
                    request,
                    f"Повторяющаяся рассылка запланирована. "
                    f"Ближайший запуск: {next_dt:%Y-%m-%d %H:%M}",
                )

            return redirect("campaign_list")
    else:
        form = CampaignForm()
    return render(
        request,
        "campaign_form.html",
        {  # ← изменено
            "form": form,
            "title": "Новая рассылка",
        },
    )


@manager_required
def campaign_edit(request, pk):
    obj = get_object_or_404(Campaign, pk=pk)
    if request.method == "POST":
        form = CampaignForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Рассылка обновлена.")
            return redirect("campaign_list")
    else:
        form = CampaignForm(instance=obj)
    return render(
        request,
        "campaign_form.html",
        {  # ← изменено
            "form": form,
            "title": f"Редактирование: {obj.name}",
        },
    )
