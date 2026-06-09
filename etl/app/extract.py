"""Извлечение данных из PostgreSQL."""
import logging
from typing import Any, Dict, List
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

MAIN_QUERY = """
    SELECT
        fw.id, fw.title, fw.description, fw.rating as imdb_rating,
        COALESCE(json_agg(DISTINCT g.name)
          FILTER (WHERE g.id IS NOT NULL), '[]')::jsonb as genres,
        COALESCE(json_agg(DISTINCT p.full_name)
          FILTER (WHERE pfw.role = 'actor' AND p.id IS NOT NULL), '[]')::jsonb as actors_names,
        COALESCE(json_agg(DISTINCT p.full_name)
          FILTER (WHERE pfw.role = 'writer' AND p.id IS NOT NULL), '[]')::jsonb as writers_names,
        COALESCE(json_agg(DISTINCT p.full_name)
          FILTER (WHERE pfw.role = 'director' AND p.id IS NOT NULL), '[]')::jsonb as directors_names,
        COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name))
          FILTER (WHERE pfw.role = 'actor' AND p.id IS NOT NULL), '[]'::jsonb) as actors,
        COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name))
          FILTER (WHERE pfw.role = 'writer' AND p.id IS NOT NULL), '[]'::jsonb) as writers,
        COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name))
          FILTER (WHERE pfw.role = 'director' AND p.id IS NOT NULL), '[]'::jsonb) as directors
    FROM content.film_work fw
    LEFT JOIN content.genre_film_work gfw ON fw.id = gfw.film_work_id
    LEFT JOIN content.genre g ON gfw.genre_id = g.id
    LEFT JOIN content.person_film_work pfw ON fw.id = pfw.film_work_id
    LEFT JOIN content.person p ON pfw.person_id = p.id
    WHERE fw.id > %s
    GROUP BY fw.id, fw.title, fw.description, fw.rating
    ORDER BY fw.id
    LIMIT %s
"""

RELATED_BY_ID_QUERY = """
    SELECT DISTINCT fw.id
    FROM content.film_work fw
    LEFT JOIN content.genre_film_work gfw ON fw.id = gfw.film_work_id
    LEFT JOIN content.genre g ON gfw.genre_id = g.id
    LEFT JOIN content.person_film_work pfw ON fw.id = pfw.film_work_id
    LEFT JOIN content.person p ON pfw.person_id = p.id
    WHERE g.id > %s OR p.id > %s
"""

BY_IDS_QUERY = """
    SELECT
        fw.id, fw.title, fw.description, fw.rating as imdb_rating,
        COALESCE(json_agg(DISTINCT g.name)
          FILTER (WHERE g.id IS NOT NULL), '[]')::jsonb as genres,
        COALESCE(json_agg(DISTINCT p.full_name)
          FILTER (WHERE pfw.role = 'actor' AND p.id IS NOT NULL), '[]')::jsonb as actors_names,
        COALESCE(json_agg(DISTINCT p.full_name)
          FILTER (WHERE pfw.role = 'writer' AND p.id IS NOT NULL), '[]')::jsonb as writers_names,
        COALESCE(json_agg(DISTINCT p.full_name)
          FILTER (WHERE pfw.role = 'director' AND p.id IS NOT NULL), '[]')::jsonb as directors_names,
        COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name))
          FILTER (WHERE pfw.role = 'actor' AND p.id IS NOT NULL), '[]'::jsonb) as actors,
        COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name))
          FILTER (WHERE pfw.role = 'writer' AND p.id IS NOT NULL), '[]'::jsonb) as writers,
        COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name))
          FILTER (WHERE pfw.role = 'director' AND p.id IS NOT NULL), '[]'::jsonb) as directors
    FROM content.film_work fw
    LEFT JOIN content.genre_film_work gfw ON fw.id = gfw.film_work_id
    LEFT JOIN content.genre g ON gfw.genre_id = g.id
    LEFT JOIN content.person_film_work pfw ON fw.id = pfw.film_work_id
    LEFT JOIN content.person p ON pfw.person_id = p.id
    WHERE fw.id = ANY(%s::uuid[])
    GROUP BY fw.id, fw.title, fw.description, fw.rating
"""


class PostgresExtractor:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _get_connection(self):
        conn = psycopg2.connect(self.dsn)
        conn.set_client_encoding("UTF8")
        return conn

    def fetch_main_batch(self, conn, last_film_id: str, limit: int) -> List[Dict[str, Any]]:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(MAIN_QUERY, (last_film_id, limit))
            return [dict(r) for r in cur.fetchall()]

    def fetch_affected_by_related_ids(self, conn, last_genre_id: str, last_person_id: str) -> List[str]:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(RELATED_BY_ID_QUERY, (last_genre_id, last_person_id))
            return [row["id"] for row in cur.fetchall()]

    def fetch_by_ids(self, conn, ids: List[str]) -> List[Dict[str, Any]]:
        if not ids: return []
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(BY_IDS_QUERY, (ids,))
            return [dict(r) for r in cur.fetchall()]
