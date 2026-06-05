from django.http import HttpResponse
from django.http import JsonResponse
from django.db.models import F
from django.views.generic.detail import BaseDetailView
from django.contrib.postgres.aggregates import ArrayAgg
from django.views.generic.list import BaseListView

from movies.models import FilmWork, PersonFilmWork


class MoviesApiMixin:
    model = FilmWork
    http_method_names = ['get']

    def get_queryset(self):
        return FilmWork.objects.prefetch_related('genre','persons')

    def render_to_response(self, context, **response_kwargs):
        return JsonResponse(context)


class MoviesListApi(MoviesApiMixin, BaseListView):
    def get_context_data(self, *, object_list=None, **kwargs):
        queryset = self.get_queryset()
        self.paginate_by = 50
        paginator, page, page_queryset, is_paginated = self.paginate_queryset(queryset, self.paginate_by)

        serialized_films = []
        for film in page_queryset:
          
            persons_by_role = {}
            for pfw in film.personfilmwork_set.all(): 
                role = pfw.role
                if role not in persons_by_role:
                    persons_by_role[role] = []
                
                persons_by_role[role].append(pfw.person.full_name)

            serialized_films.append({
                'id': str(film.id),
                'title': film.title,
                'description': film.description or '',
                'rating': str(film.rating) if film.rating is not None else "0",
                'type' : film.type or '',
                'creation_date': film.creation_date.isoformat() if film.creation_date else None,
                'genres': list(film.genres.values_list('name', flat=True)),
            } | persons_by_role)
       
        data = {
               'count': paginator.count,
               'total_pages': paginator.num_pages,
               'prev': page.previous_page_number() if page.has_previous() else None,
               'next': page.next_page_number() if page.has_next() else None,
               'results': serialized_films,
        }
        return data


class MoviesDetailApi(MoviesApiMixin, BaseDetailView):
    def get_context_data(self, **kwargs):
        film = self.object 
        cast_qs = PersonFilmWork.objects.filter(film_work_id=film.id).values('role').annotate(
            persons=ArrayAgg(F('person__full_name'),distinct=True)
        )
        cast_dict = {row['role']: row['persons'] for row in cast_qs}
        data = {
            'id': str(film.id),
            'title': film.title,
            'description': film.description or '',
            'rating': str(film.rating) if film.rating is not None else "0",
            'creation_date': film.creation_date.isoformat() if film.creation_date else None,
            'type': film.type or '',
            'genres': list(film.genres.values_list('name', flat=True)),
        } | cast_dict
        return data # Словарь с данными объекта
