import clickhouse_connect

client = clickhouse_connect.get_client(
        host='localhost',
        port=8123,
        database='analytics',
        username='default',
        password='secret',
    )

query = f'SELECT count() FROM events WHERE event_type = \'click\' AND event_id=\'click-test-06c508aa\''
    

result = client.query(query)
rows = result.result_rows

print(rows)

client.close()