"""Рендер шаблонов уведомлений — Jinja2 поверх message_templates
(notification_admin_panel, Django). Jinja2 выбран вместо встраивания Django
template engine в независимый asyncio-процесс: синтаксис `{{ user.name }}`
для простых переменных совпадает, а поднимать `django.setup()` в воркере
ради этого избыточно. Риск — если менеджеры начнут использовать
Django-специфичные теги/фильтры в шаблонах, потребуется пересмотр (см.
docs плана).

TTL-кэш по template_id в памяти процесса — шаблоны меняются редко
(вручную, через notification_admin_panel), а читаются на каждое
уведомление; отдельный кэш на каждый инстанс воркера, это осознанно (не
Redis) — устаревание в пределах TTL не критично для email-контента."""

import logging
import time

import jinja2

from src.core.config import settings
from src.db import queries
from src.db.postgres import get_pool

logger = logging.getLogger(__name__)

# Undefined (не StrictUndefined) — переменная, которой нет в контексте
# (например user.age/user.gender/user.birthday, которых нет в модели User
# auth_service, см. §3.3 плана), рендерится в '' вместо исключения.
_env = jinja2.Environment(autoescape=False)

_cache: dict[str, tuple[float, dict[str, str]]] = {}


class TemplateNotFoundError(Exception):
    """template_id не парсится как id, не существует в message_templates,
    либо шаблон деактивирован (is_active=false) — постоянная ошибка,
    рендер-стадия трактует любую из этих причин одинаково."""


async def get_template(template_id: str) -> dict[str, str]:
    now = time.monotonic()
    cached = _cache.get(template_id)
    if cached is not None and cached[0] > now:
        return cached[1]

    template = await queries.get_active_template(get_pool(), template_id)
    if template is None:
        raise TemplateNotFoundError(
            f"template_id={template_id} not found or inactive"
        )

    _cache[template_id] = (now + settings.template_cache_ttl_seconds, template)
    return template


def render(
    *, subject_template: str, body_template: str, context: dict
) -> tuple[str, str]:
    """Рендерит subject/body Jinja2-шаблонами с данным контекстом
    (context из Kafka-сообщения + {"user": {...}} от auth_service)."""
    rendered_subject = (
        _env.from_string(subject_template).render(**context) if subject_template else ""
    )
    rendered_body = _env.from_string(body_template).render(**context)
    return rendered_subject, rendered_body
