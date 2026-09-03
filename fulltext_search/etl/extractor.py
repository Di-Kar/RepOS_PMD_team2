import logging
from typing import Generator, List, Tuple

import psycopg
from backoff_utils import backoff
from config import PostgresSettings
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Keyset pagination по (modified, id) для каждой из отслеживаемых таблиц.
# Условие (modified, id) > (%s, %s::uuid) гарантирует устойчивую пагинацию
# даже при одинаковых значениях modified у нескольких записей.
CHANGED_ENTITIES_SQL = {
    'film_work': """
        SELECT id, modified
        FROM content.film_work
        WHERE (modified, id) > (%s::timestamptz, %s::uuid)
        ORDER BY modified, id
        LIMIT %s
    """,
    'person': """
        SELECT id, modified
        FROM content.person
        WHERE (modified, id) > (%s::timestamptz, %s::uuid)
        ORDER BY modified, id
        LIMIT %s
    """,
    'genre': """
        SELECT id, modified
        FROM content.genre
        WHERE (modified, id) > (%s::timestamptz, %s::uuid)
        ORDER BY modified, id
        LIMIT %s
    """,
}

FILM_IDS_FOR_PERSONS_SQL = """
    SELECT DISTINCT fw.id
    FROM content.film_work fw
    JOIN content.person_film_work pfw ON pfw.film_work_id = fw.id
    WHERE pfw.person_id = ANY(%s)
"""

FILM_IDS_FOR_GENRES_SQL = """
    SELECT DISTINCT fw.id
    FROM content.film_work fw
    JOIN content.genre_film_work gfw ON gfw.film_work_id = fw.id
    WHERE gfw.genre_id = ANY(%s)
"""

GENRES_SQL = """
    SELECT id, name, description, modified
    FROM content.genre
    WHERE (modified, id) > (%s::timestamptz, %s::uuid)
    ORDER BY modified, id
    LIMIT %s
"""

PERSONS_SQL = """
    SELECT id, full_name, modified
    FROM content.person
    WHERE (modified, id) > (%s::timestamptz, %s::uuid)
    ORDER BY modified, id
    LIMIT %s
"""

PERSON_FILM_ROLES_SQL = """
    SELECT person_id, film_work_id, role
    FROM content.person_film_work
    WHERE person_id = ANY(%s)
"""

FILM_DETAILS_SQL = """
    SELECT
        fw.id,
        fw.title,
        fw.description,
        fw.rating AS imdb_rating,
        COALESCE(
            JSON_AGG(DISTINCT jsonb_build_object('id', g.id::text, 'name', g.name))
            FILTER (WHERE g.id IS NOT NULL),
            '[]'
        ) AS genres,
        COALESCE(
            JSON_AGG(DISTINCT jsonb_build_object('id', p.id::text, 'name', p.full_name))
            FILTER (WHERE p.id IS NOT NULL AND pfw.role = 'director'),
            '[]'
        ) AS directors,
        COALESCE(
            JSON_AGG(DISTINCT jsonb_build_object('id', p.id::text, 'name', p.full_name))
            FILTER (WHERE p.id IS NOT NULL AND pfw.role = 'actor'),
            '[]'
        ) AS actors,
        COALESCE(
            JSON_AGG(DISTINCT jsonb_build_object('id', p.id::text, 'name', p.full_name))
            FILTER (WHERE p.id IS NOT NULL AND pfw.role = 'writer'),
            '[]'
        ) AS writers
    FROM content.film_work fw
    LEFT JOIN content.genre_film_work gfw ON gfw.film_work_id = fw.id
    LEFT JOIN content.genre g ON g.id = gfw.genre_id
    LEFT JOIN content.person_film_work pfw ON pfw.film_work_id = fw.id
    LEFT JOIN content.person p ON p.id = pfw.person_id
    WHERE fw.id = ANY(%s)
    GROUP BY fw.id
"""


class PostgresExtractor:
    def __init__(self, settings: PostgresSettings):
        self.settings = settings
        self._conn = None

    @backoff(exceptions=(psycopg.OperationalError, psycopg.DatabaseError))
    def _get_connection(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                host=self.settings.host,
                port=self.settings.port,
                dbname=self.settings.dbname,
                user=self.settings.user,
                password=self.settings.password,
                row_factory=dict_row,
            )
            logger.info('Подключено к PostgreSQL')
        return self._conn

    def _reset_connection(self) -> None:
        """Закрывает соединение, чтобы следующая попытка создала новое."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def fetch_batches(
        self,
        table: str,
        cursor_modified: str,
        cursor_id: str,
        batch_size: int,
    ) -> Generator[Tuple[List[str], str, str], None, None]:
        """Генерирует тройки (film_ids, new_cursor_modified, new_cursor_id).

        Курсор продвигается по (modified, id) изменившихся сущностей.
        Для person/genre дополнительно находит связанные film_work.
        """
        sql = CHANGED_ENTITIES_SQL[table]
        while True:
            rows = self._execute(sql, (cursor_modified, cursor_id, batch_size))
            if not rows:
                break

            cursor_modified = rows[-1]['modified'].isoformat()
            cursor_id = str(rows[-1]['id'])

            if table == 'film_work':
                film_ids = [str(row['id']) for row in rows]
            elif table == 'person':
                entity_ids = [row['id'] for row in rows]
                film_rows = self._execute(FILM_IDS_FOR_PERSONS_SQL, (entity_ids,))
                film_ids = [str(row['id']) for row in film_rows]
            else:
                entity_ids = [row['id'] for row in rows]
                film_rows = self._execute(FILM_IDS_FOR_GENRES_SQL, (entity_ids,))
                film_ids = [str(row['id']) for row in film_rows]

            yield film_ids, cursor_modified, cursor_id

            if len(rows) < batch_size:
                break

    def fetch_genres_batches(
        self,
        cursor_modified: str,
        cursor_id: str,
        batch_size: int,
    ) -> Generator[Tuple[List[dict], str, str], None, None]:
        """Генерирует тройки (genre_rows, new_cursor_modified, new_cursor_id)."""
        while True:
            rows = self._execute(GENRES_SQL, (cursor_modified, cursor_id, batch_size))
            if not rows:
                break

            cursor_modified = rows[-1]['modified'].isoformat()
            cursor_id = str(rows[-1]['id'])

            yield rows, cursor_modified, cursor_id

            if len(rows) < batch_size:
                break

    def fetch_persons_batches(
        self,
        cursor_modified: str,
        cursor_id: str,
        batch_size: int,
    ) -> Generator[Tuple[List[dict], str, str], None, None]:
        """Генерирует тройки (person_rows, new_cursor_modified, new_cursor_id)."""
        while True:
            rows = self._execute(PERSONS_SQL, (cursor_modified, cursor_id, batch_size))
            if not rows:
                break

            cursor_modified = rows[-1]['modified'].isoformat()
            cursor_id = str(rows[-1]['id'])

            yield rows, cursor_modified, cursor_id

            if len(rows) < batch_size:
                break

    def fetch_person_film_roles(self, person_ids: List[str]) -> List[dict]:
        """Возвращает строки (person_id, film_work_id, role) для списка персон."""
        return self._execute(PERSON_FILM_ROLES_SQL, (person_ids,))

    def fetch_film_details(self, film_ids: List[str]) -> List[dict]:
        """Возвращает полные данные фильмов по списку ID."""
        return self._execute(FILM_DETAILS_SQL, (film_ids,))

    @backoff(exceptions=(psycopg.OperationalError, psycopg.DatabaseError))
    def _execute(self, sql: str, params: tuple) -> List[dict]:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        except (psycopg.OperationalError, psycopg.DatabaseError):
            # Сбрасываем соединение: транзакция могла остаться в сломанном состоянии.
            self._reset_connection()
            raise
