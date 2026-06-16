import logging
from contextlib import asynccontextmanager

import uvicorn
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI
from redis.asyncio import Redis, ConnectionPool

from api.v1 import films, genres, persons
from core import config
from core.logger import LOGGING
from db import elastic_db
from db import redis_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Подключаемся к базам при старте сервера
    # Подключиться можем при работающем event-loop
    # Поэтому логика подключения происходит в асинхронной функции
    redis_pool = ConnectionPool(
        host=config.settings.redis_host,
        port=config.settings.redis_port,
        max_connections=500,
    )
    app.state.redis = Redis(connection_pool=redis_pool)
    app.state.elastic = AsyncElasticsearch(
        hosts=[f'{config.settings.elastic_schema}{config.settings.elastic_host}:{config.settings.elastic_port}'],
        max_retries=3,
        connections_per_node=32,
    )
    yield
    # Отключаемся от баз при выключении сервера
    await app.state.redis.close()
    await app.state.elastic.close()


app = FastAPI(
    title="Async API — Онлайн-кинотеатр",
    description=(
        "Read-only REST API для поиска фильмов, жанров и персон. "
        "Данные хранятся в Elasticsearch, ответы кэшируются в Redis. "
        "Источник данных — PostgreSQL, перенос осуществляется ETL-пайплайном."
    ),
    version="1.0.0",
    # Адрес документации в красивом интерфейсе
    docs_url='/api/openapi',
    # Адрес документации в формате OpenAPI
    openapi_url='/api/openapi.json',
    lifespan=lifespan
)

app.include_router(films.router, prefix='/api/v1/films')
app.include_router(genres.router, prefix='/api/v1/genres')
app.include_router(persons.router, prefix='/api/v1/persons')

if __name__ == '__main__':
    # Приложение может запускаться командой
    # `uvicorn main:app --host 0.0.0.0 --port 8000`
    # но чтобы не терять возможность использовать дебагер,
    # запустим uvicorn-сервер через python
    # В продакшене (Docker/Kubernetes) приложение запускается через Gunicorn
    uvicorn.run(
        'src.main:app',
        host='0.0.0.0',
        port=8000,
        log_config=LOGGING,
        log_level=logging.DEBUG,
    )
