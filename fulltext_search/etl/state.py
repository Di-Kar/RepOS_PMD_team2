import json
import logging
import os
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)


class JsonFileStorage:
    def __init__(self, file_path: str):
        self.file_path = file_path

    def save_state(self, state: dict) -> None:
        """Атомарная запись: пишем во временный файл, затем os.replace."""
        dir_name = os.path.dirname(os.path.abspath(self.file_path))
        with tempfile.NamedTemporaryFile(
            mode='w', dir=dir_name, suffix='.tmp', delete=False, encoding='utf-8'
        ) as tmp:
            json.dump(state, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, self.file_path)

    def retrieve_state(self) -> dict:
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            backup_path = self.file_path + '.bak'
            logger.error(
                'Файл состояния повреждён (%s) — начинаем переиндексацию заново. '
                'Резервная копия сохранена: %s',
                e, backup_path,
            )
            try:
                os.replace(self.file_path, backup_path)
            except OSError as replace_err:
                logger.error('Не удалось сохранить резервную копию: %s', replace_err)
            return {}


class State:
    def __init__(self, storage: JsonFileStorage):
        self.storage = storage
        self._state = storage.retrieve_state()

    def set_state(self, key: str, value: Any) -> None:
        self._state[key] = value
        self.storage.save_state(self._state)

    def get_state(self, key: str) -> Optional[Any]:
        return self._state.get(key)
