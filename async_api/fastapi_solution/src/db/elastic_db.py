from typing import Optional

from elasticsearch import AsyncElasticsearch

es: Optional[AsyncElasticsearch] = None


# Функция понадобится при внедрении зависимостей
def get_elastic() -> AsyncElasticsearch:
    return es
