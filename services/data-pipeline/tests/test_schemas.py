from datetime import UTC, datetime

from app.schemas import (
    ComponentHealth,
    ForecastPoint,
    ForecastResponse,
    HealthResponse,
    IngestRunSummary,
    IngestTriggerResponse,
    MLflowHealth,
    OpsStatus,
    PromotionResponse,
    ReadyResponse,
)


def test_health_response_defaults_to_ok():
    assert HealthResponse().status == "ok"


def test_ready_response_aggregates_components():
    ready = ReadyResponse(
        status="not_ready",
        components=[
            ComponentHealth(name="postgres", healthy=True),
            ComponentHealth(name="redis", healthy=False, detail="timeout"),
        ],
    )
    assert ready.components[1].detail == "timeout"


def test_ops_status_defaults_last_ingest_to_empty_list():
    status = OpsStatus(db_healthy=True, mlflow=MLflowHealth(reachable=True))
    assert status.last_ingest == []


def test_ingest_trigger_response_reflects_actual_outcome():
    # No "started" default any more -- the endpoint runs inline and waits,
    # so by response time the real outcome (staged/success/failed) is known.
    resp = IngestTriggerResponse(source="bom", status="staged", rows_staged=288)
    assert resp.run_id is None
    assert resp.status == "staged"
    assert resp.rows_staged == 288


def test_ingest_run_summary_round_trips_via_json():
    summary = IngestRunSummary(
        run_id="r1",
        source="bom",
        status="success",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    payload = summary.model_dump_json()
    restored = IngestRunSummary.model_validate_json(payload)
    assert restored == summary


def test_forecast_response_holds_points():
    resp = ForecastResponse(
        region="NSW1",
        model="lstm_demand@production",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        horizon="24h",
        interval="30m",
        points=[
            ForecastPoint(ts=datetime(2026, 1, 1, tzinfo=UTC), p10=1, p50=2, p90=3),
        ],
    )
    assert resp.points[0].unit == "MW"


def test_promotion_response_requires_reason():
    resp = PromotionResponse(
        model_name="lstm_demand",
        promoted=False,
        candidate_version="3",
        candidate_mape=5.1,
        reason="candidate MAPE not strictly better",
    )
    assert resp.production_mape is None
