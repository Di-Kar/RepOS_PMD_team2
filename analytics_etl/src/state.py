"""Управление состоянием на основе JSON-файлов для отслеживания смещений Kafka.

Сохраняет зафиксированные смещения для каждой темы-раздела, чтобы ETL мог
возобновить работу с последней позиции после перезапуска.
"""

import json
import logging
import os
import tempfile
from typing import Any, Dict

logger = logging.getLogger(__name__)


class OffsetStorage:
    """Файловое хранилище для смещений потребителя Kafka и состояния ETL.

    Каждое состояние сохраняется как JSON-файл в ``state_dir``.
    Записи выполняются атомарно (запись во временный файл, затем os.replace).
    """

    def __init__(self, state_dir: str, filename: str = 'kafka_offsets.json'):
        self.state_dir = state_dir
        self.file_path = os.path.join(state_dir, filename)
        os.makedirs(state_dir, exist_ok=True)

    def save_state(self, state: Dict[str, Any]) -> None:
        """Атомарно сохранить состояние на диск.

        Запись выполняется во временный файл, затем используется ``os.replace`` для
        атомарности. Сохраняет резервную копию, если текущий файл повреждён.
        """
        try:
            dir_name = os.path.dirname(os.path.abspath(self.file_path))
            with tempfile.NamedTemporaryFile(
                mode='w', dir=dir_name, suffix='.tmp', delete=False, encoding='utf-8'
            ) as tmp:
                json.dump(state, tmp, indent=2, default=str)
                tmp_path = tmp.name
            os.replace(tmp_path, self.file_path)
            logger.debug('Состояние сохранено в %s', self.file_path)
        except Exception as e:
            logger.error('Не удалось сохранить состояние: %s', e)
            # Очистить временный файл, если он существует
            if 'tmp_path' in locals():
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def load_state(self) -> Dict[str, Any]:
        """Загрузить состояние с диска.

        Возвращает пустой словарь, если файл не существует или повреждён.
        """
        if not os.path.exists(self.file_path):
            logger.info(
                'Файл состояния не найден в %s, начинаю с чистого листа', self.file_path
            )
            return {}

        try:
            with open(self.file_path, encoding='utf-8') as f:
                data = json.load(f)
            logger.debug('Состояние загружено из %s', self.file_path)
            return data
        except (json.JSONDecodeError, OSError) as e:
            backup_path = self.file_path + '.bak'
            logger.error(
                'Файл состояния повреждён (%s) — начинаю заново. '
                'Резервная копия сохранена в %s',
                e,
                backup_path,
            )
            try:
                os.replace(self.file_path, backup_path)
            except OSError as replace_err:
                logger.error('Не удалось сохранить резервную копию: %s', replace_err)
            return {}

    def save_offsets(self, offsets: Dict[str, Dict[int, int]]) -> None:
        """Сохранить смещения потребителя Kafka.

        Формат: {topic: {partition: offset}}
        """
        state = self.load_state()
        state['kafka_offsets'] = offsets
        self.save_state(state)

    def load_offsets(self) -> Dict[str, Dict[int, int]]:
        """Загрузить смещения потребителя Kafka."""
        state = self.load_state()
        return state.get('kafka_offsets', {})

    def save_etl_state(self, key: str, value: Any) -> None:
        """Сохранить произвольное значение состояния ETL."""
        state = self.load_state()
        state['etl_state'] = state.get('etl_state', {})
        state['etl_state'][key] = value
        self.save_state(state)

    def load_etl_state(self) -> Dict[str, Any]:
        """Загрузить все значения состояния ETL."""
        state = self.load_state()
        return state.get('etl_state', {})
