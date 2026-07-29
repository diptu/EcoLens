"""Root TODO.md's "Anomaly Detection" section, v1 statistical layer:
"robust rolling statistics, no training pipeline." The half of the
hybrid detector `rules.py` can't cover -- a hardcoded threshold can't
catch "this value is fine in the abstract but wildly out of character
for 3pm on a Tuesday in this region."

Median + MAD (median absolute deviation), not mean/std: robust to the
very outliers this is meant to detect, which a plain std-dev baseline
would let quietly inflate itself (one huge spike drags the mean and
std-dev both toward it, making the *next* spike look less anomalous by
comparison -- the median and MAD barely move). Scores a new value via
the standard MAD-based "modified z-score" (Iglewicz & Hoaglin):
`0.6745 * (x - median) / MAD`, thresholded at
`IngestionSettings.anomaly_robust_zscore_threshold` (3.5 by default,
the commonly-cited value for that formula -- not the more familiar
3-sigma rule of thumb, which assumes a plain std-dev baseline this
deliberately isn't using).

No separate training/serving split, no persisted model artifact: the
baseline is rebuilt from recent DuckDB history once per
`scorer.score_batch()` call and used for that one batch only. Cheap
enough to run inline in the hot ingest path (a handful of DuckDB reads,
a `pandas.groupby` over at most a few thousand rows) -- v2's periodically-
retrained IsolationForest (root TODO.md, explicitly deferred) is the
model that would need that split, not this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ecolens.ingestion.core.settings import IngestionSettings, get_ingestion_settings
from ecolens.ingestion.db import duckdb_store

# Iglewicz & Hoaglin's constant, scaling MAD to be a consistent estimator
# of the standard deviation under a normal distribution -- what turns a
# plain MAD-based deviation into a "z-score-shaped" number comparable to
# `anomaly_robust_zscore_threshold`.
_MAD_CONSISTENCY_CONSTANT = 0.6745


@dataclass(frozen=True)
class BaselineResult:
    """`zscore`/`median`/`mad` are all `None` together when the baseline
    is too thin to trust (cold start: a new region/station, or simply
    not enough history yet) -- `scorer.py` treats a `None` zscore as "no
    statistical opinion," not "definitely not an outlier."
    """

    zscore: float | None
    median: float | None
    mad: float | None
    n_samples: int


class RollingBaseline:
    """Built once per `source` per `score_batch()` call, then queried
    per `(entity, metric)` for every doc in the batch -- one DuckDB read
    per batch, not one per record.
    """

    def __init__(
        self,
        source: str,
        *,
        settings: IngestionSettings | None = None,
        history: pd.DataFrame | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.source = source
        self.settings = settings or get_ingestion_settings()
        self._stats: dict[tuple[tuple[str, ...], str], tuple[float, float, int]] = {}
        self._build(
            history
            if history is not None
            else self._load_history(self.settings, db_path)
        )

    def _load_history(
        self, settings: IngestionSettings, db_path: Path | None
    ) -> pd.DataFrame:
        """Recent history for `self.source`, scoped by `fetched_at`
        (not `ts`) -- `read_historical_since` already filters on
        `fetched_at`, and for every source but AEMO NEM's own documented
        ~4am-next-day publish lag, `fetched_at` tracks `ts` closely
        enough that this is immaterial for a robust statistical baseline
        over hundreds of samples (off by at most ~1 day at the window's
        edge, not a precision this baseline needs). Reusing the existing
        method rather than adding a second, `ts`-scoped DuckDB read path
        for a difference this small.
        """
        since = datetime.now(timezone.utc) - timedelta(
            days=settings.anomaly_baseline_lookback_days
        )
        rows = duckdb_store.read_historical_since(
            self.source, since=since, db_path=db_path
        )
        return pd.DataFrame(rows)

    def _build(self, history: pd.DataFrame) -> None:
        metrics = self.settings.metric_columns_for_source(self.source)
        if history.empty or not metrics:
            return
        entity_cols = self.settings.entity_columns_for_source(self.source)

        if entity_cols:
            missing_cols = [c for c in entity_cols if c not in history.columns]
            if missing_cols:
                return
            groups = history.groupby(list(entity_cols))
        else:
            groups = [((), history)]

        for key, group in groups:
            entity_key = key if isinstance(key, tuple) else (key,)
            for metric in metrics:
                if metric not in group.columns:
                    continue
                values = (
                    pd.to_numeric(group[metric], errors="coerce").dropna().to_numpy()
                )
                if len(values) < self.settings.anomaly_baseline_min_samples:
                    continue
                median = float(np.median(values))
                mad = float(np.median(np.abs(values - median)))
                self._stats[(entity_key, metric)] = (median, mad, len(values))

    def score(
        self, entity_key: tuple[str, ...], metric: str, value: float
    ) -> BaselineResult:
        stats = self._stats.get((entity_key, metric))
        if stats is None:
            return BaselineResult(None, None, None, 0)
        median, mad, n = stats
        # A genuinely constant recent history (mad == 0) would otherwise
        # make any deviation at all look infinitely anomalous -- a tiny
        # floor keeps the score finite without materially changing the
        # result for any real (non-degenerate) series.
        effective_mad = mad if mad > 1e-9 else 1e-9
        zscore = _MAD_CONSISTENCY_CONSTANT * (value - median) / effective_mad
        return BaselineResult(zscore=zscore, median=median, mad=mad, n_samples=n)


def load_baseline(
    source: str,
    *,
    settings: IngestionSettings | None = None,
    history: pd.DataFrame | None = None,
    db_path: Path | None = None,
) -> RollingBaseline:
    """The one call site `scorer.py` needs -- builds a fresh
    `RollingBaseline` for `source`. `history`, if given, skips the
    DuckDB read (what tests use to inject synthetic history). `db_path`
    is threaded through to the DuckDB read so a caller pointed at a
    non-default store (tests; `write_historical`'s own `db_path` param)
    baselines against the same file it's about to write to, not the
    global default.
    """
    return RollingBaseline(source, settings=settings, history=history, db_path=db_path)


__all__ = ["BaselineResult", "RollingBaseline", "load_baseline"]
