"""Мониторинг использования памяти для процесса ETL.

Отслеживает RSS / VMS память и публикует предупреждения/критические сообщения при
превышении порогов.  При высокой памяти автоматически запускает сборку мусора.
"""

import gc
import logging
import resource
import sys
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MemoryMonitor:
    """Мониторинг использования памяти текущего процесса."""

    def __init__(self, warn_mb: int = 500, critical_mb: int = 800):
        self.warn_mb = warn_mb
        self.critical_mb = critical_mb

    def track_memory(self) -> Dict[str, Any]:
        """Вернуть метрики использования памяти.

        Возвращает словарь с ``rss_mb``, ``vms_mb``, ``percent``.
        """
        # На Linux использовать модуль resource
        if hasattr(resource, 'getrlimit'):
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # ru_maxrss в КБ на Linux, в МБ на macOS
            if sys.platform == 'darwin':
                rss_mb = usage.ru_maxrss  # Уже в КБ на macOS, конвертирую
                rss_mb = rss_mb / 1024.0
            else:
                rss_mb = usage.ru_maxrss / 1024.0  # КБ → МБ
        else:
            rss_mb = 0.0

        # Попробовать /proc/self/status в качестве резервного варианта
        try:
            with open('/proc/self/status') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        rss_mb = int(line.split()[1]) / 1024.0
                        break
        except (FileNotFoundError, OSError, ValueError):
            pass

        return {
            'rss_mb': round(rss_mb, 2),
            'vms_mb': 0,
            'percent': 0,
        }

    def check_thresholds(self) -> str:
        """Проверить память относительно настроенных порогов.

        Возвращает одно из: ``'ok'``, ``'warning'``, ``'critical'``.
        Публикует соответствующие сообщения.
        """
        metrics = self.track_memory()
        rss = metrics['rss_mb']

        if rss >= self.critical_mb:
            logger.critical(
                'КРИТИЧЕСКИ: RSS-память %.0f МБ превышает порог %d МБ',
                rss, self.critical_mb,
            )
            return 'critical'
        elif rss >= self.warn_mb:
            logger.warning(
                'ВНИМАНИЕ: RSS-память %.0f МБ превышает порог %d МБ',
                rss, self.warn_mb,
            )
            return 'warning'
        return 'ok'

    def auto_gc(self) -> int:
        """Запустить сборку мусора, если память высокая.

        Возвращает количество собранных объектов.
        """
        metrics = self.track_memory()
        if metrics['rss_mb'] >= self.warn_mb:
            logger.info('Запускаю авто-сборку мусора (память %.0f МБ)', metrics['rss_mb'])
            collected = gc.collect()
            logger.info('Авто-сборка собрала %d объектов', collected)
            return collected
        return 0
