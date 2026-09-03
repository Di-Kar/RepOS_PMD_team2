import json
import os
import urllib.error
import urllib.request

from django.shortcuts import render
from django.views import View

ES_URL = 'http://{}:{}'.format(
    os.getenv('ES_HOST', 'localhost'),
    os.getenv('ES_PORT', '9200'),
)


class SearchView(View):
    http_method_names = ['get']

    def get(self, request):
        query = request.GET.get('q', '').strip()
        results = []
        error = None
        total = 0

        if query:
            try:
                results, total = self._search(query)
            except Exception as e:
                error = str(e)

        return render(
            request,
            'movies/search.html',
            {
                'query': query,
                'results': results,
                'total': total,
                'error': error,
            },
        )

    def _search(self, query: str):
        body = json.dumps(
            {
                'size': 20,
                'query': {
                    'multi_match': {
                        'query': query,
                        'fields': [
                            'title^3',
                            'description',
                            'actors_names',
                            'directors_names',
                            'writers_names',
                            'genres',
                        ],
                    }
                },
            }
        ).encode()

        req = urllib.request.Request(
            f'{ES_URL}/movies/_search',
            data=body,
            method='POST',
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        hits = data.get('hits', {})
        total = hits.get('total', {}).get('value', 0)
        results = [
            {**h['_source'], 'score': h.get('_score')} for h in hits.get('hits', [])
        ]
        return results, total
