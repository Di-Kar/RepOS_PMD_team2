"""Заявка со ссылкой на несуществующую кампанию: воркер не должен терять
уведомление. FK notifications.campaign_id -> campaigns(id) при таком
campaign_id срабатывает на первой вставке, и воркер повторяет её с
campaign_id=NULL — письмо доходит, теряется только связь с кампанией
(см. queries.insert_content_and_notification).

Регрессия на ревью S10-R4: повторная вставка выполнялась в уже прерванной
транзакции (PostgreSQL помечает её aborted после нарушения FK), падала с
InFailedSQLTransactionError, и сообщение уходило в DLQ вместо доставки.

Как и в остальных тестах пакета, всё проверяется через notification_id,
полученный из notification_log по request_id этой заявки: register_user()
попутно шлёт настоящее приветственное письмо auth_service на тот же адрес
со своим notification_id."""

import uuid

from .conftest import make_notification_request, post_notification, wait_until


async def test_missing_campaign_is_delivered_with_null_campaign(
    session, register_user, mailhog, db_conn
):
    # Свободный id кампании: берём заведомо большой и убеждаемся, что его
    # действительно нет — иначе тест проверял бы happy path.
    missing_campaign_id = 9_000_000_000 + uuid.uuid4().int % 1_000_000
    exists = await db_conn.fetchval(
        "SELECT 1 FROM campaigns WHERE id = $1", missing_campaign_id
    )
    assert exists is None, f"campaign id {missing_campaign_id} unexpectedly exists"

    user = await register_user(full_name="Кампания Удалённая")
    request = make_notification_request(
        recipient_ids=[user["id"]],
        campaign_id=str(missing_campaign_id),
        subject_override="Уведомление без кампании",
        text_override="Здравствуйте! Кампания этого письма уже удалена.",
    )

    status, body = await post_notification(session, request)
    assert status == 202, body

    message = await mailhog.wait_for_message(
        user["email"], subject="Уведомление без кампании", timeout=30.0
    )
    assert message is not None, (
        "email did not arrive in MailHog: notification with a dangling campaign_id "
        "was most likely dropped into DLQ"
    )

    async def _resolve_notification_id():
        return await db_conn.fetchval(
            "SELECT notification_id FROM notification_log WHERE request_id = $1",
            request["request_id"],
        )

    notification_id = await wait_until(_resolve_notification_id, timeout=15.0)
    assert notification_id is not None, "notification_log row was never created"

    async def _check_sent():
        row = await db_conn.fetchrow(
            "SELECT status, campaign_id FROM notifications WHERE notification_id = $1",
            notification_id,
        )
        return row if row and row["status"] == "sent" else None

    row = await wait_until(_check_sent, timeout=15.0)
    assert row is not None, "notifications.status never reached 'sent'"
    assert row["campaign_id"] is None, (
        "dangling campaign_id must be stored as NULL, got "
        f"{row['campaign_id']}"
    )

    # Уведомление не должно попасть в DLQ ни как постоянная ошибка, ни как
    # исчерпавшее ретраи.
    dlq_count = await db_conn.fetchval(
        "SELECT count(*) FROM notification_worker_dlq WHERE notification_id = $1",
        notification_id,
    )
    assert dlq_count == 0, f"notification landed in DLQ {dlq_count} time(s)"
