"""Статичные HTML-страницы для GET /r/{code}. Одна страница на исход,
без параметризации данными — заводить Jinja2/шаблоны ради пары строк
избыточно (см. docs/link_shortener_contract.md §2)."""

NOT_FOUND_HTML = """<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Ссылка недействительна</title></head>
<body style="font-family:sans-serif;text-align:center;padding:4rem">
<h1>Ссылка не найдена или истекла</h1>
<p>Возможно, вы уже воспользовались ей раньше, либо срок её действия закончился.</p>
</body>
</html>"""

SERVICE_UNAVAILABLE_HTML = """<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Временная ошибка</title></head>
<body style="font-family:sans-serif;text-align:center;padding:4rem">
<h1>Не получилось обработать ссылку</h1>
<p>Сервис временно недоступен, попробуйте перейти по ссылке ещё раз через пару минут.</p>
</body>
</html>"""
