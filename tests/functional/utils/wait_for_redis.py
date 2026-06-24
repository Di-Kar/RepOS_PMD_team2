import sys
from pathlib import Path

import redis
from backoff import backoff

# Добавление пути к файлу настроек, т.к. запускается как скрипт, а не модуль
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.functional.settings import test_settings

@backoff(redis.ConnectionError)
def ping_redis(client):
    if not client.ping():
        raise redis.ConnectionError("Redis don't response")
    return "Redis is available."


if __name__ == '__main__':
    redis_client = redis.Redis(
        host=test_settings.redis_settings.host,
        port=test_settings.redis_settings.port
    )
    try:
        result = ping_redis(redis_client)
        print(result)
    except (redis.ConnectionError, TimeoutError) as e:
        print(e)
