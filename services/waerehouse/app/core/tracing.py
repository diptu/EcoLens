"""OpenTelemetry tracing setup (`TODO.md` Phase 6's "OpenTelemetry
Tracing": "Instrument the warehouse event consumer and dbt execution
wrapper to emit distributed traces for sync latency and transformation
run times").

`configure_tracing()` is a real no-op when `Settings.otel_traces_enabled`
is `False` (the default) -- this service works exactly as before if an
operator hasn't set up `services/observility`'s OTel Collector, same
"optional infra, real no-op when absent" pattern `object_storage_
configured`/R2 already establishes here. When enabled, spans batch-export
via OTLP grpc to that collector's `:4317` receiver (`Settings.
otel_exporter_otlp_endpoint`) -- never Tempo directly, and never
synchronously on the request/consume path: `BatchSpanProcessor` buffers
and exports on its own background thread, so a slow/unreachable
collector can't add latency to a real `dbt build` or RabbitMQ message
handling (`TODO.md` Phase 6's own "Asynchronous Transport Verification"
item).

`get_tracer()` returns a real no-op tracer (`opentelemetry.trace`'s own
built-in default, not something this module has to fake) when tracing
was never configured -- every `with get_tracer().start_as_current_span(
...)` call site works identically either way, the only difference is
whether anything real gets exported.
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

_SERVICE_NAME = "warehouse"
_configured = False


def configure_tracing() -> None:
    """Call once, at process startup (`app.main`'s lifespan, and the
    `consume`/`dbt` CLI commands' own entrypoints) -- idempotent, a
    second call is a no-op rather than registering a duplicate
    processor/provider."""
    global _configured
    if _configured:
        return
    settings = get_settings()
    if not settings.otel_traces_enabled:
        # Deliberately no log line here -- disabled is this setting's
        # default, and logging it on every single CLI invocation (this
        # runs from the `main()` group callback, ahead of every
        # subcommand) would be pure noise, and would break anything
        # that parses a command's stdout as a single JSON object (e.g.
        # `ecolens-warehouse health`'s own test).
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
