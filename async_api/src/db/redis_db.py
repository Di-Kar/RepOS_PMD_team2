from typing import Optional

from redis.asyncio import Redis
from fastapi import Request


def get_redis(request: Request) -> Redis:
    return request.app.state.redis