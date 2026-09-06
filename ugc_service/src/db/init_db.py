"""Инициализация MongoDB кластера: sharding и индексы."""

import logging

from config import settings
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


async def init_cluster():
    """Настроить sharding для базы данных ugc_service."""
    # Подключаемся к mongos для административных команд
    client = AsyncIOMotorClient(settings.mongo_uri)

    try:
        # Включаем sharding для базы
        admin_db = client['admin']
        await admin_db.command({'enableSharding': settings.mongo_db})
        logger.info('Sharding включён для базы: %s', settings.mongo_db)

        # Создаём shard keys для каждой коллекции
        shard_keys = {
            'bookmarks': {'user_id': 'hashed'},
            'likes': {'user_id': 'hashed'},
            'reviews': {'film_id': 1},
            'review_votes': {'review_id': 1},
        }

        db = client[settings.mongo_db]

        for collection_name, shard_key in shard_keys.items():
            await db.command(
                {
                    'shardCollection': f'{settings.mongo_db}.{collection_name}',
                    'key': shard_key,
                }
            )
            logger.info(
                'Shard key создан для коллекции %s: %s',
                collection_name,
                shard_key,
            )

        # Создаём уникальные индексы для составных полей
        unique_indexes = {
            'bookmarks': {'user_id': 1, 'film_id': 1},
            'likes': {'user_id': 1, 'film_id': 1},
            'review_votes': {'user_id': 1, 'review_id': 1},
        }

        for collection_name, index_keys in unique_indexes.items():
            await db[collection_name].create_index(
                list(index_keys.items()), unique=True
            )
            logger.info(
                'Уникальный индекс создан для коллекции %s: %s',
                collection_name,
                index_keys,
            )

        logger.info('Инициализация кластера MongoDB завершена')

    except Exception as e:
        # Шдинг может уже быть включён — игнорируем ошибки
        logger.warning('Ошибка инициализации кластера (может уже существует): %s', e)
    finally:
        client.close()
