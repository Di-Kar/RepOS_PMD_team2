"""Заявка с template_id: воркер должен сам прочитать шаблон из
message_templates (notification_admin_panel, та же notifications_db),
подставить имя пользователя, полученное из auth_service, и переменные из
context заявки — единая шаблонизация и для автоматических уведомлений, и
для рассылок менеджера (шаблон один и тот же для обоих путей)."""

from .conftest import make_notification_request, post_notification, wait_until


async def test_template_is_rendered_with_user_name_and_context(
    session, register_user, mailhog, db_conn
):
    template_id = await db_conn.fetchval(
        """
        INSERT INTO message_templates
            (name, channel, subject, body, available_variables, is_active, created_at, updated_at)
        VALUES ($1, 'email', $2, $3, '["user.name", "movie_title"]'::jsonb, true, now(), now())
        RETURNING id
        """,
        "worker-e2e-template",
        "Новая серия: {{ movie_title }}",
        "Привет, {{ user.name }}! Вышла новая серия «{{ movie_title }}».",
    )
    try:
        user = await register_user(full_name="Рендер Тестов")
        request = make_notification_request(
            recipient_ids=[user["id"]],
            template_id=str(template_id),
            subject_override=None,
            text_override=None,
            context={"movie_title": "Тестовый сериал"},
        )

        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "accepted", body

        # subject= обязателен, см. комментарий в test_email_delivery_smoke.py
        # про приветственное письмо auth_service на тот же адрес.
        message = await mailhog.wait_for_message(
            user["email"], subject="Новая серия: Тестовый сериал", timeout=30.0
        )
        assert message is not None, "email did not arrive in MailHog within timeout"
        rendered_body = mailhog.body(message)
        assert "Рендер Тестов" in rendered_body
        assert "Тестовый сериал" in rendered_body

        # По notification_id из notification_log (уникален для этой заявки),
        # а не по user_id — иначе выборка могла бы задеть контент
        # приветственного письма auth_service тому же пользователю.
        async def _resolve_notification_id():
            return await db_conn.fetchval(
                "SELECT notification_id FROM notification_log WHERE request_id = $1",
                request["request_id"],
            )

        notification_id = await wait_until(_resolve_notification_id, timeout=15.0)
        assert notification_id is not None, "notification_log row was never created"

        content_row = await db_conn.fetchrow(
            "SELECT rendered_subject, rendered_body FROM notification_contents nc "
            "JOIN notifications n ON n.content_id = nc.content_id "
            "WHERE n.notification_id = $1",
            notification_id,
        )
        assert content_row is not None
        assert "Рендер Тестов" in content_row["rendered_body"]
    finally:
        # Django's on_delete=SET_NULL — чисто ORM-логика (Python), а не
        # настоящий "ON DELETE SET NULL" на самом constraint'е в БД: сырой
        # DELETE без предварительного обнуления template_id у уже созданных
        # notification_contents упал бы FK-нарушением.
        await db_conn.execute(
            "UPDATE notification_contents SET template_id = NULL WHERE template_id = $1",
            template_id,
        )
        await db_conn.execute(
            "DELETE FROM message_templates WHERE id = $1", template_id
        )
