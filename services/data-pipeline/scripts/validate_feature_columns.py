#!/usr/bin/env python3
"""Empirically validates candidate model features BEFORE warehousing --
against every column ingestion actually produced, not just the columns
dbt's marts already chose to keep.

This is the pre-warehousing gate the workflow was inverted to use:
previously this script (and FEATURE_COLUMNS itself) only ever looked at
`ml_features_demand_v1` -- the mart dbt had *already* curated down to a
fixed column set. That meant "is FEATURE_COLUMNS right?" could only ever
be checked against columns dbt had already decided to keep, and several
raw ingested columns never got a chance to be evaluated at all, because
dbt's intermediate layer drops them before they ever reach a queryable
mart:
  * `raw.aemo_holidays`: `holiday_name`, `holiday_type`, `is_business_day`,
    `is_observed` -- collapsed to a single `is_holiday` boolean in
    int_energy_with_weather.sql's `holiday` CTE.
  * `raw.bom_observations`: `rain_last_hour_mm`, `cloud_oktas` -- survive
    staging but get dropped in the same file's `weather` CTE.
  * `raw.aemo_nem_dispatch`/`aemo_wem_dispatch` generation mix:
    `coal_black_mw`, `coal_brown_mw`, `gas_ccgt_mw`, `gas_ocgt_mw`,
    `gas_other_mw`, `pumped_hydro_mw`, `distillate_mw`,
    `battery_charge_mw`, `battery_discharge_mw`,
    `curtailment_solar_utility_mw`, `curtailment_wind_mw`,
    `interconnector_imports_mw`/`exports_mw`, `market_value`,
    `total_generation_mw` -- collapsed into one summed
    `renewable_generation_mw` in ml_features_demand_v1.sql.
  * `raw.openelectricity_responses` -- never joined into the demand
    lineage at all (network-level, not per-region; only feeds the
    separate fact_generation_30min mart).

This script fetches ALL of the above directly from the staging views
(`stg_*`, thin rename/cast passes over `raw.*` -- see werehouse.md),
joined at the same (region, ts_30) grain int_energy_with_weather.sql
uses, and runs the same signal checks as before (missingness, variance,
correlation/mutual-info with the horizon-ahead target, RandomForest
importance). The intended workflow from here on:

    1. Ingest (unchanged).
    2. Run THIS script against the raw/staging layer -- every ingested
       column is a candidate, nothing is pre-excluded by an existing
       mart definition.
    3. Only the columns that pass get added to ml_features_demand_v1.sql
       (so dbt actually selects/joins them through) and to
       ecolens.forecasting.features.FEATURE_COLUMNS (so the LSTM
       actually trains on them).

One raw column is deliberately excluded regardless of what it scores:
`aemo_holidays.days_until` is computed once, at ingestion time, as
`(holiday_date - ingestion_date).days` (see
`ingestion/sources/holidays/transformers.py::attach_days_until`) -- a
snapshot relative to when the row was *fetched*, not to the row's own
date. Joined onto historical rows months or years later, it would be
stale/wrong on every row except the ones ingested the same day, so it's
excluded here as a known bad feature rather than validated as if it
were a legitimate one. A correct "days until next holiday" would need
computing fresh, relative to each row's own date -- not implemented
here; a reasonable follow-up if validation of the rest suggests
calendar-distance features are worth having.

Run from the data-pipeline venv (needs the `ecolens` package):

    cd services/data-pipeline
    uv run --active python scripts/validate_feature_columns.py \\
        --start-date 2026-01-01 --end-date 2026-07-01

    # Or via Makefile from the repo root:
    make validate-features START_DATE=2026-01-01 END_DATE=2026-07-01 [REGION=NSW1]
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_selection import mutual_info_regression

from ecolens.config import get_settings
from ecolens.forecasting.features import FEATURE_COLUMNS
from ecolens.shared.observability.logging import get_logger
from ecolens.warehouse.api.settings import get_warehouse_api_settings

log = get_logger("validate_feature_columns")

# Every numeric column the three energy sources (AEMO NEM, AEMO WEM,
# OpenElectricity) share -- see macros/energy_columns.sql's
# stg_energy_columns()/energy_metric_columns(), mirrored here since this
# script talks to Postgres directly rather than through dbt.
ENERGY_COLUMNS = (
    "demand_mw",
    "price_mwh",
    "market_value",
    "coal_black_mw",
    "coal_brown_mw",
    "gas_ccgt_mw",
    "gas_ocgt_mw",
    "gas_other_mw",
    "hydro_mw",
    "pumped_hydro_mw",
    "wind_mw",
    "solar_utility_mw",
    "solar_rooftop_mw",
    "biomass_mw",
    "distillate_mw",
    "battery_discharge_mw",
    "battery_charge_mw",
    "curtailment_solar_utility_mw",
    "curtailment_wind_mw",
    "total_generation_mw",
    "renewable_proportion",
    "emissions_intensity_kgco2e_per_mwh",
    "interconnector_imports_mw",
    "interconnector_exports_mw",
    "net_import_mw",
)

# Every BoM weather column -- the 10 macros/energy_columns.sql's
# weather_metric_columns() keeps, PLUS the 2 it drops
# (rain_last_hour_mm, cloud_oktas) before int_energy_with_weather.sql.
WEATHER_COLUMNS = (
    "temp_c",
    "apparent_temp_c",
    "dew_point_c",
    "humidity_pct",
    "wind_speed_kmh",
    "wind_direction_deg",
    "wind_gust_kmh",
    "pressure_hpa",
    "rain_since_9am_mm",
    "rain_last_hour_mm",
    "cloud_oktas",
    "cloud_cover_pct",
)

# region -> local IANA timezone, mirrors macros/time_helpers.sql's
# region_timezone_case() (needed here to compute the cyclical time
# features in Python, since the raw/staging layer has no equivalent --
# those columns are only ever computed inside ml_features_demand_v1.sql
# itself, which this script deliberately reads *around*).
REGION_TIMEZONES = {
    "NSW1": "Australia/Sydney",
    "QLD1": "Australia/Brisbane",
    "VIC1": "Australia/Melbourne",
    "SA1": "Australia/Adelaide",
    "TAS1": "Australia/Hobart",
    "WEM": "Australia/Perth",
}
REGION_TO_NETWORK = {r: "NEM" for r in ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")} | {
    "WEM": "WEM"
}

# Columns that are identifiers, not model-input candidates one way or
# the other.
_NEVER_CANDIDATES = {"region", "ts_30"}

_BUCKET_30MIN = (
    "(date_trunc('hour', {c}) + floor(date_part('minute', {c}) / 30) * interval '30 minutes')"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--start-date", type=date.fromisoformat, required=True, help="YYYY-MM-DD"
    )
    parser.add_argument(
        "--end-date", type=date.fromisoformat, required=True, help="YYYY-MM-DD"
    )
    parser.add_argument(
        "--region", default=None, help="Restrict to one region. Default: all regions."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/feature_validation"),
        help="Where to write the two chart PNGs.",
    )
    return parser.parse_args()


def _build_query(region: str | None) -> tuple[str, list[object]]:
    energy_avg = ",\n        ".join(f"avg({c}) as {c}" for c in ENERGY_COLUMNS)
    weather_avg = ",\n        ".join(f"avg({c}) as {c}" for c in WEATHER_COLUMNS)
    bucket_ts = _BUCKET_30MIN.format(c="ts")
    region_tz_values = ", ".join(f"('{r}','{tz}')" for r, tz in REGION_TIMEZONES.items())
    region_network_values = ", ".join(
        f"('{r}','{n}')" for r, n in REGION_TO_NETWORK.items()
    )
    oe_avg = ",\n        ".join(f"avg({c}) as oe_{c}" for c in ENERGY_COLUMNS)

    query = f"""
    with energy_raw as (
        select * from stg_aemo_nem_dispatch
        union all
        select * from stg_aemo_wem_dispatch
    ),
    energy as (
        select region, {bucket_ts} as ts_30, {energy_avg}
        from energy_raw
        group by region, {bucket_ts}
    ),
    weather as (
        select region, {bucket_ts} as ts_30, {weather_avg}
        from stg_bom_observations
        group by region, {bucket_ts}
    ),
    -- days_until deliberately not selected -- see module docstring for why
    -- it's a known-broken, ingestion-time-relative snapshot, not a
    -- per-row feature.
    holiday as (
        select region, date, holiday_name, holiday_type, is_business_day, is_observed
        from stg_public_holidays
    ),
    region_tz (region, tz) as (values {region_tz_values}),
    region_network (region, network_code) as (values {region_network_values}),
    openelectricity as (
        select network_code, {bucket_ts} as ts_30, {oe_avg}
        from stg_openelectricity_network
        group by network_code, {bucket_ts}
    )
    select
        e.region, e.ts_30,
        {", ".join(f"e.{c}" for c in ENERGY_COLUMNS)},
        {", ".join(f"w.{c}" for c in WEATHER_COLUMNS)},
        coalesce(h.date is not null, false)::int as is_holiday,
        h.holiday_name, h.holiday_type,
        coalesce(h.is_business_day, false)::int as is_business_day,
        coalesce(h.is_observed, false)::int as is_observed,
        {", ".join(f"oe.oe_{c}" for c in ENERGY_COLUMNS)}
    from energy e
    left join weather w on w.region = e.region and w.ts_30 = e.ts_30
    left join region_tz rt on rt.region = e.region
    left join holiday h on h.region = e.region and h.date = (e.ts_30 at time zone rt.tz)::date
    left join region_network rn on rn.region = e.region
    left join openelectricity oe on oe.network_code = rn.network_code and oe.ts_30 = e.ts_30
    where e.ts_30 >= $1 and e.ts_30 < $2
    {{region_clause}}
    order by e.region, e.ts_30
    """
    params: list[object] = [None, None]  # filled by caller (start/until)
    region_clause = ""
    if region:
        region_clause = f"and e.region = ${len(params) + 1}"
        params.append(region)
    return query.format(region_clause=region_clause), params


def _add_cyclical_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adds hour/dow/month sin-cos + is_weekend -- computed here in
    Python (using the same region -> timezone mapping
    macros/time_helpers.sql's region_timezone_case() applies in SQL)
    since the raw/staging layer has no equivalent; these are the one
    piece of the current FEATURE_COLUMNS set that's genuinely derived
    rather than a raw ingested column, so they're recomputed for
    apples-to-apples comparison against everything else here.
    """
    # Each row's region has a *different* local timezone, so this can't be
    # a single vectorized `.dt` accessor call (pandas' datetime64 dtype
    # carries one tz for the whole column) -- extract per-row instead.
    local = [
        ts.tz_convert(ZoneInfo(REGION_TIMEZONES[region]))
        for ts, region in zip(df["ts_30"], df["region"], strict=True)
    ]
    hour_frac = pd.Series([t.hour + t.minute / 60 for t in local], index=df.index)
    dow = pd.Series([t.weekday() for t in local], index=df.index)  # Monday=0 .. Sunday=6
    month = pd.Series([t.month for t in local], index=df.index)

    df["is_weekend"] = (dow >= 5).astype(int)
    df["hour_sin"] = np.sin(2 * np.pi * hour_frac / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour_frac / 24)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)
    return df


async def _fetch(start: date, end: date, region: str | None) -> pd.DataFrame:
    """Fetches every ingested candidate column directly from the
    staging views (energy NEM+WEM unioned, weather, holiday,
    OpenElectricity network-level broadcast-joined onto each region) --
    NOT `ml_features_demand_v1`, which is exactly the mart this
    analysis is meant to inform, not read back from.
    """
    ws = get_warehouse_api_settings()
    if ws.pg_dsn:
        conn = await asyncpg.connect(dsn=ws.pg_dsn, timeout=ws.pg_command_timeout_seconds)
    else:
        conn = await asyncpg.connect(
            host=ws.pg_host,
            port=ws.pg_port,
            database=ws.pg_database,
            user=ws.pg_user,
            password=ws.pg_password,
            timeout=ws.pg_command_timeout_seconds,
        )
    try:
        query, params = _build_query(region)
        params[0] = start
        params[1] = end + timedelta(days=1)
        rows = await conn.fetch(query, *params)
    finally:
        await conn.close()
    log.info("validate_feature_columns.fetched", rows=len(rows))
    df = pd.DataFrame(dict(r) for r in rows)
    if not df.empty:
        df = _add_cyclical_time_features(df)
    return df


# Every column the wide query in _build_query()/_add_cyclical_time_features()
# is expected to produce (minus the region/ts_30 identifiers) -- used only to
# catch columns that are entirely NULL over the requested range, which pandas
# infers as `object` dtype (not float64) for an all-`None` column, silently
# failing _candidate_columns()'s numeric-dtype filter. Without checking
# against this explicit list, a 100%-missing column doesn't show up as
# 100% missing in the report -- it just vanishes, which is exactly backwards:
# total missingness should be the most visible finding, not an invisible one.
_ALL_CANDIDATE_COLUMNS = (
    tuple(ENERGY_COLUMNS)
    + tuple(WEATHER_COLUMNS)
    + tuple(f"oe_{c}" for c in ENERGY_COLUMNS)
    + ("is_holiday", "is_business_day", "is_observed")
    + ("is_weekend", "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos")
)


def _entirely_missing_columns(df: pd.DataFrame) -> list[str]:
    return [
        col
        for col in _ALL_CANDIDATE_COLUMNS
        if col not in df.columns or df[col].isna().all()
    ]


def _candidate_columns(df: pd.DataFrame) -> list[str]:
    numeric = df.select_dtypes(include="number").columns
    return [c for c in numeric if c not in _NEVER_CANDIDATES]


def _horizon_shifted_target(df: pd.DataFrame, horizon: int) -> pd.Series:
    """`demand_mw`, `horizon` steps into the future -- what the LSTM is
    actually asked to predict, shifted *within each region* so a shift
    near a region boundary never pulls in the next region's early rows.
    """
    return df.groupby("region")["demand_mw"].shift(-horizon)


def _analyze(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    candidates = _candidate_columns(df)
    target = _horizon_shifted_target(df, horizon)
    valid = target.notna()

    # A pooled missing_pct can hide a NEM/WEM split entirely -- e.g.
    # total_generation_mw is 0% missing in WEM and 100% missing in NEM,
    # which pools to a misleading "~63% missing" that looks like ordinary
    # sparse data instead of "one network doesn't report this at all."
    # Breaking missingness out per network makes that pattern visible
    # directly in the table instead of needing a manual follow-up query.
    network = df["region"].map(REGION_TO_NETWORK)
    networks = sorted(network.dropna().unique())

    rows = []
    for col in candidates:
        series = df[col]
        missing_pct = series.isna().mean() * 100
        variance = float(series.var(skipna=True) or 0.0)

        x = series[valid]
        y = target[valid]
        pair_valid = x.notna()
        x, y = x[pair_valid], y[pair_valid]

        corr = x.corr(y) if len(x) > 1 and x.std() > 0 else float("nan")
        mi = float("nan")
        if len(x) > 1 and x.std() > 0:
            mi = mutual_info_regression(
                x.to_numpy().reshape(-1, 1), y.to_numpy(), random_state=0
            )[0]

        row = {
            "column": col,
            "in_feature_columns": col in FEATURE_COLUMNS,
            "missing_pct": round(missing_pct, 2),
            "variance": variance,
            "corr_vs_target_at_horizon": corr,
            "mutual_info": mi,
        }
        for net in networks:
            net_series = series[network == net]
            row[f"missing_pct_{net}"] = (
                round(net_series.isna().mean() * 100, 2) if len(net_series) else float("nan")
            )
        rows.append(row)

    report = pd.DataFrame(rows).set_index("column")

    # RandomForest impurity importance -- one model, every candidate at
    # once, so it also captures interactions correlation/MI (computed
    # per-column above) can't see.
    model_df = df.loc[valid, candidates].copy()
    model_df = model_df.fillna(model_df.median(numeric_only=True))
    y = target[valid]
    y_valid = y.notna()
    forest = RandomForestRegressor(
        n_estimators=200, max_depth=8, n_jobs=-1, random_state=0
    )
    forest.fit(model_df[y_valid], y[y_valid])
    report["rf_importance"] = pd.Series(forest.feature_importances_, index=candidates)

    return report.sort_values("rf_importance", ascending=False)


def _plot_correlation_heatmap(report: pd.DataFrame, output_dir: Path) -> Path:
    included = report[report["in_feature_columns"]].sort_values(
        "corr_vs_target_at_horizon", key=abs, ascending=True
    )
    fig, ax = plt.subplots(figsize=(6, max(4, len(included) * 0.3)))
    values = included["corr_vs_target_at_horizon"].to_numpy().reshape(-1, 1)
    im = ax.imshow(values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_yticks(range(len(included)))
    ax.set_yticklabels(included.index)
    ax.set_xticks([])
    ax.set_title("Correlation with demand_mw, horizon steps ahead")
    for i, v in enumerate(included["corr_vs_target_at_horizon"]):
        ax.text(0, i, f"{v:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="Pearson r")
    fig.tight_layout()
    path = output_dir / "correlation_heatmap.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_importance(report: pd.DataFrame, output_dir: Path) -> Path:
    ranked = report.sort_values("rf_importance", ascending=True)
    colors = [
        "#2b7a78" if included else "#b0b0b0" for included in ranked["in_feature_columns"]
    ]
    fig, ax = plt.subplots(figsize=(8, max(4, len(ranked) * 0.3)))
    ax.barh(ranked.index, ranked["rf_importance"], color=colors)
    ax.set_xlabel("RandomForest impurity importance")
    ax.set_title(
        "Feature importance -- teal = in FEATURE_COLUMNS today, gray = new candidate"
    )
    fig.tight_layout()
    path = output_dir / "feature_importance.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _print_report(report: pd.DataFrame, entirely_missing: list[str]) -> None:
    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)

    print(
        "\n=== 100% missing in this window (excluded from the analysis below entirely -- "
        "not flagged low-signal, genuinely never present) ==="
    )
    print(entirely_missing or "(none)")

    network_missing_cols = [c for c in report.columns if c.startswith("missing_pct_")]
    print("\n=== Per-column signal (sorted by RandomForest importance) ===")
    print(
        "(missing_pct_* columns break the pooled missing_pct out per network -- "
        "watch for a column that's ~0% missing in one network and ~100% in another, "
        "which pools to a misleadingly 'moderately sparse' number)"
    )
    print(
        report[
            [
                "in_feature_columns",
                "missing_pct",
                *network_missing_cols,
                "variance",
                "corr_vs_target_at_horizon",
                "mutual_info",
                "rf_importance",
            ]
        ]
    )

    included = report[report["in_feature_columns"]]
    new_candidates = report[~report["in_feature_columns"]]

    # A zero-variance column produces a NaN correlation/mutual-info (no
    # variation to correlate against anything) -- and NaN compares as
    # False against every numeric threshold below, so a perfectly-
    # constant column would otherwise silently dodge the "weak signal"
    # flag instead of triggering it, which is exactly backwards.
    near_constant = report[report["variance"].fillna(0) <= 1e-12]
    print(
        "\n=== ~Zero variance in this window (contribute nothing here, "
        "regardless of what other signals say) ==="
    )
    print(near_constant.index.tolist() or "(none)")

    high_missing = report[report["missing_pct"] >= 90]
    print("\n=== >=90% missing in this window (e.g. openelectricity, barely ingested) ===")
    print(high_missing.index.tolist() or "(none)")

    scored = included.drop(index=included.index.intersection(near_constant.index))
    weak_signal = scored[
        (scored["rf_importance"] < scored["rf_importance"].quantile(0.25))
        & (scored["corr_vs_target_at_horizon"].abs() < 0.05)
        & (scored["mutual_info"] < scored["mutual_info"].quantile(0.25))
    ]
    print("\n=== Included features weak on all three signals (removal candidates) ===")
    print(weak_signal.index.tolist() or "(none)")

    exclude_new = near_constant.index.union(high_missing.index)
    scored_new = new_candidates.drop(index=new_candidates.index.intersection(exclude_new))
    strong_new = scored_new[
        scored_new["rf_importance"] >= included["rf_importance"].quantile(0.75)
    ]
    print(
        "\n=== New candidates (not currently in FEATURE_COLUMNS) scoring as high as "
        "top-quartile included features -- addition candidates ==="
    )
    print(strong_new.index.tolist() or "(none)")


async def main() -> int:
    args = parse_args()
    settings = get_settings()

    df = await _fetch(args.start_date, args.end_date, args.region)
    if df.empty:
        print("No rows returned for this range -- nothing to analyze.")
        return 1

    report = _analyze(df, horizon=settings.model_horizon)
    _print_report(report, _entirely_missing_columns(df))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    heatmap_path = _plot_correlation_heatmap(report, args.output_dir)
    importance_path = _plot_importance(report, args.output_dir)
    print(f"\nWrote {heatmap_path}")
    print(f"Wrote {importance_path}")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
