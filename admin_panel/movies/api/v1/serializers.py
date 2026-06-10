def serialize_film(film) -> dict:
    return {
        'id': str(film.id),
        'title': film.title,
        'description': film.description,
        'creation_date': film.creation_date.isoformat() if film.creation_date else None,
        'rating': film.rating,
        'type': film.type,
        'genres': film.genres_list or [],
        'actors': film.actors or [],
        'directors': film.directors or [],
        'writers': film.writers or [],
    }
