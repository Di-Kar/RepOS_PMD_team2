"""Страницы профилей и аудита их просмотра в /admin/: живые запросы в
user_profiles (internal API).

profiles_list — доступ через profiles_proxy.view_profile, поиск и пагинация
на стороне user_profiles (GET /api/v1/profiles, §2). audit_list — доступ
через отдельное profiles_proxy.view_audit (роль audit, issue #117), только
чтение журнала (GET /api/v1/profiles/audit, §3)."""

import logging
import math

import requests
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

logger = logging.getLogger(__name__)

PAGE_SIZE = 20
VIEW_PERMISSION = 'profiles_proxy.view_profile'
AUDIT_VIEW_PERMISSION = 'profiles_proxy.view_audit'


def _parse_page(raw: str) -> int:
    try:
        return max(int(raw), 1)
    except ValueError:
        return 1


def profiles_list(request):
    if not request.user.has_perm(VIEW_PERMISSION):
        raise PermissionDenied

    search = request.GET.get('search', '').strip()
    page = _parse_page(request.GET.get('page', '1'))

    context = admin.site.each_context(request)
    context.update(
        title='Профили пользователей',
        search=search,
        searched=bool(search),
        page=page,
        items=[],
        total=0,
        pages=0,
        error=None,
    )

    if not search:
        # Без поискового запроса в user_profiles вообще не ходим: иначе
        # страница сразу при открытии показывала бы ФИО/телефоны всех
        # пользователей постранично — список должен быть виден только
        # результатом явного поиска администратора.
        return render(request, 'profiles_proxy/profiles_list.html', context)

    try:
        response = requests.get(
            f'{settings.PROFILES_SERVICE_URL}/api/v1/profiles',
            params={'page': page, 'page_size': PAGE_SIZE, 'search': search},
            headers={
                'X-Internal-Api-Key': settings.PROFILES_INTERNAL_API_KEY,
                # Аудит просмотра (контракт §3): самозаявленный заголовок, как и в карточке
                'X-Admin-Email': request.user.email,
            },
            timeout=settings.PROFILES_SERVICE_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('user_profiles недоступен: %s', exc)
        context['error'] = 'Сервис профилей недоступен'
    else:
        if response.status_code == 200:
            data = response.json()
            context.update(
                items=data['items'],
                total=data['total'],
                pages=math.ceil(data['total'] / PAGE_SIZE),
            )
        else:
            logger.warning('user_profiles вернул %s на листинг', response.status_code)
            context['error'] = f'Сервис профилей вернул ошибку {response.status_code}'

    return render(request, 'profiles_proxy/profiles_list.html', context)


def audit_list(request):
    """Журнал просмотра профилей администраторами (issue #117) — только
    чтение, записи пишет сам user_profiles при обращении к профилям
    (docs/user_profiles_contract.md §3). Доступ — отдельное право
    view_audit (роль audit), независимое от view_profile."""
    if not request.user.has_perm(AUDIT_VIEW_PERMISSION):
        raise PermissionDenied

    page = _parse_page(request.GET.get('page', '1'))

    context = admin.site.each_context(request)
    context.update(
        title='Аудит просмотра профилей',
        page=page,
        items=[],
        total=0,
        pages=0,
        error=None,
    )

    try:
        response = requests.get(
            f'{settings.PROFILES_SERVICE_URL}/api/v1/profiles/audit',
            params={'page': page, 'page_size': PAGE_SIZE},
            headers={'X-Internal-Api-Key': settings.PROFILES_INTERNAL_API_KEY},
            timeout=settings.PROFILES_SERVICE_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('user_profiles недоступен: %s', exc)
        context['error'] = 'Сервис профилей недоступен'
    else:
        if response.status_code == 200:
            data = response.json()
            context.update(
                items=data['items'],
                total=data['total'],
                pages=math.ceil(data['total'] / PAGE_SIZE),
            )
        else:
            logger.warning('user_profiles вернул %s на аудит', response.status_code)
            context['error'] = f'Сервис профилей вернул ошибку {response.status_code}'

    return render(request, 'profiles_proxy/audit_list.html', context)
