"""Root TODO.md's "Anomaly Detection" section: deterministic, per-record
rule checks -- the half of the hybrid detector that needs no model and
no history, just this one record (plus, for the sudden-jump check, the
immediately preceding record for the same entity within the same
ingest batch).

Three families, one function each, all dispatched by `evaluate_rules()`:
  - physical-range violations (source-specific: AEMO price cap/floor +
    negative/jumpy demand; BoM temp/humidity/wind-speed ranges)
  - completeness (a record missing one of its source's expected metrics)
  - staleness (`fetched_at - ts` far larger than the source's normal
    publish lag)

Deliberately *not* rule-based here: a whole source going silent (zero
records this run) is `warehouse/service/freshness.py`'s
`SourceFreshnessChecker`'s job already; duplicating it as a per-record
rule would just be a second, driftable copy of the same check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ecolens.ingestion.core.settings import IngestionSettings, get_ingestion_settings

_ENERGY_SOURCES = ("aemo_nem", "aemo_wem", "openelectricity")


@dataclass(frozen=True)
class RuleResult:
    fired: bool
    flag: str
    detail: str


def _as_datetime(value: Any) -> datetime | None:
    """Some sources land `ts`/`fetched_at` as an ISO string rather than a
    native `datetime` (e.g. OpenElectricity's `ts`, same quirk
    `raw_sync.py`'s `_coerce` already works around) -- normalize both
    shapes to a tz-aware `datetime` so the staleness subtraction below is
    always comparing like with like.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _price_range(doc: dict[str, Any], settings: IngestionSettings) -> RuleResult:
    price = doc.get("price_mwh")
    if price is None:
        return RuleResult(False, "rule:price_out_of_range", "")
    if price > settings.anomaly_price_cap:
        return RuleResult(
            True,
            "rule:price_above_cap",
            f"price_mwh={price:g} exceeds the market price cap "
            f"({settings.anomaly_price_cap:g})",
        )
    if price < settings.anomaly_price_floor:
        return RuleResult(
            True,
            "rule:price_below_floor",
            f"price_mwh={price:g} is below the market price floor "
            f"({settings.anomaly_price_floor:g})",
        )
    return RuleResult(False, "rule:price_out_of_range", "")


def _demand_negative(doc: dict[str, Any], settings: IngestionSettings) -> RuleResult:
    demand = doc.get("demand_mw")
    if demand is not None and demand < 0:
        return RuleResult(
            True, "rule:demand_negative", f"demand_mw={demand:g} is negative"
        )
    return RuleResult(False, "rule:demand_negative", "")


def _demand_sudden_jump(
    doc: dict[str, Any], prev_doc: dict[str, Any] | None, settings: IngestionSettings
) -> RuleResult:
    """`prev_doc`: the immediately preceding record for the *same
    entity* (region/network_code) within this batch, chronologically --
    the caller (`scorer.py`) is responsible for sorting/grouping the
    batch correctly before calling this; this function just compares
    whatever two docs it's handed.
    """
    if prev_doc is None:
        return RuleResult(False, "rule:demand_sudden_jump", "")
    demand = doc.get("demand_mw")
    prev_demand = prev_doc.get("demand_mw")
    if demand is None or prev_demand is None or prev_demand == 0:
        return RuleResult(False, "rule:demand_sudden_jump", "")
    fraction = abs(demand - prev_demand) / abs(prev_demand)
    if fraction > settings.anomaly_demand_jump_fraction:
        return RuleResult(
            True,
            "rule:demand_sudden_jump",
            f"demand_mw jumped {fraction:.0%} vs. the previous interval "
            f"({prev_demand:g} -> {demand:g})",
        )
    return RuleResult(False, "rule:demand_sudden_jump", "")


def _bom_ranges(doc: dict[str, Any], settings: IngestionSettings) -> list[RuleResult]:
    results: list[RuleResult] = []
    temp = doc.get("temp_c")
    if temp is not None and not (
        settings.anomaly_bom_temp_min_c <= temp <= settings.anomaly_bom_temp_max_c
    ):
        results.append(
            RuleResult(
                True,
                "rule:temp_out_of_range",
                f"temp_c={temp:g} outside plausible range "
                f"[{settings.anomaly_bom_temp_min_c:g}, "
                f"{settings.anomaly_bom_temp_max_c:g}]",
            )
        )
    humidity = doc.get("humidity_pct")
    if humidity is not None and not (
        settings.anomaly_bom_humidity_min_pct
        <= humidity
        <= settings.anomaly_bom_humidity_max_pct
    ):
        results.append(
            RuleResult(
                True,
                "rule:humidity_out_of_range",
                f"humidity_pct={humidity:g} outside [0, 100]",
            )
        )
    wind = doc.get("wind_speed_kmh")
    if wind is not None and (
        wind < 0 or wind > settings.anomaly_bom_wind_speed_max_kmh
    ):
        results.append(
            RuleResult(
                True,
                "rule:wind_speed_out_of_range",
                f"wind_speed_kmh={wind:g} outside "
                f"[0, {settings.anomaly_bom_wind_speed_max_kmh:g}]",
            )
        )
    return results


def _completeness(
    doc: dict[str, Any], source: str, settings: IngestionSettings
) -> RuleResult:
    metrics = settings.metric_columns_for_source(source)
    missing = [m for m in metrics if doc.get(m) is None]
    if missing:
        return RuleResult(
            True,
            "rule:incomplete_record",
            f"missing expected field(s) for {source}: {', '.join(missing)}",
        )
    return RuleResult(False, "rule:incomplete_record", "")


def _staleness(
    doc: dict[str, Any], source: str, settings: IngestionSettings
) -> RuleResult:
    threshold = settings.staleness_threshold_minutes_for_source(source)
    if threshold is None:
        return RuleResult(False, "rule:stale_record", "")
    ts_col = settings.timestamp_column_for_source(source)
    ts = _as_datetime(doc.get(ts_col))
    fetched_at = _as_datetime(doc.get("fetched_at"))
    if ts is None or fetched_at is None:
        return RuleResult(False, "rule:stale_record", "")
    lag_minutes = (fetched_at - ts).total_seconds() / 60.0
    if lag_minutes > threshold:
        return RuleResult(
            True,
            "rule:stale_record",
            f"fetched {lag_minutes:.0f} min after {ts_col} "
            f"(threshold {threshold:.0f} min for {source})",
        )
    return RuleResult(False, "rule:stale_record", "")


def evaluate_rules(
    source: str,
    doc: dict[str, Any],
    *,
    prev_doc: dict[str, Any] | None = None,
    settings: IngestionSettings | None = None,
) -> list[RuleResult]:
    """Every fired rule for `doc`, in no particular order. `prev_doc`
    (same-entity, chronologically immediately prior, within the current
    batch) is only used by the sudden-jump check -- omit it for a
    single-record call (e.g. from a test) or when there genuinely isn't
    one (first record for that entity in the batch).
    """
    settings = settings or get_ingestion_settings()
    fired: list[RuleResult] = []

    if source in _ENERGY_SOURCES:
        for result in (
            _price_range(doc, settings),
            _demand_negative(doc, settings),
            _demand_sudden_jump(doc, prev_doc, settings),
        ):
            if result.fired:
                fired.append(result)
    elif source == "bom":
        fired.extend(r for r in _bom_ranges(doc, settings) if r.fired)

    completeness = _completeness(doc, source, settings)
    if completeness.fired:
        fired.append(completeness)

    staleness = _staleness(doc, source, settings)
    if staleness.fired:
        fired.append(staleness)

    return fired


__all__ = ["RuleResult", "evaluate_rules"]
