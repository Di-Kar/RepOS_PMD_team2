"""Tests for _last_offsets: topic-partition keying and last_offsets property."""

import pytest
from unittest.mock import MagicMock
from processor import EventProcessor


@pytest.fixture
def processor():
    """Создать EventProcessor с моками зависимостей."""
    loader = MagicMock()
    dlq = MagicMock()
    return EventProcessor(loader, dlq)


def test_offsets_empty_initially(processor):
    """Verify new EventProcessor starts with empty _last_offsets."""
    assert processor._last_offsets == {}
    assert len(processor.last_offsets) == 0


def test_offsets_set_with_topic_key(processor):
    """Verify the write pattern works — topic as outer key, partition as inner key."""
    processor._last_offsets['clicks'] = {0: 100}
    processor._last_offsets['pageviews'] = {0: 200}

    assert processor._last_offsets == {
        'clicks': {0: 100},
        'pageviews': {0: 200},
    }


def test_offsets_no_collision_across_topics(processor):
    """Verify that same partition number in different topics does NOT collide."""
    processor._last_offsets['clicks'] = {0: 50}
    processor._last_offsets['pageviews'] = {0: 99}

    assert processor._last_offsets['clicks'][0] == 50
    assert processor._last_offsets['pageviews'][0] == 99
    assert len(processor._last_offsets) == 2
    assert len(processor._last_offsets['clicks']) == 1


def test_offsets_same_topic_multiple_partitions(processor):
    """Verify multiple partitions within the same topic work correctly."""
    processor._last_offsets['clicks'] = {0: 100, 1: 200}

    assert processor._last_offsets['clicks'] == {0: 100, 1: 200}


def test_offsets_overwrite_within_same_topic_partition(processor):
    """Verify that updating offset for same topic+partition replaces old value."""
    processor._last_offsets['clicks'] = {0: 100}
    processor._last_offsets['clicks'][0] = 150

    assert processor._last_offsets['clicks'][0] == 150
    assert len(processor._last_offsets['clicks']) == 1


def test_last_offsets_property_returns_copy(processor):
    """Verify last_offsets returns a copy, not the internal reference."""
    processor._last_offsets['clicks'] = {0: 100}
    result = processor.last_offsets

    assert result['clicks'][0] == 100

    # Modify result — should NOT change internal state
    result['clicks'][0] = 999
    assert processor._last_offsets['clicks'][0] == 100

    # Remove from result — should NOT affect internal state
    del result['clicks']
    assert 'clicks' in processor._last_offsets


def test_last_offsets_empty_returns_empty_dict(processor):
    """Empty processor returns empty dict from property."""
    assert processor.last_offsets == {}
