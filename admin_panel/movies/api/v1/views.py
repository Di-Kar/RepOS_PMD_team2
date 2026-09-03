from django.contrib.postgres.aggregates import ArrayAgg
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.views import View

from movies.models import FilmWork, Roles

from .serializers import serialize_film


class MoviesApiMixin(View):
    model = FilmWork
    http_method_names = ['get']

    def get_queryset(self):
        return self.model.objects.annotate(
            genres_list=ArrayAgg('genres__name', distinct=True),
            actors=ArrayAgg(
                'persons__full_name',
                filter=Q(personfilmwork__role=Roles.ACTOR),
                distinct=True,
            ),
            directors=ArrayAgg(
                'persons__full_name',
                filter=Q(personfilmwork__role=Roles.DIRECTOR),
                distinct=True,
            ),
            writers=ArrayAgg(
                'persons__full_name',
                filter=Q(personfilmwork__role=Roles.WRITER),
                distinct=True,
            ),
        )

    def render_to_response(self, context):
        return JsonResponse(context)


class MoviesListApi(MoviesApiMixin):
    page_size = 50

    def get(self, request, *args, **kwargs):
        paginator = Paginator(self.get_queryset(), self.page_size)
        paginator.__dict__['count'] = FilmWork.objects.count()
        page_number = request.GET.get('page', 1)
        if page_number == 'last':
            page_number = paginator.num_pages
        try:
            page = paginator.page(page_number)
        except PageNotAnInteger:
            page = paginator.page(1)
        except EmptyPage:
            return JsonResponse({'detail': 'Page not found.'}, status=404)

        return self.render_to_response(
            {
                'count': paginator.count,
                'total_pages': paginator.num_pages,
                'prev': page.previous_page_number() if page.has_previous() else None,
                'next': page.next_page_number() if page.has_next() else None,
                'results': [serialize_film(f) for f in page.object_list],
            }
        )


class MoviesDetailApi(MoviesApiMixin):
    def get(self, request, pk, *args, **kwargs):
        try:
            film = self.get_queryset().get(id=pk)
        except FilmWork.DoesNotExist:
            return JsonResponse({'detail': 'Not found.'}, status=404)

        return self.render_to_response(serialize_film(film))
