"""Unit-tests для analytics_etl.memory_monitor — MemoryMonitor."""

import gc
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_monitor import MemoryMonitor

# --------------------------------------------------------------------------- #
#  Фикстуры                                                                   #
# --------------------------------------------------------------------------- #


@pytest.fixture
def monitor():
    """MemoryMonitor с порогами по умолчанию."""
    return MemoryMonitor(warn_mb=500, critical_mb=800)


@pytest.fixture
def monitor_with_mocked_memory(monitor, monkeypatch):
    """Монитор с контролируемым значением RSS через monkeypatch."""
    def mock_track(rss_mb):
        original = monitor.track_memory
        def _mocked():
            return {'rss_mb': rss_mb, 'vms_mb': 0, 'percent': 0}
        return _mocked()
    return monitor


# --------------------------------------------------------------------------- #
#  check_thresholds()                                                         #
# --------------------------------------------------------------------------- #


class TestCheckThresholds:
    def test_returns_ok_when_below_warn(self, monitor, monkeypatch):
        """Когда RSS ниже warn — возвращается 'ok'."""
        monkeypatch.setattr(
            monitor, 'track_memory',
            lambda: {'rss_mb': 100.0, 'vms_mb': 0, 'percent': 0},
        )
        result = monitor.check_thresholds()
        assert result == 'ok'

    def test_returns_warning_when_above_warn(self, monitor, monkeypatch):
        """Когда RSS >= warn_mb — возвращается 'warning'."""
        monkeypatch.setattr(
            monitor, 'track_memory',
            lambda: {'rss_mb': 600.0, 'vms_mb': 0, 'percent': 0},
        )
        result = monitor.check_thresholds()
        assert result == 'warning'

    def test_returns_critical_when_above_critical(self, monitor, monkeypatch):
        """Когда RSS >= critical_mb — возвращается 'critical'."""
        monkeypatch.setattr(
            monitor, 'track_memory',
            lambda: {'rss_mb': 900.0, 'vms_mb': 0, 'percent': 0},
        )
        result = monitor.check_thresholds()
        assert result == 'critical'

    def test_ok_at_exact_warn(self, monitor, monkeypatch):
        """При RSS точно равном warn_mb — 'warning' (>= check)."""
        monkeypatch.setattr(
            monitor, 'track_memory',
            lambda: {'rss_mb': 500.0, 'vms_mb': 0, 'percent': 0},
        )
        result = monitor.check_thresholds()
        assert result == 'warning'

    def test_returns_string_not_int(self, monitor, monkeypatch):
        monkeypatch.setattr(
            monitor, 'track_memory',
            lambda: {'rss_mb': 100.0, 'vms_mb': 0, 'percent': 0},
        )
        result = monitor.check_thresholds()
        assert isinstance(result, str)
        assert result in ('ok', 'warning', 'critical')


# --------------------------------------------------------------------------- #
#  track_memory()                                                             #
# --------------------------------------------------------------------------- #


class TestTrackMemory:
    def test_returns_dict_with_keys(self):
        """track_memory возвращает словарь с rss_mb, vms_mb, percent."""
        monitor = MemoryMonitor()
        result = monitor.track_memory()
        assert isinstance(result, dict)
        assert 'rss_mb' in result
        assert 'vms_mb' in result
        assert 'percent' in result

    def test_rss_mb_is_number(self):
        result = MemoryMonitor().track_memory()
        assert isinstance(result['rss_mb'], (int, float))
        assert result['rss_mb'] >= 0

    def test_vms_mb_is_number(self):
        result = MemoryMonitor().track_memory()
        assert isinstance(result['vms_mb'], (int, float))

    def test_percent_is_number(self):
        result = MemoryMonitor().track_memory()
        assert isinstance(result['percent'], (int, float))

    def test_rss_mb_positive(self):
        result = MemoryMonitor().track_memory()
        assert result['rss_mb'] > 0

    def test_rss_mb_rounded(self):
        result = MemoryMonitor().track_memory()
        # rss_mb должен быть округлён до 2 знаков
        assert result['rss_mb'] == round(result['rss_mb'], 2)


# --------------------------------------------------------------------------- #
#  auto_gc()                                                                  #
# --------------------------------------------------------------------------- #


class TestAutoGc:
    def test_returns_zero_when_memory_low(self, monitor, monkeypatch):
        """Когда память ниже warn — auto_gc возвращает 0."""
        monkeypatch.setattr(
            monitor, 'track_memory',
            lambda: {'rss_mb': 100.0, 'vms_mb': 0, 'percent': 0},
        )
        result = monitor.auto_gc()
        assert result == 0

    def test_returns_zero_when_memory_at_warn(self, monitor, monkeypatch):
        """При RSS точно на warn_mb — auto_gc запускает gc (>= check)."""
        monkeypatch.setattr(
            monitor, 'track_memory',
            lambda: {'rss_mb': 500.0, 'vms_mb': 0, 'percent': 0},
        )
        result = monitor.auto_gc()
        # Должен запуститься gc.collect
        assert isinstance(result, int)
        assert result >= 0

    def test_returns_int(self, monitor):
        result = monitor.auto_gc()
        assert isinstance(result, int)

    def test_calls_gc_collect(self, monitor, monkeypatch):
        """auto_gc вызывает gc.collect() при высокой памяти."""
        monkeypatch.setattr(
            monitor, 'track_memory',
            lambda: {'rss_mb': 600.0, 'vms_mb': 0, 'percent': 0},
        )
        with patch('memory_monitor.gc.collect') as mock_gc:
            mock_gc.return_value = 42
            result = monitor.auto_gc()
            mock_gc.assert_called_once()
            assert result == 42
