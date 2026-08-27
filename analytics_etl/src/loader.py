"""Загрузчик ClickHouse с логикой повторных попыток (backoff)."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import clickhouse_connect
from clickhouse_connect.driver.exceptions import DatabaseError, OperationalError
from backoff_utils import backoff
from config import clickhouse_settings, etl_settings

if TYPE_CHECKING:
    from clickhouse_connect.driver.client import Client

logger = logging.getLogger(__name__)

_CLICKHOUSE_EXCEPTIONS = (DatabaseError, OperationalError, ConnectionError, TimeoutError)


class ClickHouseLoader:
    """Обрабатывает все взаимодействия с ClickHouse.

    Использует клиент ``clickhouse-connect`` с пакетными вставками и
    экспоненциальной задержкой при временных сбоях.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        self.host = host or clickhouse_settings.host
        self.port = port or clickhouse_settings.port
        self.database = database or clickhouse_settings.database
        self.user = user or clickhouse_settings.user
        self.password = password or clickhouse_settings.password
        self._client: Client | None = None

    def _get_client(self) -> Client:
        """Лениво инициализировать клиент ClickHouse."""
        if self._client is None:
            try:
                self._client = clickhouse_connect.get_client(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    username=self.user,
                    password=self.password,
                    connect_timeout=10,
                    send_receive_timeout=30,
                )
                logger.info(
                    'Подключено к ClickHouse на %s:%d, база данных=%s',
                    self.host, self.port, self.database,
                )
            except Exception as e:
                logger.error('Не удалось подключиться к ClickHouse: %s', e)
                raise
        return self._client

    # ------------------------------------------------------------------ #
    #  Инициализация схемы                                                     #
    # ------------------------------------------------------------------ #

    def ensure_database_exists(self) -> None:
        """Создать базу данных аналитики, если она не существует."""
        # Подключаемся к БД по умолчанию, чтобы создать нужную БД
        temp_client = clickhouse_connect.get_client(
            host=self.host,
            port=self.port,
            database='default',
            username=self.user,
            password=self.password,
            connect_timeout=10,
        )
        try:
            temp_client.command(f'CREATE DATABASE IF NOT EXISTS {self.database}')
        finally:
            temp_client.close()
        logger.info('База данных %s готова', self.database)
        # Переподключаемся к созданной БД
        self._client = None

    def execute_query(self, query: str, params: Any | None = None) -> None:
        """Выполнить запрос (DDL схемы, метаданные и т.д.)."""
        client = self._get_client()
        client.command(query, params)

    def init_schema(self, schema_file: str) -> None:
        """Выполнить все операторы CREATE TABLE из SQL-файла."""
        logger.info('Попытка инициализации схемы из %s', schema_file)
        import os
        if not os.path.exists(schema_file):
            logger.error('Файл схемы не найден: %s (cwd=%s, file=%s)', schema_file, os.getcwd(), os.path.dirname(__file__))
            raise FileNotFoundError(f'Файл схемы не найден: {schema_file}')
        client = self._get_client()
        try:
            with open(schema_file, 'r', encoding='utf-8') as f:
                sql = f.read()
            statements = sql.split(';')
            logger.info('Найдено %d операторов (разделено по ;)', len(statements))
            for i, statement in enumerate(statements):
                statement = statement.strip()
                logger.info('Оператор #%d (len=%d, repr=%s)', i, len(statement), repr(statement[:80]))
                if statement and ('CREATE TABLE' in statement.upper()):
                    logger.info('Выполняю CREATE TABLE #%d: %s', i, statement[:100])
                    client.command(statement)
                    logger.info('Выполнено: %s', statement[:80])
        except FileNotFoundError:
            logger.error('Файл схемы не найден: %s', schema_file)
            raise
        except Exception as e:
            logger.error('Ошибка инициализации схемы: %s', e)
            raise

    # ------------------------------------------------------------------ #
    #  Пакетные вставки (обёрнутые backoff)                                      #
    # ------------------------------------------------------------------ #

    @backoff(exceptions=_CLICKHOUSE_EXCEPTIONS)
    def bulk_insert(self, table: str, rows: List[dict]) -> bool:
        """Вставить пакет строк в указанную таблицу.

        Возвращает true при успехе, false если пакет пустой.
        """
        if not rows:
            return True

        client = self._get_client()
        columns = list(rows[0].keys())
        data = [[row.get(col) for col in columns] for row in rows]

        client.insert(
            table,
            data,
            column_names=columns,
            database=self.database,
        )
        logger.info('Вставлено %d строк в %s.%s', len(rows), self.database, table)
        return True

    @backoff(exceptions=_CLICKHOUSE_EXCEPTIONS)
    def bulk_insert_movies_metrics(self, rows: List[dict]) -> bool:
        """Вставить агрегированные строки метрик фильмов.

        Использует специализированный запрос merge для семантики SummingMergeTree.
        """
        if not rows:
            return True

        client = self._get_client()

        aggregated: Dict[str, dict] = {}
        for row in rows:
            cid = row['content_id']
            if cid not in aggregated:
                aggregated[cid] = {
                    'content_id': cid,
                    'total_views': 0,
                    'total_watch_sessions': 0,
                    'completions': 0,
                    'total_duration_ms': 0,
                    'unique_users': set(),
                    'last_viewed_at': row.get('occurred_at', ''),
                }
            agg = aggregated[cid]
            if row.get('is_quality_change'):
                agg['total_watch_sessions'] += 1
            if row.get('is_watch_complete'):
                agg['completions'] += 1
                agg['total_watch_sessions'] += 1
            agg['unique_users'].add(row.get('user_id'))
            agg['total_views'] += 1
            agg['last_viewed_at'] = max(agg['last_viewed_at'], row.get('occurred_at', ''))

        ch_rows = []
        for _cid, agg in aggregated.items(): # B007[ruff] Loop control variable `cid` not used within loop body
            ch_rows.append({
                'content_id': agg['content_id'],
                'total_views': agg['total_views'],
                'total_watch_sessions': agg['total_watch_sessions'],
                'completions': agg['completions'],
                'total_duration_ms': agg.get('total_duration_ms', 0),
                'unique_viewers': len(agg['unique_users']),
                'last_viewed_at': agg['last_viewed_at'],
                'updated_at': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()),
            })

        if ch_rows:
            columns = list(ch_rows[0].keys())
            data = [[row.get(col) for col in columns] for row in ch_rows]
            client.insert(
                'movies_metrics',
                data,
                column_names=columns,
                database=self.database,
            )
            logger.info('Вставлено %d строк метрик фильмов', len(ch_rows))

        return True

    @backoff(exceptions=_CLICKHOUSE_EXCEPTIONS)
    def bulk_insert_watch_sessions(self, rows: List[dict]) -> bool:
        """Вставить строки сеансов просмотра в таблицу watch_sessions."""
        if not rows:
            return True

        client = self._get_client()
        columns = list(rows[0].keys())
        data = [[row.get(col) for col in columns] for row in rows]

        client.insert(
            'watch_sessions',
            data,
            column_names=columns,
            database=self.database,
        )
        logger.info('Вставлено %d строк сеансов просмотра', len(rows))
        return True

    @backoff(exceptions=_CLICKHOUSE_EXCEPTIONS)
    def execute_ddl(self, query: str) -> None:
        """Выполнить DDL-запрос."""
        client = self._get_client()
        client.command(query)

    def close(self) -> None:
        """Закрыть основное соединение с ClickHouse."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.exception('Ошибка при закрытии клиента ClickHouse')
            finally:
                self._client = None
            logger.info('Соединение с ClickHouse закрыто')
