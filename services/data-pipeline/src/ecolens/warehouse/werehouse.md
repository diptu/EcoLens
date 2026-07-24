# How ecoLens turns raw data into predictions

---

## The problem we're solving

Our fetchers drop raw data into MongoDB every 30 minutes. That's 6 weather stations, 5 NEM regions, 1 WEM region, all firing at the same time. The data lands in there messy — different shapes, different time zones, some of it 5-min, some 30-min, some of it not even time series at all (holidays, for instance, are just dates).

The forecast API needs to train a neural network on this stuff. The dashboard needs to plot it. And we need to be able to ask questions like "what was the average demand in VIC1 on a 38°C weekday in February?" without writing a 200-line query.

So we need a warehouse. Not a fancy one. Just a place where the data is **clean, joined, and ready to answer questions** in under 200 milliseconds.

---

## The simple version

```
MongoDB (raw, messy)  →  dbt (the cleanup crew)  →  PostgreSQL (the answer machine)
```

That's it. Three places. Each one has a job.

- **MongoDB** is the parking lot. The data lands here first, and it doesn't have to be pretty.
- **dbt** is the cleaning crew. It takes the messy stuff, fixes it up, joins it together, and writes the result.
- **PostgreSQL** is where we keep the finished product. This is what the dashboard and the forecast API read from. They never touch MongoDB.

---

## The four layers of cleaning

The dbt project has four layers, and each one has a specific job. Think of it like a kitchen.

### 1. Staging — "just rename the columns"

The first layer is a thin wrapper over MongoDB. It does almost nothing. It just:

- Picks the right fields
- Renames them to snake_case
- Casts the types (the fetchers send some as strings, some as numbers; staging normalizes)
- Filters out the obvious junk

No business logic. No joins. No math. If a model in staging has more than 30 lines of SQL, something has gone wrong.

Each source gets one staging model: `stg_aemo_nem_dispatch`, `stg_bom_observations`, `stg_public_holidays`, and so on. These are **views** in PostgreSQL, which means they're free — no storage, always up to date.

### 2. Intermediate — "make the grains match"

This is where the real work happens. The three energy sources (AEMO NEM, AEMO WEM, OpenElectricity) all measure the same thing — electricity in and out of the grid — but they have different **time grains**:

- NEM: every 5 minutes
- WEM: every 30 minutes
- OpenElectricity: every 5 minutes (network-level, not per-region)

Before we can do anything useful, we need them all on the same grain. So we roll the 5-minute NEM data up to 30-minute averages and stack it next to the WEM data. Now we have one big unified 30-minute fact table covering the whole country.

This is also where we join the weather. Each 30-minute energy reading gets a temperature, humidity, and wind speed attached to it. And we add the holiday flag.

Intermediate models are **incrementals** — they only re-process the last 5 days, not all of history. New data trickles in, the intermediate models update, the whole pipeline stays fast.

There's one more intermediate step, and it's the one that makes the LSTM feature table trustworthy: `int_energy_filled_30min`. AEMO occasionally drops a 30-minute slot, and BoM occasionally misses a reading — when that happens, `int_energy_with_weather` just doesn't have a row for it. That's fine for the dashboard (a gap shows up as a gap), but it's poison for `LAG()`/`AVG() OVER (ORDER BY ts_30)`: if a slot is missing, "1 step back" quietly becomes "2 steps back" and a "7-day" rolling window quietly covers more or less than 7 days. `int_energy_filled_30min` builds a full (region × 30-min slot) calendar spine and forward-fills every metric onto it (falling back to the region's all-time average for the rare case of a gap with nothing prior to carry forward), flagging every filled slot via `is_gap_filled`. It's a full table rebuild rather than incremental, because forward-fill is a whole-series computation — but it's cheap, since it only reads the already-incremental `int_energy_with_weather`.

### 3. Marts — "make it queryable"

Marts are the tables the dashboard and forecast API actually read. They're small, wide, and ready to answer questions.

We have a handful:

- `fact_demand_30min` — the main one. Every row is "at this time, in this region, demand was X and temperature was Y." About a million rows a year.
- `dim_region` — the 6 regions (NSW1, QLD1, VIC1, SA1, TAS1, WEM) with their state codes and populations.
- `dim_holiday` — which dates are public holidays in which region.
- `ml_features_demand_v1` — the master feature table the LSTM trains and infers on. Each row has 48 lagged demand values, 7-day rolling mean/stddev, price and grid-mix covariates, the full 10-column weather set, holiday/weekend flags, and cyclical time encodings — on a uniform, gap-free 30-min grid, so there's nothing left to clean up in Python.

Marts are **tables** (not views) because the dashboard and forecast API hit them constantly. Storing them once and reading from disk is way faster than recomputing every query.

### 4. ML features — "feed the model"

This is the secret sauce. The LSTM doesn't just want "today's demand." It wants "today's demand, plus yesterday's demand at this time, plus the demand from 24 hours ago, plus the average over the last week, plus the price, plus how much of the grid was renewables, plus the temperature, plus whether it's a public holiday, plus whether it's the weekend, plus where in the day/week/year this timestamp sits." That's a lot of features, and computing them in Python for every training batch is slow — and doing it on a series with silent gaps in it produces features that are quietly wrong.

So we compute them in SQL using window functions (`LAG`, `AVG OVER`, `STDDEV OVER`) on top of `int_energy_filled_30min`'s gap-free grid. The database does the heavy lifting, the model just reads the result — no missing values, no resampling, no NaNs to mask. Training is 3-4x faster this way, and the LSTM's `state_dict` portability story (see `services/forecast-api/strategy.md`) only works cleanly if the training and serving paths read from the exact same, already-clean feature table.

---

## The schedule

Everything runs from one crontab entry. Here's the rhythm:

```
Every 30 min  →  fetch new data + run dbt
Every hour    →  refresh the ML feature tables
Every week    →  rebuild the ML training set (with 3-year lookback for late AEMO data)
Every year    →  pull the new year's holiday calendar
```

The 30-minute cron entry does the whole thing in one shot. It fetches the new data into MongoDB, and only if that succeeds does it run dbt to update the warehouse. If anything goes wrong, the next tick catches up — there's no corruption, no half-state.

---

## The mistakes we made (so you don't repeat them)

### The race condition

We used to have the fetchers and dbt running on separate cron schedules, every 15 minutes each. Then we realized: if dbt starts at 9:15 and the fetcher is still writing rows at 9:18, dbt sees a half-finished MongoDB collection and produces a half-finished warehouse. Bad.

**Fix:** Chain them. One script does fetch → dbt, in that order. If the fetch fails, dbt doesn't run.

### Daylight saving time

Australia has DST in some states and not others. If you do `LAG(demand_mw, 1) OVER (ORDER BY ts)` on a series where one row got skipped (the 2:30am one when the clock jumps forward) or duplicated (the 2:30am one when it jumps back), you get nonsense.

**Fix:** Everything is UTC inside the warehouse. Local time is only computed at the very last step, when we're about to display something to a human. Postgres knows about AEDT thanks to IANA tzdata, so `AT TIME ZONE 'Australia/Sydney'` handles it automatically.

### Late-arriving data

AEMO re-publishes "final" settlement data up to 3 years after the fact. If you train your LSTM on "preliminary" data and then the final numbers come in different, your model is suddenly wrong.

**Fix:** Every incremental model has a 5-day lookback window. It re-processes the last 5 days on every run, picking up any updates. 5 days is nothing (1,440 rows per region) but it catches most corrections. The ML training set has a much bigger lookback (3 years) and rebuilds weekly.

### 2GB RAM is tight

Window functions over a million rows can spike memory. Postgres spills to disk and the whole server freezes for 30 seconds.

**Fix:** Bumped `work_mem` from 4MB to 32MB. The default is conservative for general use; our queries are heavy on sorts and need the headroom. We also enabled `effective_io_concurrency = 200` to take advantage of the SSD.

---

## What's where

If you want to find something, here's the cheat sheet:

| Looking for… | Go to |
|--------------|-------|
| Raw energy data from AEMO | MongoDB `raw.aemo_nem_dispatch` |
| Clean energy data, ready to chart | Postgres `fact_demand_30min` |
| The gap-filled, uniform-interval series everything ML is built on | Postgres `int_energy_filled_30min` |
| What features does the LSTM use? | Postgres `ml_features_demand_v1` |
| Why is a holiday showing up? | Postgres `dim_holiday` |
| What stations is BoM pulling from? | MongoDB `raw.bom_observations` |
| When did dbt last run? | `/var/log/ecolens/ingest-*.log` |
| What models are in the project? | `/opt/ecolens/dbt/models/` |

---

## TL;DR

MongoDB is where data lands. dbt cleans it. PostgreSQL is where it lives once it's useful. The whole thing runs from a 30-minute cron entry, holds a million rows in a couple hundred MB, and feeds both the dashboard and the forecast API. The trick is being disciplined about the layers — don't put business logic in staging, don't do math in marts, don't reach back to MongoDB from the dashboard.

If you keep it that simple, the thing just runs.
