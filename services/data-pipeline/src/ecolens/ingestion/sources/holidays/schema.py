"""Holiday v1.0 schema — region/state maps, holiday templates, output columns.

Pure configuration: no I/O, no classes. See `engine.py`'s module
docstring for the fetcher design (3-tier live/cache/synthetic).
"""

from __future__ import annotations

# ────────────────────────────────────────────────────────────────────
# Schema version — bump when adding/removing/renaming columns
# ────────────────────────────────────────────────────────────────────
SCHEMA_VERSION: str = "1.0"


# ────────────────────────────────────────────────────────────────────
# Source constants
# ────────────────────────────────────────────────────────────────────
DATA_GOV_AU_BASE = "https://data.gov.au/data/api/3/action"
DATA_GOV_AU_DATASET = "australian-public-holidays-combined"
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5

# Local CSV cache layout: <cache_dir>/holidays_<region>_<YYYY>.csv
# (cache_dir itself comes from Settings.holidays_cache_dir, see config.py)

# NEM/WEM regions. Must match the BoM fetcher's region set so the
# dbt join is consistent.
NEM_REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM")

# Map: NEM region -> Australian state/territory code.
# (Why: data.gov.au holidays are tagged by state; we need to fan-out
# the per-state list to the right NEM regions.)
REGION_TO_STATE: dict[str, str] = {
    "NSW1": "NSW",
    "QLD1": "QLD",
    "VIC1": "VIC",
    "SA1": "SA",
    "TAS1": "TAS",
    "WEM": "WA",
}

# Reverse map: state -> tuple of NEM regions.
_state_regions: dict[str, list[str]] = {}
for _region, _state in REGION_TO_STATE.items():
    _state_regions.setdefault(_state, []).append(_region)
STATE_TO_REGIONS: dict[str, tuple[str, ...]] = {
    state: tuple(regions) for state, regions in _state_regions.items()
}

# Valid Australian state codes (only the 6 we care about)
VALID_STATES: frozenset[str] = frozenset({"NSW", "QLD", "VIC", "SA", "TAS", "WA"})

# Valid holiday types
VALID_HOLIDAY_TYPES: frozenset[str] = frozenset(
    {
        "national",  # observed in all states (e.g. Christmas)
        "state",  # observed in one state only
        "regional",  # observed in a sub-region of one state (e.g. AFL GF -> Melbourne)
        "bank",  # bank holiday (not a public holiday in all states)
        "observance",  # not a public holiday but widely observed (e.g. NYE, ANZAC Day)
    }
)


# ════════════════════════════════════════════════════════════════════
# Output schema — v1.0 (13 columns)
# ════════════════════════════════════════════════════════════════════
HOLIDAY_OUTPUT_COLUMNS: list[str] = [
    # ── Identity ───────────────────────────────────────────────
    "date",  # ISO date string (YYYY-MM-DD)
    "region",  # NSW1 / QLD1 / VIC1 / SA1 / TAS1 / WEM
    "state",  # NSW / QLD / VIC / SA / TAS / WA
    "holiday_name",  # human-readable name
    "holiday_type",  # "national" / "state" / "regional" / "observance"
    "schema_version",  # "1.0"
    # ── Derived flags ──────────────────────────────────────────
    "is_business_day",  # always False
    "is_observed",  # True if rolled to Monday
    "observed_date",  # ISO date string or None
    # ── Fetch-time metadata ────────────────────────────────────
    "days_until",  # int; set at fetch time, None otherwise
    "source",  # "data_gov_au" / "state_api" / "cache" / "synthetic"
    "ingest_run_id",
    "fetched_at",  # tz-aware UTC timestamp
]


# ════════════════════════════════════════════════════════════════════
# Static holiday templates per state
# ════════════════════════════════════════════════════════════════════
# (name, month-day, type) tuples. Easter-dependent ones are resolved
# by `transformers.resolve_date()` from `transformers.easter_date()`.
#
# "MM-DD" -> fixed date
# "easter+N" or "easter-N" -> N days from Easter Sunday

# National holidays (observed in every state)
NATIONAL_HOLIDAYS: tuple[tuple[str, str, str], ...] = (
    ("New Year's Day", "01-01", "national"),
    ("Australia Day", "01-26", "national"),
    ("Good Friday", "easter-2", "national"),
    ("Easter Saturday", "easter-1", "observance"),
    ("Easter Sunday", "easter+0", "observance"),
    ("Easter Monday", "easter+1", "national"),
    ("Anzac Day", "04-25", "national"),
    ("Christmas Day", "12-25", "national"),
    ("Boxing Day", "12-26", "national"),
)

# State-specific holidays. Each state has a slightly different set.
STATE_HOLIDAYS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "NSW": (
        ("Queen's Birthday", "06-09", "state"),  # 2nd Monday of June
        ("Labour Day", "10-01", "state"),  # 1st Monday of October
        ("Bank Holiday", "08-01", "bank"),  # 1st Monday of August
    ),
    "QLD": (
        ("Labour Day", "05-01", "state"),  # 1st Monday of May
        ("Queen's Birthday", "10-01", "state"),  # 1st Monday of October
    ),
    "VIC": (
        ("Labour Day", "03-01", "state"),  # 2nd Monday of March
        ("Queen's Birthday", "06-09", "state"),
        ("Melbourne Cup Day", "11-01", "state"),  # 1st Tuesday of November
        ("AFL Grand Final Friday", "09-30", "regional"),  # varies
    ),
    "SA": (
        ("Adelaide Cup Day", "03-01", "state"),
        ("Labour Day", "10-01", "state"),
        ("Queen's Birthday", "06-09", "state"),
        ("Proclamation Day", "12-26", "state"),  # additional SA Dec 26
    ),
    "TAS": (
        ("Eight Hours Day", "03-01", "state"),
        ("Queen's Birthday", "06-09", "state"),
        ("Recreation Day", "11-01", "state"),  # 1st Monday of November
    ),
    "WA": (
        ("Labour Day", "03-01", "state"),
        ("Western Australia Day", "06-01", "state"),  # 1st Monday of June
        ("Queen's Birthday (WA)", "09-30", "state"),  # last Monday of September
    ),
}

# National holidays that roll over to the next Monday when they fall
# on a weekend, in the states that observe that practice.
ROLLOVER_STATES: frozenset[str] = frozenset({"NSW", "VIC", "SA", "WA"})
ROLLOVER_HOLIDAYS: frozenset[str] = frozenset(
    {"New Year's Day", "Australia Day", "Anzac Day", "Christmas Day", "Boxing Day"}
)
