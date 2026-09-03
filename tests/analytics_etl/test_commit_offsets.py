"""Tests for _commit_offsets: partition assignment filtering and state saving."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure src is importable
_SRC_ROOT = Path(__file__).parent.parent.parent / 'analytics_etl' / 'src'
if _SRC_ROOT.is_dir() and str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import pytest
from confluent_kafka import TopicPartition

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_consumer():
    """Mock Kafka consumer with assignment()."""
    consumer = MagicMock()
    consumer.assignment.return_value = []
    return consumer


@pytest.fixture
def mock_processor():
    """Mock EventProcessor with pending_offsets."""
    processor = MagicMock()
    processor.pending_offsets = {}
    return processor


@pytest.fixture
def mock_storage():
    """Mock OffsetStorage."""
    with patch('main.OffsetStorage') as MockStorage:
        storage = MagicMock()
        MockStorage.return_value = storage
        yield storage


@pytest.fixture
def etl_settings_mock(tmp_path):
    """Mock etl_settings with a temporary state_dir."""
    with patch('main.etl_settings') as mock_settings:
        mock_settings.state_dir = str(tmp_path)
        yield mock_settings


# ---------------------------------------------------------------------------
# Tests for _commit_offsets with assignment filtering
# ---------------------------------------------------------------------------


def test_commit_offsets_uses_assignment(mock_consumer, mock_processor, mock_storage, etl_settings_mock):
    """Verify _commit_offsets filters offsets by consumer.assignment()."""
    from main import _commit_offsets

    # Setup: consumer has 2 assigned partitions
    assigned_tp = [
        TopicPartition('clicks', 0),
        TopicPartition('clicks', 1),
    ]
    mock_consumer.assignment.return_value = assigned_tp

    # Setup: processor has offsets for clicks/0 and clicks/1, plus an unassigned topic
    mock_processor.pending_offsets = {
        'clicks': {0: 100, 1: 200},
        'pageviews': {0: 50},  # not assigned — should be ignored
    }

    _commit_offsets(mock_consumer, mock_processor)

    # Verify commit was called with only assigned partitions
    mock_consumer.commit.assert_called_once()
    commit_args = mock_consumer.commit.call_args
    commit_list = commit_args.kwargs['offsets']

    assert len(commit_list) == 2
    topics_partitions = [(tp.topic, tp.partition, tp.offset) for tp in commit_list]
    assert ('clicks', 0, 100) in topics_partitions
    assert ('clicks', 1, 200) in topics_partitions
    assert ('pageviews', 0, 50) not in topics_partitions


def test_commit_offsets_empty_assignment(mock_consumer, mock_processor, mock_storage, etl_settings_mock):
    """Verify _commit_offsets handles empty assignment gracefully."""
    from main import _commit_offsets

    mock_consumer.assignment.return_value = []
    mock_processor.pending_offsets = {
        'clicks': {0: 100},
    }

    # Should not raise — commit is called with empty list (or not at all)
    _commit_offsets(mock_consumer, mock_processor)

    # commit may be called with empty list — that's acceptable
    if mock_consumer.commit.called:
        commit_list = mock_consumer.commit.call_args.kwargs['offsets']
        assert commit_list == []


def test_commit_offsets_only_some_partitions_assigned(mock_consumer, mock_processor, mock_storage, etl_settings_mock):
    """Verify only assigned partitions are committed, others ignored."""
    from main import _commit_offsets

    # Only partition 0 is assigned
    assigned_tp = [TopicPartition('pageviews', 0)]
    mock_consumer.assignment.return_value = assigned_tp

    mock_processor.pending_offsets = {
        'pageviews': {0: 50, 1: 60},  # 1 is NOT assigned
    }

    _commit_offsets(mock_consumer, mock_processor)

    commit_list = mock_consumer.commit.call_args.kwargs['offsets']
    assert len(commit_list) == 1
    assert commit_list[0].topic == 'pageviews'
    assert commit_list[0].partition == 0
    assert commit_list[0].offset == 50


def test_commit_offsets_empty_pending_offsets(mock_consumer, mock_processor, mock_storage, etl_settings_mock):
    """Verify _commit_offsets returns early when there are no pending offsets."""
    from main import _commit_offsets

    mock_consumer.assignment.return_value = [TopicPartition('clicks', 0)]
    mock_processor.pending_offsets = {}

    _commit_offsets(mock_consumer, mock_processor)

    # commit should NOT be called
    mock_consumer.commit.assert_not_called()


def test_commit_offsets_saves_state(mock_consumer, mock_processor, mock_storage, etl_settings_mock):
    """Verify offsets are saved to state storage."""
    from main import _commit_offsets

    assigned_tp = [TopicPartition('clicks', 0)]
    mock_consumer.assignment.return_value = assigned_tp

    mock_processor.pending_offsets = {
        'clicks': {0: 100},
    }

    _commit_offsets(mock_consumer, mock_processor)

    # Verify save_offsets was called with the pending offsets
    mock_storage.save_offsets.assert_called_once_with({
        'clicks': {0: 100},
    })


def test_commit_offsets_with_unassigned_topic(mock_consumer, mock_processor, mock_storage, etl_settings_mock):
    """Verify offsets for completely unassigned topics are ignored."""
    from main import _commit_offsets

    # Only clicks is assigned, not pageviews
    assigned_tp = [TopicPartition('clicks', 0)]
    mock_consumer.assignment.return_value = assigned_tp

    mock_processor.pending_offsets = {
        'clicks': {0: 100},
        'pageviews': {0: 200, 1: 300},
        'sessions': {0: 400},
    }

    _commit_offsets(mock_consumer, mock_processor)

    # Only clicks/0 should be committed
    commit_list = mock_consumer.commit.call_args.kwargs['offsets']
    assert len(commit_list) == 1
    assert commit_list[0].topic == 'clicks'
    assert commit_list[0].partition == 0
    assert commit_list[0].offset == 100

    # State should still save ALL pending offsets (for resume after restart)
    mock_storage.save_offsets.assert_called_once_with({
        'clicks': {0: 100},
        'pageviews': {0: 200, 1: 300},
        'sessions': {0: 400},
    })
