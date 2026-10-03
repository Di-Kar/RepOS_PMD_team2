"""Юнит-тесты для src/models/schemas.py (user_profiles) — без БД/HTTP.

Файл грузится через importlib по прямому пути, а не через sys.path +
`from src.models.schemas import ...`: в общем прогоне `pytest /tests` имена
"src" и "models" уже заняты пакетами других сервисов, примонтированных в тот
же контейнер (tests/notification_worker/test_consumer_dlq_unavailable.py
кладёт в sys.modules "src" из notification_worker, ugc_service/src тоже
содержит пакет "models") — обычный import получил бы в sys.modules чужой
закэшированный пакет вместо user_profiles и упал бы на
`ModuleNotFoundError: No module named 'src.models'`. schemas.py не имеет
внутренних `from src...`-импортов (только re/uuid/datetime/pydantic),
поэтому безопасно грузится изолированно, под собственным именем модуля."""

import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

# Путь к файлу — по нескольким кандидатам (docker-путь vs локальный запуск
# от корня репо через .venv), по аналогии с tests/ugc_service/conftest.py.
_docker_path = Path('/user_profiles/src/models/schemas.py')
if _docker_path.is_file():
    _SCHEMAS_PATH = _docker_path
else:
    _SCHEMAS_PATH = (
        Path(__file__).parent.parent.parent
        / 'user_profiles' / 'src' / 'models' / 'schemas.py'
    )

_spec = importlib.util.spec_from_file_location(
    'user_profiles_schemas_under_test', _SCHEMAS_PATH
)
_schemas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_schemas)

ProfileCreateRequest = _schemas.ProfileCreateRequest
ProfileUpdateRequest = _schemas.ProfileUpdateRequest
ProfileResponse = _schemas.ProfileResponse


def make_payload(**overrides) -> dict:
    payload = {"first_name": "Иван", "last_name": "Иванов", "phone": "+79991234567"}
    payload.update(overrides)
    return payload


class TestProfileCreateRequest:
    def test_valid_e164_phone_accepted(self):
        request = ProfileCreateRequest(**make_payload(phone="+79991234567"))
        assert request.phone == "+79991234567"

    def test_phone_without_plus_rejected(self):
        with pytest.raises(ValidationError):
            ProfileCreateRequest(**make_payload(phone="79991234567"))

    def test_phone_with_leading_zero_after_plus_rejected(self):
        with pytest.raises(ValidationError):
            ProfileCreateRequest(**make_payload(phone="+09991234567"))

    def test_phone_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ProfileCreateRequest(**make_payload(phone="+" + "1" * 16))

    def test_missing_first_name_rejected(self):
        payload = make_payload()
        del payload["first_name"]
        with pytest.raises(ValidationError):
            ProfileCreateRequest(**payload)

    def test_missing_last_name_rejected(self):
        payload = make_payload()
        del payload["last_name"]
        with pytest.raises(ValidationError):
            ProfileCreateRequest(**payload)

    def test_missing_phone_rejected(self):
        payload = make_payload()
        del payload["phone"]
        with pytest.raises(ValidationError):
            ProfileCreateRequest(**payload)


class TestProfileUpdateRequest:
    def test_same_validation_as_create(self):
        request = ProfileUpdateRequest(**make_payload())
        assert request.phone == "+79991234567"

        with pytest.raises(ValidationError):
            ProfileUpdateRequest(**make_payload(phone="not-a-phone"))


class TestProfileResponse:
    def test_from_orm_like_object(self):
        class _FakeProfile:
            user_id = uuid.uuid4()
            first_name = "Иван"
            last_name = "Иванов"
            phone = "+79991234567"
            created_at = datetime.now(timezone.utc)
            updated_at = datetime.now(timezone.utc)

        response = ProfileResponse.model_validate(_FakeProfile())
        assert response.first_name == "Иван"
        assert response.phone == "+79991234567"
