# 📋 Краткая инструкция по работе с `notification_admin_panel`

## 🔍 1. Диагностика (что происходит)

```bash
# Статус контейнера
docker compose ps notification_admin_panel

# Логи (последние 50 строк)
docker compose logs --tail=50 notification_admin_panel
```

**Если в логах** `"python3"` без аргументов — проблема в `Dockerfile` или `docker-compose.yml`.

---

## 🔧 2. Быстрое исправление

### Проверьте `notification_admin_panel/Dockerfile`
В конце **не должно** быть `CMD ["python3"]`. Должно быть:
```dockerfile
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

---

## ✅ 3. Проверка работоспособности

```bash
# Должен быть статус "Up"
docker compose ps notification_admin_panel

# Должно быть "System check identified no issues"
docker compose exec notification_admin_panel python manage.py check

# Создание суперпользователя (если ещё не создан)
docker compose exec notification_admin_panel python manage.py createsuperuser
```

**Открыть в браузере:**
- HTML-панель: `http://localhost:8005/panel/`
- Django-админка: `http://localhost:8005/admin/`
- Swagger API: `http://localhost:8005/api/v1/docs/`

---

## 🛠 4. Полезные команды

| Действие | Команда |
|---|---|
| Логи в реальном времени | `docker compose logs -f notification_admin_panel` |
| Зайти в контейнер | `docker compose exec notification_admin_panel bash` |
| Подключение к БД | `docker compose exec notification_postgres psql -U notify_user -d notifications_db` |
| Применить миграции | `docker compose exec notification_admin_panel python manage.py migrate` |
| Создать миграцию | `docker compose exec notification_admin_panel python manage.py makemigrations` |
| Запустить тесты | `docker compose exec notification_admin_panel python manage.py test notifications -v 2` |
| Полный сброс БД | `docker compose down -v && docker compose up -d notification_postgres notification_admin_panel` |
| Перезапуск cron | `docker compose restart notification_admin_cron` |



## 🎯 Экспресс-старт с нуля

```bash
docker compose down -v
docker compose build --no-cache notification_admin_panel
docker compose up -d notification_postgres notification_admin_panel notification_admin_cron
docker compose exec notification_admin_panel python manage.py migrate
docker compose exec notification_admin_panel python manage.py createsuperuser
```

Готово! Панель доступна на `http://localhost:8005/panel/`.

