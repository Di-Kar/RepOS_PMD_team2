# Контракт событий пользователя

Формат событий, которые клиентский SDK отправляет через API в
Kafka, откуда их читает ETL в ClickHouse. 

Требования — `docs/README.md`.

## 1. Топики Kafka

| Топик | События | Ключ |
|---|---|---|
| `analytics.clicks.v1` | клики (FR-1…FR-3) | `session_id` |
| `analytics.pageviews.v1` | просмотры страниц (FR-5…FR-10) | `session_id` |
| `analytics.custom_events.v1` | кастомные события, см. `custom_event_type` (FR-11…FR-20) | `session_id` |

Ключ = `session_id` → события одной сессии попадают в одну партицию и не
теряют порядок (NFR-16). Кастомные события собраны в один топик с
дискриминатором вместо топика на каждый тип — так новый тип события
добавляется без новой инфраструктуры (FR-30).

## 2. Общие поля сообщения

Ключ сообщения (`session_id`) и поля JSON в `value` одинаковые для всех трёх топиков независимо от типа события:

| Поле | Тип | Зачем |
|---|---|---|
| `event_id` | UUID | уникальность, дедуп (FR-23, FR-28) |
| `event_type` | string | `click` / `page_view_start` / `page_view_end` / `custom_event` |
| `schema_version` | int | версионирование схемы (NFR-25) |
| `occurred_at` | timestamp | когда событие произошло на клиенте (FR-24) |
| `received_at` | timestamp | когда принято API — для late-arrival (NFR-17) |
| `user_id` \| `anonymous_id` | string | один из двух обязателен (FR-25) |
| `session_id` | UUID | привязка к сессии (FR-26) |
| `sequence_number` | int | порядок событий внутри сессии (NFR-16) |
| `consent` | bool | согласие на сбор (FR-33, NFR-23) |
| `context` | object | страница, устройство, браузер, версия приложения |
| `source` | string | `web` / `mobile` и т.п. |
| `payload` | object | поля, специфичные для типа события (раздел 3) |

## 3. Payload по типам событий

**click** (FR-1…FR-3): `element_id`, `element_type`, `zone`, атрибуты
элемента (`attrs: object`).

**page_view_start / page_view_end** (FR-5…FR-10): `page_view_id` (общий у
пары start/end), `page_type`, `page_id`. `page_view_end` дополнительно несёт
`duration_ms` и `tab_active` — событие разбито на два, чтобы длительность
считалась в момент закрытия/потери фокуса, а не оценивалась на старте. Смена
страницы, в т.ч. SPA-навигация без перезагрузки (FR-9), — всегда новая пара
start/end со своим `page_view_id`.

**custom_event**, поле-дискриминатор `custom_event_type`:
- `quality_change` (FR-11…FR-13): `content_id`, `watch_session_id`, `from_quality`, `to_quality`
- `watch_complete` (FR-14…FR-16): `content_id`, `progress_percent`
- `search_filter` (FR-17…FR-20): `filter_type`, `filter_value`, `search_session_id` (опц.), `result_count` (опц.)

## 4. Примеры JSON

**`analytics.clicks.v1`** — `click`:

```json
{
  "event_id": "b3f1c2a4-9e3a-4b7a-8b1a-7e2d3f4a5b6c",
  "event_type": "click",
  "schema_version": 1,
  "occurred_at": "2026-08-09T12:34:56.789Z",
  "received_at": "2026-08-09T12:34:56.912Z",
  "user_id": "user-482910",
  "session_id": "8f6a1e2b-4c3d-4a2b-9f1e-2b3c4d5e6f7a",
  "sequence_number": 14,
  "consent": true,
  "context": {
    "page_type": "movie_card",
    "page_id": "tt0111161",
    "device": "desktop",
    "app_version": "3.4.1"
  },
  "source": "web",
  "payload": {
    "element_id": "play-button",
    "element_type": "button",
    "zone": "hero",
    "attrs": {
      "content_id": "tt0111161"
    }
  }
}
```

**`analytics.pageviews.v1`** — пара `page_view_start` / `page_view_end`:

```json
{
  "event_id": "1a2b3c4d-0000-4000-8000-000000000001",
  "event_type": "page_view_start",
  "schema_version": 1,
  "occurred_at": "2026-08-09T12:30:00.000Z",
  "received_at": "2026-08-09T12:30:00.050Z",
  "anonymous_id": "anon-7f3e9c1d",
  "session_id": "8f6a1e2b-4c3d-4a2b-9f1e-2b3c4d5e6f7a",
  "sequence_number": 1,
  "consent": true,
  "context": {
    "device": "mobile",
    "browser": "Safari/17"
  },
  "source": "web",
  "payload": {
    "page_view_id": "pv-556677",
    "page_type": "search",
    "page_id": null
  }
}
```

```json
{
  "event_id": "2b3c4d5e-0000-4000-8000-000000000002",
  "event_type": "page_view_end",
  "schema_version": 1,
  "occurred_at": "2026-08-09T12:31:42.000Z",
  "received_at": "2026-08-09T12:31:42.070Z",
  "anonymous_id": "anon-7f3e9c1d",
  "session_id": "8f6a1e2b-4c3d-4a2b-9f1e-2b3c4d5e6f7a",
  "sequence_number": 2,
  "consent": true,
  "context": {
    "device": "mobile",
    "browser": "Safari/17"
  },
  "source": "web",
  "payload": {
    "page_view_id": "pv-556677",
    "page_type": "search",
    "page_id": null,
    "duration_ms": 102000,
    "tab_active": true
  }
}
```

**`analytics.custom_events.v1`** — `custom_event` с дискриминатором `custom_event_type` (здесь `quality_change`):

```json
{
  "event_id": "3c4d5e6f-0000-4000-8000-000000000003",
  "event_type": "custom_event",
  "schema_version": 1,
  "occurred_at": "2026-08-09T13:05:11.300Z",
  "received_at": "2026-08-09T13:05:11.410Z",
  "user_id": "user-482910",
  "session_id": "8f6a1e2b-4c3d-4a2b-9f1e-2b3c4d5e6f7a",
  "sequence_number": 27,
  "consent": true,
  "context": {
    "page_type": "watch",
    "page_id": "tt0111161"
  },
  "source": "web",
  "payload": {
    "custom_event_type": "quality_change",
    "content_id": "tt0111161",
    "watch_session_id": "ws-334455",
    "from_quality": "720p",
    "to_quality": "1080p"
  }
}
```
