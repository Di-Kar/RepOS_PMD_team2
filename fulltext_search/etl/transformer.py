import json
import logging
from typing import List
from models import Movie, PersonShort

logger = logging.getLogger(__name__)


class DataTransformer:
    def transform(self, raw_rows: List[dict]) -> List[Movie]:
        movies = []
        for row in raw_rows:
            try:
                directors = self._parse_persons(row.get('directors', '[]'))
                actors = self._parse_persons(row.get('actors', '[]'))
                writers = self._parse_persons(row.get('writers', '[]'))
                genres = self._parse_list(row.get('genres', '[]'))

                movie = Movie(
                    id=row['id'],
                    imdb_rating=row.get('imdb_rating'),
                    genres=genres,
                    title=row['title'],
                    description=row.get('description'),
                    directors_names=[p.name for p in directors],
                    actors_names=[p.name for p in actors],
                    writers_names=[p.name for p in writers],
                    directors=directors,
                    actors=actors,
                    writers=writers,
                )
                movies.append(movie)
            except Exception as e:
                logger.error('Ошибка валидации записи id=%s: %s', row.get('id'), e)
        return movies

    @staticmethod
    def _parse_persons(value) -> List[PersonShort]:
        if isinstance(value, str):
            value = json.loads(value)
        if not value:
            return []
        return [PersonShort(id=p['id'], name=p['name']) for p in value if p]

    @staticmethod
    def _parse_list(value) -> List[str]:
        if isinstance(value, str):
            value = json.loads(value)
        return [v for v in (value or []) if v is not None]
