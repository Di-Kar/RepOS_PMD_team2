from abc import ABC, abstractmethod
from typing import Generic, List, Optional, TypeVar

T = TypeVar('T')


class CacheInterface(ABC, Generic[T]):
    """Интерфейс для работы с кэшем. Соблюдает ISP и DIP."""

    @abstractmethod
    async def get(self, key: str) -> Optional[T]:
        """Получить одиночный объект из кэша."""

    @abstractmethod
    async def set(self, key: str, value: T, expire: int) -> None:
        """Сохранить одиночный объект в кэш."""

    @abstractmethod
    async def get_list(self, key: str) -> Optional[List[T]]:
        """Получить список объектов из кэша."""

    @abstractmethod
    async def set_list(self, key: str, value: List[T], expire: int) -> None:
        """Сохранить список объектов в кэш."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Удалить объект из кэша по ключу."""

    @abstractmethod
    async def delete_pattern(self, pattern: str) -> None:
        """Удалить объекты из кэша по паттерну ключа."""
