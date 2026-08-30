"""Конфигурация тестов для ugc_service."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_beanie():
    """Мокаем Beanie для тестов без реальной MongoDB."""
    mock_doc = MagicMock()
    mock_doc.insert = AsyncMock()
    mock_doc.delete = AsyncMock()
    mock_doc.save = AsyncMock()
    mock_doc.find_one = AsyncMock(return_value=None)
    mock_doc.find = MagicMock()
    mock_doc.find.return_value.skip = MagicMock()
    mock_doc.find.return_value.limit = MagicMock()
    mock_doc.find.return_value.sort = MagicMock()
    mock_doc.find.return_value.to_list = AsyncMock(return_value=[])
    mock_doc.get = AsyncMock(return_value=None)
    return mock_doc
