"""Страница профилей в /admin/: живой запрос в user_profiles (internal API).

Доступ — через право profiles_proxy.view_profile. Поиск и пагинация идут на
сторону user_profiles (GET /api/v1/profiles, docs/user_profiles_contract.md §2).
"""

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
        page=page,
        items=[],
        total=0,
        pages=0,
        error=None,
    )

    params = {'page': page, 'page_size': PAGE_SIZE}
    if search:
        params['search'] = search
    try:
        response = requests.get(
            f'{settings.PROFILES_SERVICE_URL}/api/v1/profiles',
            params=params,
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
