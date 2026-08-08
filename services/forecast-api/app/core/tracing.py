"""OpenTelemetry tracing setup (`TODO.md` Forecasting Phase 7's
"OpenTelemetry Instrumentation": "Instrument model execution routines,
inference latency, drift metrics, and error rates with OpenTelemetry
traces"). Same real-no-op-when-disabled design as `services/waerehouse`'s
identical module -- see that one's own docstring for the full reasoning
(batched OTLP export to `services/observility`'s Collector, never
straight to Tempo; a real no-op when `Settings.otel_traces_enabled` is
`False`, the default).
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_SERVICE_NAME = "forecast-api"
_configured = False


def configure_tracing() -> None:
    """Call once, at process startup (`app.main`'s lifespan, and the
    CLI's `main()` group callback for training/tuning/evaluation
    commands run outside the API process) -- idempotent."""
    global _configured
    if _configured:
        return
    settings = get_settings()
    if not settings.otel_traces_enabled:
        # No log line here, deliberately -- see `services/waerehouse`'s
        # identical module for why (this runs ahead of every CLI
        # subcommand too; logging on every invocation would be noise and
        # could break anything parsing a command's stdout as JSON).
        _configured = True
        return

    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: _SERVICE_NAME})
    )
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True
    log.info("tracing.enabled", endpoint=settings.otel_exporter_otlp_endpoint)


def get_tracer() -> Tracer:
    """A real no-op tracer if `configure_tracing()` was never called or
    tracing is disabled -- every call site can use this unconditionally."""
    return trace.get_tracer(_SERVICE_NAME)
