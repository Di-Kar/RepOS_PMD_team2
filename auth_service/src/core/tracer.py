"""Модуль инициализации OpenTelemetry-трассировки."""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from src.core.config import settings

logger = logging.getLogger('jaeger')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    logger.addHandler(handler)

def configure_tracer(debug: bool = False) -> None:
    """
    Настраивает OpenTelemetry-трассировку.

    Args:
        debug: Если True, добавляется ConsoleSpanExporter (для локальной отладки).
    """
    resource = Resource.create(attributes={
        SERVICE_NAME: "auth_service"
    })
    # Установка провайдера трассировки
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    # Добавляем OTLP-экспортер только если jaeger_endpoint задан
    jaeger_ep = settings.jaeger_endpoint
    if jaeger_ep and jaeger_ep.strip():
        try:
            # Настройка экспортера Jaeger (используется OTLP HTTP по умолчанию на порт 4318)
            jaeger_exporter = OTLPSpanExporter(
                endpoint=jaeger_ep.strip(),
            )
            tracer_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
            logger.info(f"OTLP-экспортер настроен: {jaeger_ep}")
        except Exception as e:
            logger.warning(
                f"Не удалось настроить OTLP-экспортер (Jaeger недоступен?): "
                f"{jaeger_ep}. Продолжаем без трассировки. Ошибка: {e}"
            )

    # Чтобы видеть трейсы в консоли только для debug-режима
    if debug:
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.debug("Debug-режим включён — консольный экспорт включён")
    
    # Включение TraceContextTextMapPropagator для поддержки w3c trace-context
    set_global_textmap(TraceContextTextMapPropagator())
    
