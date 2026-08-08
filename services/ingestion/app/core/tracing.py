"""OpenTelemetry tracing setup (`TODO.md` Observability Phase 1's
"OpenTelemetry Core SDK Integration") -- same real-no-op-when-disabled
design as `services/waerehouse`/`services/forecast-api`'s identical
modules (batched OTLP export to `services/observility`'s Collector,
never straight to Tempo; a real no-op when `Settings.otel_traces_enabled`
is `False`, the default).

The 3rd of 3 business services to gain this -- see each module's own
docstring for what it instruments: `pipeline.tasks._common.standard_run`
(the run-start/fetch/anomaly-scan/stage/publish lifecycle every ingest
task shares) here, `sync_landed_event`/`run_build` in waerehouse,
`get_forecast`/`check_drift` in forecast-api.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from app.core.config import get_settings

_SERVICE_NAME = "ingestion"
_configured = False


def configure_tracing() -> None:
    """Call once, at process startup (`app.main`'s lifespan, `app.cli`'s
    `main()` group callback, and `app.celery_app`'s `worker_process_init`
    signal -- Celery forks worker processes, so each one needs its own
    call, same as it needs its own event loop) -- idempotent."""
    global _configured
    if _configured:
        return
    settings = get_settings()
    if not settings.otel_traces_enabled:
        # No log line here, deliberately -- see `services/waerehouse`'s
        # identical module for why (this runs ahead of every CLI
        # subcommand too; logging on every invocation would be noise and
        # could break anything parsing a command's stdout as JSON, e.g.
        # `ecolens-ingestion health`).
        _configured = True
        return

    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: _SERVICE_NAME})
    )
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer() -> Tracer:
    """A real no-op tracer if `configure_tracing()` was never called or
    tracing is disabled -- every call site can use this unconditionally."""
    return trace.get_tracer(_SERVICE_NAME)
