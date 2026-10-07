"""Пользовательские данные карточки фильма: рейтинг, рецензии и ФИО авторов.

Все данные идут из ugc_service и user_profiles, в кэш фильма (services/base.py)
не попадают — иначе рейтинг застывал бы вместе с Film. Кэшируются только имена
авторов (Redis, ключ profile_name:{user_id}); кэш best-effort.
"""

import asyncio
import logging
from typing import Optional
from uuid import UUID

from db.profiles_client import ProfilesClient
from db.ugc_client import UgcClient
from fastapi import Request
from models.film import FilmUserRating
from redis.asyncio import Redis
from redis.exceptions import RedisError
from ugc_schemas import ReviewWithAuthorSchema

logger = logging.getLogger(__name__)

ANONYMOUS_NAME = 'Аноним'
CARD_REVIEWS_LIMIT = 5
NAME_CACHE_KEY = 'profile_name:{user_id}'
NAME_CACHE_TTL_SECONDS = 600


class UgcCardService:
    def __init__(self, ugc: UgcClient, profiles: ProfilesClient, redis: Redis) -> None:
        self._ugc = ugc
        self._profiles = profiles
        self._redis = redis

    async def get_card_data(
        self, film_id: UUID
    ) -> tuple[Optional[FilmUserRating], list[ReviewWithAuthorSchema], bool]:
        """Данные для блока карточки: (рейтинг, топ рецензий, доступность ugc)."""
        stats, reviews = await asyncio.gather(
            self._ugc.get_film_stats(film_id),
            self.get_reviews(film_id, 'likes_count', 1, CARD_REVIEWS_LIMIT),
        )
        rating = FilmUserRating(**stats) if stats is not None else None
        available = stats is not None and reviews is not None
        return rating, reviews or [], available

    async def get_reviews(
        self, film_id: UUID, sort: str, page_number: int, page_size: int
    ) -> Optional[list[ReviewWithAuthorSchema]]:
        raw = await self._ugc.get_film_reviews(film_id, sort, page_number, page_size)
        if raw is None:
            return None
        names = await self._resolve_names({item['user_id'] for item in raw})
        return [
            ReviewWithAuthorSchema(
                **item, user_name=names.get(item['user_id'], ANONYMOUS_NAME)
            )
            for item in raw
        ]

    async def _resolve_names(self, user_ids: set[str]) -> dict[str, str]:
        async def resolve(user_id: str) -> tuple[str, Optional[str]]:
            name = await self._get_cached_name(user_id)
            if name is None:
                name = await self._profiles.get_full_name(user_id)
                if name is not None:
                    await self._cache_name(user_id, name)
            return user_id, name

        pairs = await asyncio.gather(*(resolve(uid) for uid in user_ids))
        return {uid: name for uid, name in pairs if name is not None}

    async def _get_cached_name(self, user_id: str) -> Optional[str]:
        try:
            cached = await self._redis.get(NAME_CACHE_KEY.format(user_id=user_id))
        except RedisError as exc:
            logger.warning('redis недоступен при чтении имени: %s', exc)
            return None
        if cached is None:
            return None
        return cached.decode() if isinstance(cached, bytes) else cached

    async def _cache_name(self, user_id: str, name: str) -> None:
        try:
            await self._redis.set(
                NAME_CACHE_KEY.format(user_id=user_id),
                name,
                ex=NAME_CACHE_TTL_SECONDS,
            )
        except RedisError as exc:
            logger.warning('redis недоступен при записи имени: %s', exc)


def get_ugc_card_service(request: Request) -> UgcCardService:
    state = request.app.state
    return UgcCardService(state.ugc_client, state.profiles_client, state.redis)
