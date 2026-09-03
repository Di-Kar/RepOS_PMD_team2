import json
import logging
from collections import defaultdict
from typing import List

from models import Genre, GenreShort, Movie, Person, PersonFilm, PersonShort

logger = logging.getLogger(__name__)


class DataTransformer:
    def transform(self, raw_rows: List[dict]) -> List[Movie]:
        movies = []
        for row in raw_rows:
            try:
                directors = self._parse_persons(row.get('directors', '[]'))
                actors = self._parse_persons(row.get('actors', '[]'))
                writers = self._parse_persons(row.get('writers', '[]'))
                genres = self._parse_genres(row.get('genres', '[]'))

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

    def transform_genres(self, raw_rows: List[dict]) -> List[Genre]:
        genres = []
        for row in raw_rows:
            try:
                genres.append(
                    Genre(
                        id=row['id'],
                        name=row['name'],
                        description=row.get('description'),
                    )
                )
            except Exception as e:
                logger.error('Ошибка валидации жанра id=%s: %s', row.get('id'), e)
        return genres

    def transform_persons(
        self, raw_rows: List[dict], film_roles: List[dict]
    ) -> List[Person]:
        # person_id -> film_work_id -> {roles}
        films_by_person: dict = defaultdict(lambda: defaultdict(set))
        for row in film_roles:
            films_by_person[row['person_id']][row['film_work_id']].add(row['role'])

        persons = []
        for row in raw_rows:
            try:
                films = [
                    PersonFilm(uuid=film_id, roles=sorted(roles))
                    for film_id, roles in films_by_person.get(row['id'], {}).items()
                ]
                persons.append(
                    Person(
                        id=row['id'],
                        full_name=row['full_name'],
                        films=films,
                    )
                )
            except Exception as e:
                logger.error('Ошибка валидации персоны id=%s: %s', row.get('id'), e)
        return persons

    @staticmethod
    def _parse_persons(value) -> List[PersonShort]:
        if isinstance(value, str):
            value = json.loads(value)
        if not value:
            return []
        return [PersonShort(id=p['id'], name=p['name']) for p in value if p]

    @staticmethod
    def _parse_genres(value) -> List[GenreShort]:
        if isinstance(value, str):
            value = json.loads(value)
        if not value:
            return []
        return [GenreShort(id=g['id'], name=g['name']) for g in value if g]
