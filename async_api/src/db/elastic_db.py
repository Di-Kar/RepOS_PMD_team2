
from elasticsearch import AsyncElasticsearch
from fastapi import Request


def get_elastic(request: Request) -> AsyncElasticsearch:
    return request.app.state.elastic
