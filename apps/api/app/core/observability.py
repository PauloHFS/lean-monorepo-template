"""OpenTelemetry + Sentry opcional.

Ativado quando `OTEL_EXPORTER_OTLP_ENDPOINT` ou `SENTRY_DSN` estão setados.
Sem env, é no-op — não custa nada.

Decisão: vendor-agnostic no app. Quem roteia OTLP pro vendor (Grafana Tempo,
Honeycomb, Datadog, etc.) é o operador.
"""
from __future__ import annotations

import os

from app.core.config import settings

_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
_SENTRY_DSN = os.environ.get("SENTRY_DSN")


def setup_observability(app) -> None:
    """Inicializa tracing/metrics se `OTEL_EXPORTER_OTLP_ENDPOINT` estiver setado."""
    if not _OTLP_ENDPOINT:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({SERVICE_NAME: settings.app_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_OTLP_ENDPOINT)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    LoggingInstrumentor().instrument(set_logging_format=False)

    from app.db.session import engine
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    from app.core.logging import get_logger
    get_logger("otel").info("tracing inicializado", endpoint=_OTLP_ENDPOINT)


def setup_sentry() -> None:
    """Inicializa Sentry se DSN setado."""
    if not _SENTRY_DSN:
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=settings.app_env,
        release=f"{settings.app_name}@{settings.app_version}",
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
        ],
        # Profiling: custa CPU, deixa off por padrão
        profiles_sample_rate=0.0,
        traces_sample_rate=1.0,
    )