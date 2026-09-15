# Контракт заявок на уведомления

Контракт границы между `notification_api` (S10_T1, issue #94) — приёмом заявок
на создание уведомлений — и `notification_worker` (S10_T3, issue #96), который
читает Kafka и выполняет фактическую доставку. Также описывает HTTP-вход,
которым пользуется `notification_admin_panel` (S10_T2) и, в дальнейшем, другие
сервисы кинотеатра (S10_T7, issue #100).

## 0. Границы ответственности

- **notification_api** (этот контракт): принимает HTTP-заявку, валидирует,
  разворачивает список получателей в отдельные сообщения Kafka, публикует.
  Не рендерит шаблоны, не ходит за профилем пользователя, не отправляет
  письма/push/sms и не хранит историю статусов — только приём и постановка в
  очередь (issue #94: «Сам API не занимается рассылкой — это центральный узел»).
- **notification_worker** (#96, отдельная задача): читает
  `notifications.requests.v1`, для персонализации сам ходит в `auth_service`
  за именем/email/телефоном по `user_id` (к воркеру эти данные не приходят —
  только `user_id`), рендерит шаблон, отправляет, ведёт у себя историю и
  статусы доставки.
- **Планирование** (отложенные/повторяющиеся рассылки) — ответственность
  вызывающей стороны. У `notification_admin_panel` уже есть свой cron
  (`process_notifications`, `process_recurring`), который решает delay/cron и
  должен вызывать этот API в момент фактической отправки, а не при создании
  кампании. Контракт T1 всегда описывает заявку «отправить сейчас» — полей
  расписания в нём нет.
- **Broadcast «всем пользователям»** (issue #94) — вне scope T1. Ни у
  `admin_panel`, ни у `auth_service` сейчас нет endpoint'а со списком всех
  `user_id`. Контракт принимает только явный список `recipient_ids`; его
  получение — задача вызывающей стороны (см. §8).
- **Каналы**: `email`/`sms`/`push` уже используются в
  `notification_admin_panel`. `websocket` зарезервирован под S10_T4 (issue
  #97) — добавлен в enum уже сейчас, чтобы не делать breaking change схемы
  позже; воркера/консьюмера для него пока нет.

## 1. Топик Kafka

| Топик | Назначение | Ключ |
|---|---|---|
| `notifications.requests.v1` | заявка на отправку одного уведомления одному получателю | `user_id` |

Один топик на все каналы и источники — канал/шаблон/источник различаются
полями сообщения, а не отдельным топиком (тот же принцип, что и
`analytics.custom_events.v1` в `docs/user_events_contract.md`: новый тип
уведомления не требует новой инфраструктуры).

Партиционирование по `user_id` — несколько уведомлений одному пользователю
(повторные попытки, почти одновременные бизнес-события) обрабатываются
воркером по порядку и не обгоняют друг друга.

Фан-аут получателей делает **API**, не воркер: HTTP-заявка может содержать
несколько `recipient_ids`, но в Kafka уходит по одному сообщению на каждого
получателя — это соответствует контракту T3, где воркеру в принципе не может
прийти больше одного `user_id` за раз.

## 2. HTTP API `notification_api`

### `POST /api/v1/notifications`

Одна заявка, возможно на нескольких получателей одного шаблона/сообщения.
Отвечает `202 Accepted` **всегда**, включая случай, когда заявка целиком
невалидна (как и `event_api`: `payload` принимается как `dict`, бизнес-модель
валидируется внутри обработчика, а не FastAPI-биндингом) — клиент не должен
разбирать HTTP-статусы отдельно от бизнес-статуса (тот же приём, что у
`event_api`, NFR-3-аналог). `400` возможен только на уровне самого HTTP (не
JSON, не тот `Content-Type`) — до бизнес-валидации дело не доходит.

Request body — `NotificationRequest`, см. §3.

Response `202`:

```json
{
  "request_id": "5f3e2c1a-0000-4000-8000-000000000010",
  "status": "accepted",
  "accepted_count": 2,
  "rejected_recipients": [],
  "errors": []
}
```

`status`: `accepted` (все получатели приняты) / `partially_accepted` (часть
`recipient_ids` отклонена, остальные приняты) / `rejected` (принятых
получателей ноль — либо заявка целиком не прошла бизнес-валидацию, например
не задано ни `template_id`, ни `text_override`, либо каждый элемент
`recipient_ids` отклонён по отдельности).

`rejected_recipients`: список `{"user_id": "...", "reason": "..."}` для
получателей, отклонённых индивидуально (невалидный UUID и т.п.).

`errors`: список текстовых причин отклонения заявки **целиком** (envelope
не прошёл бизнес-валидацию — например, не задано ни `template_id`, ни
`text_override`, либо отсутствует обязательное поле). Пуст в остальных
случаях — по образцу `EventResult.errors` у `event_api`.

### `POST /api/v1/notifications/batch`

Массив независимых `NotificationRequest` в одном HTTP-вызове — по аналогии с
`/api/v1/events/batch` в `event_api`. Каждая заявка в массиве валидируется и
разворачивается независимо; ошибка в одной не блокирует остальные. Ограничение
размера массива — `NOTIFICATIONS_BATCH_MAX_SIZE` (по аналогии с
`EVENTS_BATCH_MAX_SIZE`).

### Авторизация

Единый `NOTIFICATIONS_API_KEY` на всех вызывающих (admin_panel и позже другие
сервисы по S10_T7) — по образцу `EVENTS_API_KEY` в `event_api`. Значение
`source_service` в теле заявки (см. §3) самозаявленное, криптографически не
проверяется — сознательное упрощение при доверенной внутренней сети; при
необходимости отдельных ключей на сервис-источник (S10_T7) это расширение не
меняет схему сообщения, только добавляет проверку на уровне API-key → allowed
`source_service`.

### Rate limiting

`NOTIFICATIONS_RATE_LIMIT_*`, in-memory лимитер per-instance — по аналогии с
`rate_limiter.py` в `event_api`.

## 3. Поля HTTP-заявки (`NotificationRequest`, до фан-аута)

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| `request_id` | UUID | да | Идентификатор заявки. Один и тот же `request_id` при повторной отправке (ретрай клиента) даёт детерминированные `notification_id` при фан-ауте — см. §6 |
| `source_service` | string | да | Кто вызвал API: `admin_panel`, `auth_service` и т.д. — для аудита/трассировки |
| `campaign_id` | string, nullable | нет | Ссылка на `Campaign` в `notification_admin_panel`, если заявка создана рассылкой |
| `channel` | enum: `email` / `sms` / `push` / `websocket` | да | Канал доставки. `websocket` зарезервирован под S10_T4 |
| `template_id` | string, nullable | да*, если не задан `text_override` | ID шаблона из `notification_admin_panel` (`MessageTemplate.id`) |
| `subject_override` | string, nullable | нет | Переопределяет тему шаблона либо задаёт тему при отсутствии шаблона (актуально для `email`) |
| `text_override` | string, nullable | да*, если не задан `template_id` | Готовый текст сообщения без рендера шаблона — свободный формат (issue #94, п. «отработка событий в свободном формате») |
| `context` | object | нет, default `{}` | Доп. переменные для рендера шаблона (например `{"movie_title": "..."}`). **Не должен** содержать email/телефон/ФИО — эти данные воркер получает сам из `auth_service` по `user_id` |
| `recipient_ids` | array<UUID>, 1..`NOTIFICATIONS_MAX_RECIPIENTS` (default 1000) | да | Получатели заявки; фан-аут выполняет API (§1) |
| `occurred_at` | datetime | да | Когда бизнес-событие произошло на стороне вызывающего |

Ровно одно из `template_id` / `text_override` должно быть задано (см. §5).

## 4. Поля сообщения Kafka (`notifications.requests.v1`, после фан-аута — на одного получателя)

| Поле | Тип | Описание |
|---|---|---|
| `notification_id` | UUID | Детерминированно выводится из `(request_id, user_id)` — см. §6 |
| `request_id` | UUID | Из HTTP-заявки, для корреляции всех уведомлений одной заявки |
| `schema_version` | int | Версионирование схемы (по аналогии с `user_events_contract.md`) |
| `source_service` | string | Из HTTP-заявки |
| `campaign_id` | string, nullable | Из HTTP-заявки |
| `user_id` | UUID | Получатель — совпадает с ключом сообщения |
| `channel` | enum | Из HTTP-заявки |
| `template_id` | string, nullable | Из HTTP-заявки |
| `subject_override` | string, nullable | Из HTTP-заявки |
| `text_override` | string, nullable | Из HTTP-заявки |
| `context` | object | Из HTTP-заявки |
| `occurred_at` | datetime | Из HTTP-заявки |
| `received_at` | datetime | Проставляется `notification_api` в момент публикации |

## 5. Правила валидации

- Ровно одно из `template_id` / `text_override` обязательно. Если задан
  `template_id`, `subject_override`/`text_override` необязательны и трактуются
  воркером как точечное переопределение отрендеренных полей.
- `recipient_ids` — от 1 до `NOTIFICATIONS_MAX_RECIPIENTS` элементов, каждый
  валидный UUID; невалидные элементы не блокируют остальных получателей заявки
  (попадают в `rejected_recipients` ответа, §2), а не всю заявку.
- `channel` — только значения из enum.
- `context` — плоский JSON-объект; сервис не валидирует бизнес-смысл значений,
  только что это JSON-сериализуемые данные.

## 6. Идемпотентность

`notification_api` не имеет собственной БД (см. §0), поэтому дедуп не может
опираться на память сервиса. Вместо этого `notification_id` выводится
детерминированно: `uuid5(NOTIFICATIONS_NAMESPACE, f"{request_id}:{user_id}")`.

Повторная отправка того же HTTP-запроса с тем же `request_id` (ретрай клиента,
NFR-29-аналог из `docs/README.md`) даёт при фан-ауте те же самые
`notification_id`, что и в первый раз. Дедуп по факту происходит на стороне
`notification_worker`, когда он сохраняет историю (уникальный
`notification_id`) — API остаётся stateless, но не мешает дедупу ниже по
потоку.

## 7. Примеры

**HTTP-заявка с шаблоном** (кампания из `notification_admin_panel`, два получателя):

```json
{
  "request_id": "5f3e2c1a-0000-4000-8000-000000000010",
  "source_service": "admin_panel",
  "campaign_id": "42",
  "channel": "email",
  "template_id": "7",
  "context": {},
  "recipient_ids": [
    "550e8400-e29b-41d4-a716-446655440000",
    "6f9619ff-8b86-d011-b42d-00c04fc964ff"
  ],
  "occurred_at": "2026-09-15T10:00:00.000Z"
}
```

**HTTP-заявка в свободном формате** (без шаблона, триггер из другого сервиса, S10_T7):

```json
{
  "request_id": "5f3e2c1a-0000-4000-8000-000000000011",
  "source_service": "auth_service",
  "channel": "email",
  "text_override": "Добро пожаловать! Ваш аккаунт создан.",
  "subject_override": "Регистрация завершена",
  "context": {},
  "recipient_ids": ["550e8400-e29b-41d4-a716-446655440000"],
  "occurred_at": "2026-09-15T10:05:00.000Z"
}
```

**Сообщение в `notifications.requests.v1`** (результат фан-аута первого примера, получатель `550e8400-...`):

```json
{
  "notification_id": "b3f1c2a4-9e3a-4b7a-8b1a-7e2d3f4a5b6c",
  "request_id": "5f3e2c1a-0000-4000-8000-000000000010",
  "schema_version": 1,
  "source_service": "admin_panel",
  "campaign_id": "42",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "channel": "email",
  "template_id": "7",
  "subject_override": null,
  "text_override": null,
  "context": {},
  "occurred_at": "2026-09-15T10:00:00.000Z",
  "received_at": "2026-09-15T10:00:00.120Z"
}
```

## 8. Вне scope T1 (сознательно отложено)

- **Broadcast «всем пользователям»** — контракт принимает только явный список
  `recipient_ids`. Массовая рассылка без явного списка требует источника
  списка всех `user_id` (например, bulk-endpoint в `auth_service`), который
  сегодня не существует и не входит в T1.
- **Хранение истории/статусов отправки и «мои уведомления» в личном
  кабинете** — у `notification_worker` (T3) или будущего отдельного сервиса,
  не у `notification_api`.