from django.db import models


class ProfileAccess(models.Model):
    """Право на просмотр профилей пользователей.

    Таблицы нет (managed=False): модель нужна только ради Permission, по
    которому ModelBackend и admin решают, показывать ли раздел профилей.
    Сами профили живут в user_profiles и читаются по HTTP (см. views.py).
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [("view_profile", "Can view user profiles")]


class AuditAccess(models.Model):
    """Право на просмотр журнала аудита просмотра профилей (issue #117).

    Отдельная модель-пустышка (по образцу ProfileAccess) — просмотр самих
    профилей и просмотр журнала их просмотра это независимые права: роль
    audit не даёт доступа к profiles_list, а profiles_viewer — к audit_list.
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [("view_audit", "Can view profile view audit log")]
