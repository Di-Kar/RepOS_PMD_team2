"""Утилиты общего назначения для приложения."""

from typing import Optional


def get_device_type(user_agent: Optional[str]) -> str:
    """
    Определяет тип устройства на основе строки User-Agent.

    Правила:
    - 'mobile': содержит 'mobile', 'android' или 'iphone'
    - 'smart': содержит 'smart' или 'tv'
    - 'web': все остальные случаи (по умолчанию)

    Args:
        user_agent: Строка User-Agent из заголовков HTTP-запроса.

    Returns:
        Строка: 'mobile', 'smart' или 'web'.
    """
    if not user_agent:
        return "web"

    ua_lower = user_agent.lower()

    # Проверка на мобильные устройства
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        return "mobile"

    # Проверка на Smart TV и подобные устройства
    if "smart" in ua_lower or "tv" in ua_lower:
        return "smart"

    # По умолчанию считаем обычным веб-браузером
    return "web"
