import os

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTHENTICATION_BACKENDS = [
    'config.auth_backends.AuthServiceBackend',
    'django.contrib.auth.backends.ModelBackend',
]

AUTH_SERVICE_URL = 'http://auth_service:8000/api/v1/auth'
AUTH_SERVICE_TIMEOUT = float(os.getenv('AUTH_SERVICE_TIMEOUT', '3'))
# Роль (из IdM auth_service), дающая доступ к Django admin.
AUTH_SERVICE_ADMIN_ROLE = os.getenv('AUTH_SERVICE_ADMIN_ROLE', 'admin')
# Порог/окно простого in-process circuit breaker (см. config/circuit_breaker.py).
AUTH_SERVICE_BREAKER_FAILURE_THRESHOLD = int(os.getenv('AUTH_SERVICE_BREAKER_FAILURE_THRESHOLD', '3'))
AUTH_SERVICE_BREAKER_RESET_TIMEOUT = float(os.getenv('AUTH_SERVICE_BREAKER_RESET_TIMEOUT', '30'))
