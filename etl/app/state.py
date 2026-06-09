"""Хранилище состояния ETL-процесса."""
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class StateStorage:
    def __init__(self, state_dir: str = "state", filename: str = "state.json"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(exist_ok=True)
        self.state_path = self.state_dir / filename
        self._state: dict = self._load()

    def _load(self) -> dict:
        """Загружает состояние. Ожидает плоский dict {table: id}."""
        if not self.state_path.exists():
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Если файл повреждён или имеет неверный тип, начинаем с чистого листа
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"⚠️ Ошибка загрузки состояния: {e}. Начинаю с чистого листа.")
            return {}

    def _save(self) -> None:
        """Атомарная запись через временный файл + os.replace."""
        dir_path = self.state_path.parent
        tmp_fd, tmp_path = None, None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix='.tmp', prefix='state_')
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as tmp:
                json.dump(self._state, tmp, indent=2, ensure_ascii=False)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, self.state_path)
            tmp_path = None
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения состояния: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def get_cursor(self, table: str) -> Optional[str]:
        """Возвращает строку ID или None. Старые форматы игнорируются."""
        val = self._state.get(table)
        return val if isinstance(val, str) else None

    def update_cursor(self, table: str, last_id: str) -> None:
        """Сохраняет только строку ID."""
        self._state[table] = str(last_id)
        self._save()
        logger.debug(f"📍 Курсор {table} обновлён: {last_id}")

    def clear(self) -> None:
        """Удаляет файл и сбрасывает кеш."""
        if self.state_path.exists():
            self.state_path.unlink()
        self._state = {}
        logger.info("🗑️ Файл состояния очищен.")
