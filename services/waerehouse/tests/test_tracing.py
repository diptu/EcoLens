from __future__ import annotations

import pytest

from app.core import tracing


@pytest.fixture(autouse=True)
def _reset_configured_flag():
    """`configure_tracing()`'s own `_configured` module-level guard would
    otherwise make every test after the first a no-op -- reset it so
    each test in this file starts from a clean slate. Doesn't touch
    OpenTelemetry's own global tracer provider (that's a genuinely
    process-wide, set-once-only piece of state by OTel's own design --
    not something a single service's tests should be fighting with)."""
    tracing._configured = False
    yield
    tracing._configured = False


def test_disabled_by_default(monkeypatch):
    settings = tracing.get_settings()
    assert settings.otel_traces_enabled is False


def test_configure_tracing_is_a_real_noop_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tracing, "OTLPSpanExporter", lambda **kw: calls.append(kw) or object()
    )

    tracing.configure_tracing()

    assert calls == []
    assert tracing._configured is True


class _FakeProvider:
    """Stands in for a real `TracerProvider` -- avoids ever constructing
    one with a fake (non-OTel) processor/exporter, which would otherwise
    blow up at real interpreter-exit time (`TracerProvider.shutdown()`
    calling `.shutdown()` on whatever fake processor object was added)."""

    def add_span_processor(self, processor):
        pass


def test_configure_tracing_is_idempotent(monkeypatch):
    calls = []
    monkeypatch.setattr(tracing.get_settings(), "otel_traces_enabled", True)
    monkeypatch.setattr(
        tracing, "OTLPSpanExporter", lambda **kw: calls.append(kw) or object()
    )
    monkeypatch.setattr(tracing, "BatchSpanProcessor", lambda exporter: object())
    monkeypatch.setattr(tracing, "TracerProvider", lambda **kw: _FakeProvider())
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", lambda provider: None)

    tracing.configure_tracing()
    tracing.configure_tracing()

    # The exporter is only ever constructed once -- a second call is a
    # true no-op, not a duplicate provider/processor registration.
    assert len(calls) == 1


def test_configure_tracing_builds_the_exporter_with_the_configured_endpoint(
    monkeypatch,
):
    captured = {}
    monkeypatch.setattr(tracing.get_settings(), "otel_traces_enabled", True)
    monkeypatch.setattr(
        tracing.get_settings(),
        "otel_exporter_otlp_endpoint",
        "http://collector.internal:4317",
    )

    def fake_exporter(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(tracing, "OTLPSpanExporter", fake_exporter)
    monkeypatch.setattr(tracing, "BatchSpanProcessor", lambda exporter: object())
    monkeypatch.setattr(tracing, "TracerProvider", lambda **kw: _FakeProvider())
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", lambda provider: None)

    tracing.configure_tracing()

    assert captured["endpoint"] == "http://collector.internal:4317"


def test_get_tracer_returns_a_usable_tracer_even_when_never_configured():
    """The whole point of `get_tracer()` -- every call site
    (`consumers.landed_events`, `dbt.scheduler`) can use it
    unconditionally, before or after `configure_tracing()` ever runs."""
    tracer = tracing.get_tracer()

    with tracer.start_as_current_span("test.span") as span:
        span.set_attribute("k", "v")  # must not raise
