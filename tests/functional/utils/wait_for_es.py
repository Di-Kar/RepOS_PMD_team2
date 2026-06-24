from pathlib import Path
import sys
import elasticsearch

from backoff import backoff
# Добавление пути к файлу настроек, т.к. запускается как скрипт, а не модуль
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.functional.settings import test_settings

@backoff(elasticsearch.ConnectionError)
def ping_elastic(client):
    if not client.ping():
        raise elasticsearch.ConnectionError("Elasticsearch don't response")
    return "Elastic is available."


if __name__ == '__main__':
    elastic_client = elasticsearch.Elasticsearch(
        hosts=test_settings.elastic_settings.get_host(),
        verify_certs=False,
        ssl_show_warn=False 
    )
    try:
        result = ping_elastic(elastic_client)
        print(result)
    except (elasticsearch.ConnectionError, TimeoutError) as e:
        print(e)
