"""Unit-tests для analytics_etl.backoff_utils — декоратор backoff."""

from unittest.mock import patch

import pytest
from backoff_utils import backoff, configure

# --------------------------------------------------------------------------- #
#  Фикстуры                                                                   #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def reset_config():
    """Сбросить глобальную конфигу backoff перед каждым тестом."""
    # Сохранить оригинальные значения
    import backoff_utils as mod
    orig_start = mod._start_sleep_time
    orig_factor = mod._factor
    orig_border = mod._border_sleep_time
    orig_max = mod._max_attempts
    yield
    # Восстановить
    mod._start_sleep_time = orig_start
    mod._factor = orig_factor
    mod._border_sleep_time = orig_border
    mod._max_attempts = orig_max


# --------------------------------------------------------------------------- #
#  basic backoff behaviour                                                     #
# --------------------------------------------------------------------------- #


class TestBackoffDecorator:
    def test_succeeds_on_first_try(self):
        """Когда функция не выбрасывает исключений — вызов 1 раз."""
        call_count = 0

        @backoff(exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            return 'ok'

        result = fn()
        assert result == 'ok'
        assert call_count == 1

    def test_retries_on_exception(self):
        """При исключении — повторный вызов с задержкой."""
        call_count = 0
        sleeps = []

        @backoff(exceptions=(RuntimeError,))
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError('fail')
            return 'success'

        with patch('backoff_utils.time.sleep') as mock_sleep:
            mock_sleep.side_effect = lambda s: sleeps.append(s)
            result = fn()

        assert result == 'success'
        assert call_count == 3
        assert len(sleeps) == 2  # sleep между попытками 1→2 и 2→3

    def test_raises_after_max_attempts(self):
        """Когда max_attempts достигнут — KeyError/BrokenError передаётся дальше."""
        call_count = 0

        configure(max_attempts=3, start_sleep_time=0.01, border_sleep_time=1.0)

        @backoff(exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            raise ValueError('always fail')

        with patch('backoff_utils.time.sleep'):
            with pytest.raises(ValueError, match='always fail'):
                fn()

        assert call_count == 3

    def test_raises_original_exception(self):
        """Внезапное исключение, не в списке — пробрасывается без повторов."""
        @backoff(exceptions=(ValueError,))
        def fn():
            raise TypeError('wrong type')

        with pytest.raises(TypeError, match='wrong type'):
            fn()


# --------------------------------------------------------------------------- #
#  configure()                                                                #
# --------------------------------------------------------------------------- #


class TestConfigure:
    def test_sets_global_parameters(self):
        """configure меняет глобальные параметры."""
        import backoff_utils as mod
        configure(
            start_sleep_time=0.5,
            factor=3,
            border_sleep_time=30.0,
            max_attempts=5,
        )
        assert mod._start_sleep_time == 0.5
        assert mod._factor == 3
        assert mod._border_sleep_time == 30.0
        assert mod._max_attempts == 5

    def test_zero_max_attempts_no_limit(self):
        """max_attempts=0 = без ограничений."""
        import backoff_utils as mod
        configure(max_attempts=0)
        assert mod._max_attempts == 0


# --------------------------------------------------------------------------- #
#  Exponential sleep growth                                                   #
# --------------------------------------------------------------------------- #


class TestExponentialSleep:
    def test_sleep_grows_exponentially(self):
        """Сон растёт по формуле sleep *= factor (до border_sleep_time)."""
        sleeps = []

        configure(start_sleep_time=0.1, factor=2, border_sleep_time=10.0, max_attempts=5)

        @backoff(exceptions=(ValueError,))
        def fn():
            raise ValueError('fail')

        with patch('backoff_utils.time.sleep') as mock_sleep:
            mock_sleep.side_effect = lambda s: sleeps.append(s)
            with pytest.raises(ValueError):
                fn()

        # Ожидаемые sleep: 0.1, 0.2, 0.4, 0.8 (4 попытки, 3 sleep)
        assert len(sleeps) == 4
        assert sleeps[0] == 0.1
        assert sleeps[1] == 0.2
        assert sleeps[2] == 0.4
        assert sleeps[3] == 0.8

    def test_sleep_capped_at_border(self):
        """sleep не превышает border_sleep_time."""
        sleeps = []

        configure(
            start_sleep_time=5.0,
            factor=2,
            border_sleep_time=10.0,
            max_attempts=10,
        )

        @backoff(exceptions=(ValueError,))
        def fn():
            raise ValueError('fail')

        with patch('backoff_utils.time.sleep') as mock_sleep:
            mock_sleep.side_effect = lambda s: sleeps.append(s)
            with pytest.raises(ValueError):
                fn()

        # Первые sleep: 5.0, 10.0 (cap), 10.0, ...
        assert sleeps[0] == 5.0
        assert sleeps[1] == 10.0
        # Все последующие тоже должны быть capped
        assert all(s == 10.0 for s in sleeps[1:])
