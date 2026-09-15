"""Инициализация MongoDB кластера: sharding и индексы."""

import logging

from config import settings
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


async def _wait_for_sharding_init(admin_db, db_name, max_retries=10):
    """Ожидание инициализации sharding для базы данных."""
    import asyncio

    for attempt in range(max_retries):
        try:
            # Проверяем статус sharding через listDatabases
            result = await admin_db.command({'listDatabases': 1, 'name': db_name})
            for db in result.get('databases', []):
                if db.get('name') == db_name:
                    logger.info('Sharding инициализирован для базы: %s', db_name)
                    return
            # Если база не найдена в списке, ждём
            if attempt < max_retries - 1:
                logger.debug(
                    'Ожидание инициализации sharding... ' '(попытка %d/%d)',
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(2)
        except Exception:
            # База данных ещё не готова
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            else:
                raise


async def _create_shard_key_with_retry(
    db, db_name, collection_name, shard_key, max_retries=5
):
    """Создание shard key с повторными попытками."""
    import asyncio

    full_collection_name = f'{db_name}.{collection_name}'

    for attempt in range(max_retries):
        try:
            await db.command(
                {
                    'shardCollection': full_collection_name,
                    'key': shard_key,
                }
            )
            logger.info(
                'Shard key создан для коллекции %s: %s',
                collection_name,
                shard_key,
            )
            return
        except Exception as e:
            error_msg = str(e)
            # Если ошибка связана с тем, что sharding не инициализирован
            if 'sharding state has not been initialized' in error_msg:
                if attempt < max_retries - 1:
                    logger.debug(
                        'Sharding ещё не инициализирован для коллекции %s. '
                        'Повторная попытка %d/%d',
                        collection_name,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(3)
                else:
                    raise
            else:
                # Другая ошибка — пробрасываем дальше
                raise


async def init_cluster():
    """Настроить sharding для базы данных ugc_service."""
    # Подключаемся к mongos для административных команд
    client = AsyncIOMotorClient(settings.mongo_uri)

    try:
        # Включаем sharding для базы
        admin_db = client['admin']
        await admin_db.command({'enableSharding': settings.mongo_db})
        logger.info('Sharding включён для базы: %s', settings.mongo_db)

        # Ждём, пока sharding инициализируется для базы данных
        await _wait_for_sharding_init(admin_db, settings.mongo_db)

        # Создаём shard keys для каждой коллекции
        shard_keys = {
            'bookmarks': {'user_id': 'hashed'},
            'likes': {'user_id': 'hashed'},
            'reviews': {'film_id': 1},
            'review_votes': {'review_id': 1},
        }

        db = client[settings.mongo_db]

        for collection_name, shard_key in shard_keys.items():
            await _create_shard_key_with_retry(
                db, settings.mongo_db, collection_name, shard_key
            )

        logger.info('Инициализация кластера MongoDB завершена')

    except Exception as e:
        # Шдинг может уже быть включён — игнорируем ошибки
        logger.warning('Ошибка инициализации кластера (может уже существует): %s', e)
    finally:
        client.close()
