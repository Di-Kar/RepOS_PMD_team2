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
  письма/push/sms и не ведёт историю статусов доставки — только приём и
  постановка в очередь (issue #94: «Сам API не занимается рассылкой — это
  центральный узел»). Своя БД (см. §9) хранит только факт и результат
  публикации в Kafka — это лог отправки, а не история доставки.
- **notification_worker** (#96, реализовано — см. §11): читает
  `notifications.requests.v1`, для персонализации сам ходит в `auth_service`
  за именем/email по `user_id` (к воркеру эти данные не приходят — только
  `user_id`), рендерит шаблон, отправляет. Детальную историю попыток
  доставки ведёт у себя (Django-таблицы `notification_admin_panel`,
  прямым SQL); финальный статус по каждому уведомлению обновляет также в
  `notification_log` БД `notification_api` по ключу `notification_id` — см.
  §9. Пока реализована доставка только канала `email` — телефон для
  sms/push в модели `auth_service.User` также пока отсутствует.
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
  `notification_admin_panel`. `websocket` (S10_T4, issue #97) доставляется
  самим `notification_api` — единственный канал, для которого API не только
  принимает и публикует заявку, но и сам её доставляет: у остальных каналов
  это работа `notification_worker` (S10_T3, которого ещё нет), а websocket
  — стейтфул по своей природе (соединение с конкретным получателем нужно
  держать открытым в процессе, который его принял), так что делегировать
  доставку отдельному consumer-сервису без pub/sub между инстансами
  бессмысленно. Подробности — §10.

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

`notification_api` не делает собственный дедуп заявок при публикации —
`notification_log` (§9) пишется уже post-factum, после попытки публикации в
Kafka, и не проверяется перед ней. Вместо дедупа по БД `notification_id`
выводится детерминированно: `uuid5(NOTIFICATIONS_NAMESPACE,
f"{request_id}:{user_id}")`.

Повторная отправка того же HTTP-запроса с тем же `request_id` (ретрай клиента,
NFR-29-аналог из `docs/README.md`) даёт при фан-ауте те же самые
`notification_id`, что и в первый раз — при повторной публикации перезапишет
(`INSERT ... ON CONFLICT`, см. §9) ту же строку `notification_log`. Дедуп по
факту доставки происходит на стороне `notification_worker`, когда он
сохраняет свою историю (уникальный `notification_id`).

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

**HTTP-заявка в свободном формате** (без шаблона; так реально вызывает
`auth_service` при регистрации/смене пароля, S10_T7 — см.
`auth_service/src/services/notification_client.py`):

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

## 9. Лог заявок в БД `notification_api` (таблица `notification_log`)

У `notification_api` появилась собственная Postgres-БД (отдельная от
`auth_service` и остальных сервисов). Она хранит **лог факта и результата
публикации в Kafka** — не историю доставки (это по-прежнему зона
`notification_worker`, §0).

Одна строка на `notification_id`, т.е. на получателя **после** фан-аута (не на
HTTP-заявку) — тот же ключ, что и в сообщении Kafka (§4). `notification_api`
пишет строку сразу после попытки публикации, синхронно в рамках обработки
HTTP-запроса, но best-effort: сбой записи в БД не влияет на HTTP-ответ и не
откатывает публикацию — источник истины по факту отправки остаётся Kafka.

| Поле | Тип | Кто пишет | Описание |
|---|---|---|---|
| `notification_id` | UUID, PK | `notification_api` | см. §6 |
| `request_id` | UUID, indexed | `notification_api` | |
| `schema_version` | int | `notification_api` | |
| `source_service` | string | `notification_api` | |
| `campaign_id` | string, nullable | `notification_api` | |
| `user_id` | UUID, indexed | `notification_api` | |
| `channel` | string | `notification_api` | |
| `template_id` | string, nullable | `notification_api` | |
| `subject_override` | text, nullable | `notification_api` | |
| `text_override` | text, nullable | `notification_api` | |
| `context` | JSONB | `notification_api` | |
| `occurred_at` | timestamptz | `notification_api` | |
| `received_at` | timestamptz | `notification_api` | момент публикации |
| `status` | string, indexed | `notification_api` **и** `notification_worker` | см. ниже |
| `status_updated_at` | timestamptz | БД (auto, триггер) | обновляется любым `UPDATE` строки — в т.ч. от `notification_worker`, независимо от того, каким клиентом/ORM он выполнен |
| `created_at` | timestamptz | БД (auto) | |

### Статусы

`status` — обычная строка, не Postgres ENUM: набор значений расширяется
`notification_worker` без миграции на стороне `notification_api`.

Для `email`/`sms`/`push` `notification_api` проставляет один из двух
статусов сразу после попытки публикации в Kafka:

- `kafka_published` — сообщение успешно ушло в топик.
- `kafka_publish_failed` — публикация не удалась (соответствует
  `rejected_recipients[].reason == "kafka_publish_failed"` в HTTP-ответе, §2);
  сообщение в Kafka не появится, `notification_worker` его не увидит.

Дальше `notification_worker` **обновляет ту же строку** по
`notification_id` (`UPDATE notification_log SET status = ... WHERE
notification_id = :id`), когда обрабатывает сообщение из Kafka. Ретрай
HTTP-заявки с тем же `request_id` даёт тот же `notification_id` (§6) и
обновит строку через `INSERT ... ON CONFLICT DO UPDATE`, но `notification_api`
**не перезаписывает `status`, если он уже не своим** (см. ниже) — то есть
после того как воркер хоть раз обновил статус, повторная публикация той же
заявки его не затирает.

Реализованный (S10_T3) набор статусов `notification_worker` (email-канал —
единственный, для которого сейчас есть доставка, см. §11):

- `queued_for_send` — рендер-стадия успешно прочитала профиль и шаблон,
  опубликовала готовое сообщение в `notifications.ready.v1`.
- `render_failed` — постоянная ошибка на рендер-стадии (пользователь не
  найден в `auth_service`, шаблон не найден/неактивен) — подробности в
  `notification_worker_dlq` (§11).
- `skipped` — пользователь неактивен (`is_active=false`) либо канал ещё не
  реализован (сейчас — не `email`); осознанное решение не отправлять, не
  ошибка.
- `sent` — письмо успешно передано SMTP.
- `failed` — постоянная ошибка отправки (невалидный email, провайдер
  отклонил с постоянной ошибкой).
- `requires_manual_review` — send-стадия обнаружила статус
  `notifications.status='sending'` под чужим `attempt_id` (см. §11) — не
  ретраится автоматически, чтобы не продублировать письмо; статус самой
  `notifications` строки при этом остаётся `sending`, разбирается вручную.

Для `websocket` (S10_T4, §10) статус проставляется вместо этого сразу по
факту синхронной доставки — Kafka не участвует, воркер тоже:

- `websocket_delivered` — на момент запроса было открытое соединение,
  сообщение отправлено.
- `websocket_no_connection` — получатель не подключён (best-effort, §8).
- `websocket_text_required` — заявка без `text_override` (`template_id`
  без рендера не поддержан), соответствует
  `rejected_recipients[].reason == "websocket_requires_text_override"`.

Для `websocket` понятия «наш статус vs. статус воркера» нет — воркера,
который мог бы обновить строку поверх, для этого канала не существует, так
что `notification_api` перезаписывает статус при каждом ретрае.

## 10. Доставка канала `websocket` (S10_T4, issue #97)

В отличие от `email`/`sms`/`push` (доставка — зона `notification_worker`,
T3), канал `websocket` доставляет сам `notification_api`: HTTP-приём заявки
и её доставка живут в одном процессе, потому что держать открытое
соединение с конкретным получателем и одновременно читать очередь можно
только там, где это соединение принято.

### Подключение клиента

`GET /api/v1/notifications/ws?token=<access_token>` — upgrade до
websocket. Токен передаётся query-параметром, а не заголовком: в браузерном
`WebSocket` API нельзя выставить произвольный заголовок при подключении.

Авторизация — как у остальных клиентов auth_service в проекте (ugc_service,
async_api): `token` проверяется вызовом `GET /profile` в `auth_service`, JWT
локально не расшифровывается. В отличие от них — фейлимся закрыто: без
валидного токена соединение не принимается (`close(code=4401)` до
`accept()`), анонимного или чужого вебсокета быть не должно (это прямое
требование issue #97).

Соединение — только сервер → клиент; входящие от клиента данные игнорируются
(`receive` используется лишь чтобы поймать разрыв). Один пользователь может
держать несколько открытых соединений (вкладки/устройства) — доставка идёт
во все.

### Механизм доставки

В отличие от `email`/`sms`/`push`, заявка с `channel="websocket"` **не
публикуется в Kafka** — доставляется синхронно, в рамках того же
HTTP-запроса, что её принял: `notification_api` сам держит открытые
соединения, и класть сообщение в очередь, которую тут же читает тот же
самый процесс, не даёт ничего, кроме задержки (а на масштабирование это
всё равно не работает — см. «Один инстанс» ниже, проблема «какая реплика
держит нужное соединение» не решается ни очередью, ни прямой доставкой без
pub/sub поверх). Ищется открытое соединение по `user_id` (реестр в памяти
процесса) и пушится JSON `{notification_id, request_id, source_service,
subject, text, context, occurred_at}`.

**Best-effort, без бэклога** — та же логика, что и во всём контракте (§8):
если получатель не подключён в момент запроса, сообщение теряется (HTTP
всё равно `accepted` — «доставлено» этот статус не гарантирует ни для
одного канала); истории/переспроса при переподключении нет.

**MVP-ограничение: только `text_override`.** Заявки с `template_id` без
`text_override` — рендеринг шаблонов остаётся работой `notification_worker`,
а `MessageTemplate` (таблица `notification_admin_panel`, Django) — не то, во
что `notification_api` должен лезть напрямую. В отличие от остальных
ограничений — эта проверка синхронная: получатель уходит в
`rejected_recipients` HTTP-ответа с `reason: "websocket_requires_text_override"`,
а не просто в лог.

## 11. `notification_worker` (S10_T3, issue #96) — реализовано

Два процесса из каталога `notification_worker/` (общий Docker-образ, разный
`command`): `notification_worker_render` (consumer group
`notification_worker_render`) и `notification_worker_email_sender` (consumer
group `notification_worker_email_sender`). Схема сообщений (`shared/
notification_schemas.py`) общая с `notification_api`.

**Промежуточный топик** `notifications.ready.v1` (3 партиции, ключ
`user_id`) — выход рендер-стадии, вход отправляющих воркеров: несёт уже
отрендеренные `subject`/`body` и email получателя, чтобы send-стадия не
обращалась к `auth_service` повторно.

**Обогащение профилем** — `GET /api/v1/auth/internal/users/{user_id}` в
`auth_service` (заголовок `X-Internal-Api-Key`, см.
`auth_service/src/api/v1/internal.py`), а не обычный `GET /profile` — у
воркера нет JWT конечного пользователя, только `user_id` из Kafka. `404` —
постоянная ошибка (пользователь не найден), `is_active=false` отдаётся как
есть — решение "не слать" принимает воркер (`skipped`, не ошибка).

**Запись результата** — воркер пишет в три места: `notification_log`
(статус, см. выше) и Django-таблицы `notification_admin_panel`
(`notification_contents`/`notifications`/`notification_history`, ранее
существовавшие без единого писателя) — прямым SQL, без Django ORM.

**Идемпотентность доставки** — перед рендером и перед фактической
отправкой воркер проверяет текущий `notifications.status`. Терминальный
статус (`sent`/`failed`/`skipped`) означает redelivery — повторная обработка
пропускается. `pending`, встреченный на рендер-стадии повторно, — особый
случай: контент уже отрендерен, но предыдущая попытка могла не успеть
опубликовать его в `notifications.ready.v1` (например обрыв Kafka producer
между DB-коммитом и публикацией) — воркер не рендерит повторно, а
публикует уже сохранённый контент (republish безопасен благодаря
идемпотентности send-стадии ниже).

Статус `sending`, встреченный на send-стадии, — особый случай: `src/
consumer.py` присваивает каждому сообщению `attempt_id` (случайный UUID),
стабильный на протяжении всех ретраев/пауз одного непрерывного вызова, но
новый при каждой "свежей" выдаче сообщения (перезапуск процесса,
переигровка offset'а). `attempt_id` записывается вместе со статусом
`sending` в `notification_history.error_message` — если он совпадает с
текущим, это точно та же, ещё не прервавшаяся серия ретраев (продолжаем);
если нет — запись оставлена другим (вероятно, упавшим) вызовом,
автоматический ретрай не выполняется (`requires_manual_review`), чтобы не
продублировать письмо. Раньше эта развилка решалась эвристикой по времени
(лиз) — она не могла надёжно отличить свежий чужой crash от своего же
живого ретрая; точное сравнение `attempt_id` не полагается на угадывание.

**`notification_worker_dlq`** (таблица в `notifications_db`, своя у
воркера, применяется скриптом `notification_worker/scripts/migrate.py`, не
Alembic/Django) — сообщения с постоянной ошибкой (пользователь/шаблон не
найден, битый JSON, невалидный/несовместимый с Jinja2 шаблон, SMTP отклонил
письмо окончательно) и случаи `requires_manual_review`. Поля:
`notification_id` (nullable — не всегда известен), `stage` (`render`/
`send`), `error_type`, `error_message`, `raw_message` (JSONB),
`attempt_count`, `created_at`.

**Предел числа циклов паузы** (`NOTIFICATION_WORKER_MAX_PAUSE_CYCLES`, по
умолчанию 5) — транзиентная ошибка, которую не решает ни один из
`retry_max_attempts`, ставит партицию на паузу и позже пробует снова
(`src/consumer.py`); без предела сообщение, ломающееся по причине, не
зависящей от количества попыток (например баг в коде, а не во внешней
зависимости), крутило бы pause/resume бесконечно и блокировало бы
партицию (а с ней всех пользователей, чьи сообщения туда попадают)
навсегда. После исчерпания предела сообщение фиксируется в
`notification_worker_dlq` (`error_type=giving_up_after_max_pause_cycles`)
и пропускается — но только если запись в DLQ действительно прошла.

**Недоступная DLQ** (`NOTIFICATION_WORKER_DLQ_UNAVAILABLE_MAX_HOLD_SECONDS`,
по умолчанию 120). Offset подтверждается только после того, как результат
или причина сбоя надёжно сохранены: успешная обработка, постоянная ошибка
(обработчик записал причину сам до того, как поднять
`PermanentProcessingError`) либо успешная запись в
`notification_worker_dlq`. Если Postgres недоступен и записать сообщение в
DLQ не удалось, offset **не** подтверждается: в лог уходит `CRITICAL` (и в
Sentry через LoggingIntegration), партиция остаётся на паузе, а попытки
(сначала обработка — Postgres мог подняться, затем снова запись в DLQ)
повторяются. Раньше ошибка записи в DLQ глушилась и сообщение всё равно
коммитилось — при длительной недоступности Postgres оно исчезало и из
доставки, и из DLQ (ревью S10_R4).

Удержание ограничено по времени, потому что пауза не бесплатна: aiokafka
выводит консьюмера из группы, если фетчей не было дольше
`max_poll_interval_ms` (по умолчанию 300 с), а на паузе фетчей нет — при
назначении одной партиции на реплику бесконечное удержание само привело бы
к тому, что партиция перестала бы читаться группой, а последующий commit
упал бы с `CommitFailedError`. Поэтому по истечении
`DLQ_UNAVAILABLE_MAX_HOLD_SECONDS` (значение должно оставаться заметно
меньше `max_poll_interval_ms`) consumer-loop поднимает
`DlqUnavailableError`, процесс завершается с ненулевым кодом и
перезапускается docker'ом (`restart: unless-stopped`), продолжая с
неподтверждённого offset'а — сообщение не теряется. Чтобы этот бюджет был
достижим, у пула Postgres задан таймаут соединения и запроса
(`NOTIFICATION_WORKER_POSTGRES_COMMAND_TIMEOUT_SECONDS`, по умолчанию 10):
без него не отвечающая (в отличие от явно отказывающей) БД растянула бы
один цикл ретраев дольше всего бюджета.

То же правило действует и на send-стадии. `send_service` заводит на ручной
разбор случаи, которые нельзя ретраить (`smtp_ambiguous`,
`send_confirmation_persist_failed`): если сама эта запись не прошла, воркер
поднимает `DlqUnavailableError`, а не `PermanentProcessingError` —
consumer.py не подтверждает offset и роняет процесс, НЕ повторяя
обработчик: повтор с тем же `attempt_id` отправил бы второе письмо. После
рестарта `attempt_id` уже другой, поэтому `_claim_for_sending` уводит
сообщение на ручной разбор (`send_ambiguous`), а не отправляет заново.
Раньше сбой этой записи только логировался, и сообщение подтверждалось без
единого следа в DLQ.

**Ограничение MVP**: реализована доставка только канала `email`. Заявки с
`channel="sms"`/`"push"` доходят до рендер-стадии и получают статус
`skipped` (`error_type=channel_not_implemented` в логике воркера, не
записывается отдельно в DLQ — это не ошибка, а осознанный пропуск) — не
теряются молча, но и не доставляются, пока не появятся соответствующие
sender-процессы, читающие тот же `notifications.ready.v1`.

**Один инстанс.** Реестр соединений — только в памяти процесса; в текущем
`docker-compose.yml` `notification_api` не масштабируется горизонтально.
Если это понадобится — нужен будет pub/sub между репликами (например,
Redis), сейчас не реализовано.