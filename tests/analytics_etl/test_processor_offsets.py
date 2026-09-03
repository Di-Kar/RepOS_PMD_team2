"""Tests for _pending_offsets: topic-partition keying, offset lifecycle, and clear_committed_offsets."""

from unittest.mock import MagicMock

import pytest
from processor import EventProcessor


@pytest.fixture
def processor():
    """Создать EventProcessor с моками зависимостей."""
    loader = MagicMock()
    dlq = MagicMock()
    return EventProcessor(loader, dlq)


# ---------------------------------------------------------------------------
# Tests for _pending_offsets structure
# ---------------------------------------------------------------------------


def test_pending_offsets_empty_initially(processor):
    """Verify new EventProcessor starts with empty _pending_offsets."""
    assert processor._pending_offsets == {}
    assert len(processor.pending_offsets) == 0


def test_pending_offsets_set_with_topic_key(processor):
    """Verify the write pattern works — topic as outer key, partition as inner key."""
    processor._pending_offsets['clicks'] = {0: 100}
    processor._pending_offsets['pageviews'] = {0: 200}

    assert processor._pending_offsets == {
        'clicks': {0: 100},
        'pageviews': {0: 200},
    }


def test_pending_offsets_no_collision_across_topics(processor):
    """Verify that same partition number in different topics does NOT collide."""
    processor._pending_offsets['clicks'] = {0: 50}
    processor._pending_offsets['pageviews'] = {0: 99}

    assert processor._pending_offsets['clicks'][0] == 50
    assert processor._pending_offsets['pageviews'][0] == 99
    assert len(processor._pending_offsets) == 2
    assert len(processor._pending_offsets['clicks']) == 1


def test_pending_offsets_same_topic_multiple_partitions(processor):
    """Verify multiple partitions within the same topic work correctly."""
    processor._pending_offsets['clicks'] = {0: 100, 1: 200}

    assert processor._pending_offsets['clicks'] == {0: 100, 1: 200}


def test_pending_offsets_overwrite_within_same_topic_partition(processor):
    """Verify that updating offset for same topic+partition replaces old value."""
    processor._pending_offsets['clicks'] = {0: 100}
    processor._pending_offsets['clicks'][0] = 150

    assert processor._pending_offsets['clicks'][0] == 150
    assert len(processor._pending_offsets['clicks']) == 1


def test_pending_offsets_property_returns_copy(processor):
    """Verify pending_offsets returns a copy, not the internal reference."""
    processor._pending_offsets['clicks'] = {0: 100}
    result = processor.pending_offsets

    assert result['clicks'][0] == 100

    # Modify result — should NOT change internal state
    result['clicks'][0] = 999
    assert processor._pending_offsets['clicks'][0] == 100

    # Remove from result — should NOT affect internal state
    del result['clicks']
    assert 'clicks' in processor._pending_offsets


def test_pending_offsets_empty_returns_empty_dict(processor):
    """Empty processor returns empty dict from property."""
    assert processor.pending_offsets == {}


# ---------------------------------------------------------------------------
# Tests for clear_committed_offsets
# ---------------------------------------------------------------------------


def test_clear_committed_offsets_clears_all(processor):
    """Verify clear_committed_offsets clears the entire _pending_offsets."""
    processor._pending_offsets['clicks'] = {0: 100}
    processor._pending_offsets['pageviews'] = {0: 200}

    processor.clear_committed_offsets()

    assert processor._pending_offsets == {}
    assert processor.pending_offsets == {}


def test_clear_committed_offsets_on_empty(processor):
    """Verify clear_committed_offsets works on empty state."""
    processor.clear_committed_offsets()
    # Should not raise, state remains empty
    assert processor._pending_offsets == {}


# ---------------------------------------------------------------------------
# Tests for flush() return value (count, success)
# ---------------------------------------------------------------------------


def test_flush_returns_tuple(processor):
    """Verify flush() returns a tuple of (count, success)."""
    result = processor.flush()
    assert isinstance(result, tuple)
    assert len(result) == 2
    count, success = result
    assert isinstance(count, int)
    assert isinstance(success, bool)


def test_flush_empty_returns_zero_and_true(processor):
    """When buffer is empty, flush returns (0, True)."""
    count, success = processor.flush()
    assert count == 0
    assert success is True
