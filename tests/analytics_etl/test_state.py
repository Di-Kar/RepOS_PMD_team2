"""Unit-tests для analytics_etl.state — OffsetStorage."""

import os
from unittest.mock import MagicMock, patch

import pytest
from state import OffsetStorage

# --------------------------------------------------------------------------- #
#  Фикстуры                                                                   #
# --------------------------------------------------------------------------- #


@pytest.fixture
def tmp_state_dir(tmp_path):
    """Временная директория для состояния."""
    state_dir = str(tmp_path / 'state')
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


@pytest.fixture
def storage(tmp_state_dir):
    return OffsetStorage(state_dir=tmp_state_dir, filename='test_offsets.json')


# --------------------------------------------------------------------------- #
#  save_state() / load_state()                                                #
# --------------------------------------------------------------------------- #


class TestSaveLoadState:
    def test_save_and_load(self, storage):
        state = {
            'kafka_offsets': {'topic-A': {'0': 100, '1': 200}},
            'etl_state': {'cursor': 'abc'},
        }
        storage.save_state(state)
        loaded = storage.load_state()
        assert loaded == state

    def test_save_load_preserves_types(self, storage):
        state = {'count': 42, 'flag': True, 'nested': {'key': 'value'}}
        storage.save_state(state)
        loaded = storage.load_state()
        assert loaded['count'] == 42
        assert loaded['flag'] is True
        assert loaded['nested']['key'] == 'value'

    def test_load_nonexistent_file_returns_empty(self, tmp_state_dir):
        storage = OffsetStorage(
            state_dir=tmp_state_dir,
            filename='nonexistent.json',
        )
        result = storage.load_state()
        assert result == {}

    def test_load_corrupt_json_returns_empty(self, tmp_state_dir):
        storage = OffsetStorage(
            state_dir=tmp_state_dir,
            filename='corrupt.json',
        )
        # Записать мусор в файл
        corrupt_path = os.path.join(tmp_state_dir, 'corrupt.json')
        with open(corrupt_path, 'w') as f:
            f.write('{corrupt json!!!}')
        result = storage.load_state()
        assert result == {}


# --------------------------------------------------------------------------- #
#  save_offsets() / load_offsets()                                            #
# --------------------------------------------------------------------------- #


class TestOffsets:
    def test_save_and_load_offsets(self, storage):
        offsets = {'topic-A': {'0': 100, '1': 200}, 'topic-B': {'0': 50}}
        storage.save_offsets(offsets)
        loaded = storage.load_offsets()
        assert loaded == offsets

    def test_load_offsets_when_none_saved(self, storage):
        result = storage.load_offsets()
        assert result == {}


# --------------------------------------------------------------------------- #
#  save_etl_state() / load_etl_state()                                        #
# --------------------------------------------------------------------------- #


class TestEtlState:
    def test_save_and_load_etl_state(self, storage):
        storage.save_etl_state('cursor', 'abc-123')
        storage.save_etl_state('batch_size', 100)
        result = storage.load_etl_state()
        assert result['cursor'] == 'abc-123'
        assert result['batch_size'] == 100

    def test_load_etl_state_when_none_saved(self, storage):
        result = storage.load_etl_state()
        assert result == {}

    def test_etl_state_overwrite(self, storage):
        storage.save_etl_state('cursor', 'v1')
        storage.save_etl_state('cursor', 'v2')
        result = storage.load_etl_state()
        assert result['cursor'] == 'v2'

    def test_etl_state_preserves_other_keys(self, storage):
        storage.save_etl_state('a', 1)
        storage.save_etl_state('b', 2)
        result = storage.load_etl_state()
        assert 'a' in result
        assert 'b' in result
        assert result['a'] == 1
        assert result['b'] == 2


# --------------------------------------------------------------------------- #
#  Atomicity: tempfile + os.replace                                           #
# --------------------------------------------------------------------------- #


class TestAtomicity:
    def test_save_uses_tempfile_and_replace(self, tmp_state_dir):
        """save_state использует tempfile.NamedTemporaryFile + os.replace."""
        storage = OffsetStorage(
            state_dir=tmp_state_dir,
            filename='atomic_test.json',
        )

        with patch('state.tempfile.NamedTemporaryFile') as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = '/tmp/mock_tmp_123'
            mock_tmp.return_value.__enter__.return_value = mock_file
            mock_tmp.return_value.__exit__.return_value = False

            with patch('state.os.replace') as mock_replace:
                storage.save_state({'key': 'value'})

                # NamedTemporaryFile должен быть создан
                mock_tmp.assert_called_once()
                # os.replace должен быть вызван
                mock_replace.assert_called_once_with(
                    '/tmp/mock_tmp_123',
                    os.path.join(tmp_state_dir, 'atomic_test.json'),
                )

    def test_save_creates_state_dir(self, tmp_path):
        """save_state создаёт state_dir, если его нет."""
        new_dir = str(tmp_path / 'new_dir' / 'sub')
        storage = OffsetStorage(state_dir=new_dir, filename='test.json')
        storage.save_state({'key': 'val'})
        assert os.path.exists(os.path.join(new_dir, 'test.json'))
