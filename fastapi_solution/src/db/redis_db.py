from typing import Optional

from redis.asyncio import Redis

redis: Optional[Redis] = None


# Функция понадобится при внедрении зависимостей
def get_redis() -> Redis:
    return redis
