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
