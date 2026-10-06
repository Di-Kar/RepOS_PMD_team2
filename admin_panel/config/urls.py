"""config URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest
from django.urls import include, path
from movies.search import SearchView
from profiles_proxy.views import profiles_list

urlpatterns = [
    # До admin.site.urls: тот же префикс /admin/, но свой view с проверкой права
    path('admin/profiles/', admin.site.admin_view(profiles_list), name='profiles_list'),
    path('admin/', admin.site.urls),
    path('api/', include('movies.api.urls')),
    path('search/', SearchView.as_view(), name='search'),
]

if settings.DEBUG:

    def sentry_debug(request: HttpRequest):
        raise ZeroDivisionError

    urlpatterns += [path('api/v1/_sentry_debug/', sentry_debug)]
