from app.core import metrics


def test_histogram_records_observations():
    # Label value distinct from any real source name — the ingest tasks'
    # own tests (@timed("bom") etc.) share this same process-wide
    # registry, so a real source label would make this count-assertion
    # order-dependent across test files.
    before = (
        metrics.REGISTRY.get_sample_value(
            "ecolens_ingest_duration_seconds_count", {"source": "histogram_test"}
        )
        or 0.0
    )

    with metrics.ingest_duration_seconds.labels(source="histogram_test").time():
        pass

    after = metrics.REGISTRY.get_sample_value(
        "ecolens_ingest_duration_seconds_count", {"source": "histogram_test"}
    )
    assert after == before + 1.0


def test_ingest_failures_total_increments():
    metrics.ingest_failures_total.labels(source="aemo_nem").inc()

    text = metrics.metrics_as_text().decode()
    assert "ecolens_ingest_failures_total" in text


def test_latest_ingest_ts_records_a_timestamp():
    metrics.latest_ingest_ts.labels(source="bom").set(1_700_000_000)

    value = metrics.REGISTRY.get_sample_value(
        "ecolens_latest_ingest_timestamp_seconds", {"source": "bom"}
    )
    assert value == 1_700_000_000


def test_circuit_breaker_state_gauge_records_last_value():
    metrics.circuit_breaker_state.labels(source="bom").set(2)

    value = metrics.REGISTRY.get_sample_value(
        "ecolens_circuit_breaker_state", {"source": "bom"}
    )
    assert value == 2


def test_ingest_rows_total_increments():
    metrics.ingest_rows_total.labels(source="holidays").inc(5)

    text = metrics.metrics_as_text().decode()
    assert "ecolens_ingest_rows_total" in text


def test_ingest_runs_total_increments_by_outcome():
    metrics.ingest_runs_total.labels(source="aemo_wem", outcome="success").inc()

    value = metrics.REGISTRY.get_sample_value(
        "ecolens_ingest_runs_total", {"source": "aemo_wem", "outcome": "success"}
    )
    assert value == 1.0


def test_build_info_identifies_this_service():
    from app import __version__

    value = metrics.REGISTRY.get_sample_value(
        "ecolens_build_info", {"service": "ingestion", "version": __version__}
    )
    assert value == 1
