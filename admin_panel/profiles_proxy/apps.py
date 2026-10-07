from django.apps import AppConfig
from django.contrib import admin


class ProfilesProxyConfig(AppConfig):
    name = 'profiles_proxy'
    verbose_name = 'Профили пользователей'

    def ready(self):
        # Ссылка на раздел профилей в индексе /admin/, видна только при праве view_profile
        admin.site.index_template = 'profiles_proxy/admin_index.html'
