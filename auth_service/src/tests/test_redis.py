import pytest
from redis.asyncio import Redis


class TestRedisConnection:
    """Тесты подключения к Redis"""
    
    async def test_connection(self, redis_client: Redis):
        """Проверяем подключение через PING"""
        result = await redis_client.ping()
        assert result is True
    
    async def test_set_and_get(self, redis_client: Redis):
        """Базовая операция set/get"""
        await redis_client.set("test_key", "test_value")
        value = await redis_client.get("test_key")
        
        assert value == "test_value"
    
    async def test_get_nonexistent_key(self, redis_client: Redis):
        """Получение несуществующего ключа"""
        value = await redis_client.get("nonexistent_key")
        assert value is None


class TestRedisTTL:
    """Тесты работы с временем жизни ключей"""
    
    async def test_set_with_ttl(self, redis_client: Redis):
        """Установка ключа с TTL"""
        await redis_client.setex("ttl_key", 10, "ttl_value")
        
        value = await redis_client.get("ttl_key")
        ttl = await redis_client.ttl("ttl_key")
        
        assert value == "ttl_value"
        assert 0 < ttl <= 10
    
    async def test_expire_key(self, redis_client: Redis):
        """Установка TTL через expire"""
        await redis_client.set("expire_key", "value")
        await redis_client.expire("expire_key", 5)
        
        ttl = await redis_client.ttl("expire_key")
        assert 0 < ttl <= 5
    
    async def test_key_expiration(self, redis_client: Redis):
        """Проверяем, что ключ удаляется по истечении TTL"""
        import asyncio
        
        await redis_client.setex("short_ttl", 1, "value")
        
        # Ждём, пока ключ истечёт
        await asyncio.sleep(1.5)
        
        value = await redis_client.get("short_ttl")
        assert value is None


class TestRedisDataTypes:
    """Тесты различных структур данных Redis"""
    
    async def test_hash_operations(self, redis_client: Redis):
        """Работа с хэш-таблицами"""
        await redis_client.hset("user:1", mapping={
            "name": "John",
            "email": "john@example.com",
            "age": "30",
        })
        
        name = await redis_client.hget("user:1", "name")
        all_fields = await redis_client.hgetall("user:1")
        
        assert name == "John"
        assert all_fields == {
            "name": "John",
            "email": "john@example.com",
            "age": "30",
        }
    
    async def test_list_operations(self, redis_client: Redis):
        """Работа со списками"""
        await redis_client.rpush("queue", "task1", "task2", "task3")
        
        length = await redis_client.llen("queue")
        first = await redis_client.lpop("queue")
        remaining = await redis_client.lrange("queue", 0, -1)
        
        assert length == 3
        assert first == "task1"
        assert remaining == ["task2", "task3"]
    
    async def test_set_operations(self, redis_client: Redis):
        """Работа с множествами"""
        await redis_client.sadd("tags", "python", "fastapi", "redis")
        
        is_member = await redis_client.sismember("tags", "python")
        members = await redis_client.smembers("tags")
        
        assert is_member == 1
        assert members == {"python", "fastapi", "redis"}


class TestRedisTransactions:
    """Тесты транзакций (pipeline)"""
    
    async def test_pipeline_basic(self, redis_client: Redis):
        """Базовая работа с pipeline"""
        pipeline = redis_client.pipeline()
        pipeline.set("key1", "value1")
        pipeline.set("key2", "value2")
        pipeline.set("key3", "value3")
        results = await pipeline.execute()
        
        assert results == [True, True, True]
        
        value1 = await redis_client.get("key1")
        value2 = await redis_client.get("key2")
        value3 = await redis_client.get("key3")
        
        assert value1 == "value1"
        assert value2 == "value2"
        assert value3 == "value3"
    
    async def test_pipeline_with_ttl(self, redis_client: Redis):
        """Pipeline с установкой TTL"""
        pipeline = redis_client.pipeline()
        pipeline.setex("token1", 3600, "access_token_1")
        pipeline.setex("token2", 3600, "access_token_2")
        await pipeline.execute()
        
        ttl1 = await redis_client.ttl("token1")
        ttl2 = await redis_client.ttl("token2")
        
        assert 0 < ttl1 <= 3600
        assert 0 < ttl2 <= 3600
    
    async def test_pipeline_atomicity(self, redis_client: Redis):
        """Проверяем атомарность pipeline"""
        pipeline = redis_client.pipeline()
        pipeline.incr("counter")
        pipeline.incr("counter")
        pipeline.incr("counter")
        await pipeline.execute()
        
        value = await redis_client.get("counter")
        assert value == "3"


class TestRedisInvalidTokens:
    """Тесты сценария хранения невалидных токенов"""
    
    async def test_store_invalid_token(self, redis_client: Redis):
        """Хранение невалидного access-токена"""
        user_id = "user-123"
        token = "invalid_token_abc"
        ttl = 3600  # 1 час
        
        # Сохраняем невалидный токен
        key = f"invalid_token:{user_id}:{token}"
        await redis_client.setex(key, ttl, "revoked")
        
        # Проверяем, что токен в списке невалидных
        exists = await redis_client.exists(key)
        assert exists == 1
    
    async def test_store_refresh_token(self, redis_client: Redis):
        """Хранение refresh-токена"""
        user_id = "user-456"
        refresh_token = "refresh_xyz"
        
        # Сохраняем refresh-токен с привязкой к пользователю
        key = f"refresh_token:{user_id}"
        await redis_client.setex(key, 7 * 24 * 3600, refresh_token)  # 7 дней
        
        stored_token = await redis_client.get(key)
        assert stored_token == refresh_token
    
    async def test_revoke_all_user_tokens(self, redis_client: Redis):
        """Массовый сброс всех сессий пользователя"""
        user_id = "user-789"
        
        # Создаём несколько токенов пользователя
        pipeline = redis_client.pipeline()
        for i in range(5):
            pipeline.setex(f"session:{user_id}:{i}", 3600, f"token_{i}")
        await pipeline.execute()
        
        # Получаем все ключи пользователя
        pattern = f"session:{user_id}:*"
        keys = []
        async for key in redis_client.scan_iter(match=pattern):
            keys.append(key)
        
        assert len(keys) == 5
        
        # Удаляем все сессии пользователя
        if keys:
            await redis_client.delete(*keys)
        
        # Проверяем, что все удалены
        remaining = []
        async for key in redis_client.scan_iter(match=pattern):
            remaining.append(key)
        
        assert len(remaining) == 0
