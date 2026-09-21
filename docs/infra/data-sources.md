# The Five Sources Behind Every Number on EcoLens

If you have already read the EcoLens ingestion overview in [`docs/infra/ingestion.md`](./ingestion.md), you know the general shape of the pipeline:

A Celery Beat schedule triggers ingestion, a circuit breaker protects against failing sources, DuckDB stages the data, R2 or MinIO stores snapshots, Postgres receives the records, and dbt transforms them into useful datasets.

That document explains the **plumbing**.

This one focuses on what actually flows through that plumbing: the five real-world data sources EcoLens depends on, why each source matters, how the data is fetched and processed, and where the system still has rough edges.

None of the details here are hypothetical. The behaviors, workarounds, bugs, and unresolved limitations come either from the current implementation or from issues that were discovered, fixed, and documented during development.

In several cases, the code comments effectively became small incident reports. That turned out to be useful: the history of what went wrong also explains why the pipeline works the way it does today.

---

## The Five Sources at a Glance

| Source                    | What it provides                                 | Native cadence                                             | Regions                           | Authentication                                  |
| ------------------------- | ------------------------------------------------ | ---------------------------------------------------------- | --------------------------------- | ----------------------------------------------- |
| **AEMO NEM**              | Regional demand and wholesale price              | 5-minute data, polled every 15 minutes                     | NSW1, QLD1, VIC1, SA1, TAS1       | None                                            |
| **AEMO WEM**              | Demand and reference trading price               | 5-minute demand / 30-minute price, polled every 15 minutes | WEM, Western Australia            | None                                            |
| **OpenElectricity**       | Generation mix by fuel type and emissions        | 5-minute NEM / 30-minute WEM, polled every 5 minutes       | All six regions                   | API key                                         |
| **Bureau of Meteorology** | Temperature, humidity, wind, pressure, and cloud | Hourly observations, polled every 30 minutes               | All six regions, one station each | API key technically available but mostly unused |
| **AEMO Public Holidays**  | Regional holidays and workday flags              | Once per year                                              | All six regions                   | None                                            |

So the platform combines five sources, six regions, several different government and market data formats, and one third-party SDK.

Each source contributes something different.

---

# 1. AEMO NEM: The Eastern Grid's Heartbeat

## What It Is

The National Electricity Market, or NEM, covers:

* New South Wales
* Queensland
* Victoria
* South Australia
* Tasmania

Together, these regions represent roughly 80% of Australia's population.

AEMO, the Australian Energy Market Operator, publishes dispatch information every five minutes. For EcoLens, the two most important values are:

* `demand_mw`: how much electricity the region is consuming
* `price_mwh`: the wholesale spot-market price

## Why EcoLens Needs It

NEM demand is the central target variable for the forecasting system.

Everything else in EcoLens exists partly to explain or predict this number:

* Weather helps explain demand changes.
* Holidays explain changes in daily patterns.
* Generation mix helps explain how demand is being supplied.
* Market prices provide additional market context.

Without NEM demand, there is no primary demand forecast and no meaningful demand chart.

## How the Data Is Processed

There is no single, clean “AEMO API” endpoint that solves everything. The actual ingestion path is closer to investigative work than ordinary API plumbing.

### Live and Recent Data: DispatchIS Archive

The current ingestion path uses AEMO's public **DispatchIS Archive**, available through `nemweb.com.au`.

The archive is organized as:

* One ZIP file per day
* 288 nested ZIP files inside it
* One nested ZIP for each five-minute dispatch interval

The request does not require an API key or authentication. However, it does require a `User-Agent` header. A basic `httpx` request without one returns no useful data.

Each nested CSV uses AEMO's MMS format, including row prefixes such as:

* `C`
* `I`
* `D`

EcoLens only needs two of the many embedded tables:

* `DISPATCH,REGIONSUM` for regional demand
* `DISPATCH,PRICE` for wholesale price

### Older Data: MMSDM Historical Archive

The DispatchIS Archive retains approximately 13 months of data.

For older records, EcoLens uses AEMO's **MMSDM Historical Data** archive. It provides monthly ZIP files and appears to go back to at least 2020. AEMO's documentation claims that data may go back to 2009, but only the 2020 boundary has been verified against an actual download.

The historical path uses:

* `DISPATCHREGIONSUM`
* `DISPATCHPRICE`

It is important not to confuse these with `DISPATCHLOAD`.

`DISPATCHLOAD` contains dispatch instructions for individual generating units. It is not the correct source for regional demand.

### Development and CI Fallbacks

Below the real archive integrations, the code has two additional fallback layers:

1. A development-only CSV cache at `/data/raw/aemo/nem/`, mounted through Docker Compose.
2. A deterministic synthetic stub that generates random-looking demand around each region's typical level.

The synthetic stub also sets fuel-mix columns to zero.

Its purpose is not to represent reality. It exists so local development and CI can still run when no real data is available.

### A Significant Production Bug

One incident is particularly important.

The original “live API” implementation used a guessed endpoint that returned `None` unconditionally, even when the HTTP response status was 200.

That caused the scheduled NEM ingestion process to silently fall through this chain:

```text
Guessed live endpoint
        ↓
Development cache
        ↓
Synthetic stub
```

Because the cache was only mounted in Docker Compose, the scheduled deployment ended up generating synthetic demand data instead of real AEMO readings.

In other words, every NEM row produced by that scheduled path was fake noise until the issue was discovered.

The fix was to route the live path through the already-verified DispatchIS Archive integration.

### Timestamp Handling

NEM reports use fixed AEST, or UTC+10, without daylight saving time.

EcoLens converts those timestamps to UTC during ingestion so that NEM data aligns with the other sources downstream.

`Australia/Brisbane` is used as an exact practical representation of this fixed offset because Queensland does not observe daylight saving time.

### Duplicate Safety

Re-fetching an already ingested day is safe.

The Postgres load layer uses:

```sql
ON CONFLICT DO NOTHING
```

against natural keys based on:

```text
timestamp + region
```

This makes repeated ingestion idempotent.

## What Could Be Improved?

### Synthetic Data Is Too Quiet

The synthetic fallback currently produces a warning in the logs rather than a strong alert.

That creates a risk: a source could serve fake data for days while looking healthy to anyone who only checks whether the ingestion job completed.

A stronger design would either:

* Add a dashboard-visible flag marking synthetic rows, or
* Disable the synthetic fallback outside development and fail loudly instead

### Backfills Download Too Much Repeated Data

A full-month backfill through MMSDM currently downloads the same monthly ZIP repeatedly.

The reason is that `pipeline.backfill` processes one calendar day at a time, while the in-process cache only survives within one ingestion call.

A cache at the backfill level would allow the monthly archive to be downloaded once and reused across all relevant days.

### Historical Format Changes Need Better Detection

AEMO changed its MMSDM filename convention around mid-2024.

The boundary was discovered by binary-searching real HTTP responses rather than by relying on documentation.

That solved the current problem, but there is no equivalent automated check for future format changes.

A scheduled canary fetch against a known-good recent day could detect a format change before a large backfill silently returns empty results.

---

# 2. AEMO WEM: The Other Australian Grid

## What It Is

Western Australia operates a separate electricity market from the NEM.

Its South West Interconnected System is commonly associated with the WEM, or Wholesale Electricity Market.

It has:

* Different market rules
* Different settlement processes
* A different data portal
* A different generation mix

The system includes substantial coal and gas generation, alongside growing wind and solar capacity.

## Why EcoLens Needs It

Western Australia represents roughly 10% of Australia's population, but its grid behaves differently from the eastern NEM regions.

Treating WEM as simply another NEM region with different numbers would be misleading.

EcoLens therefore gives WEM:

* Its own ingestion path
* Its own timezone handling
* Its own regional records
* Its own forecast and anomaly context

This allows the platform to distinguish a WEM-specific anomaly from a NEM-wide event.

## How the Data Is Processed

WEM demand and price come from two separate endpoints on `data.wa.aemo.com.au`.

### Demand Endpoint

The `operationalDemandWithdrawal` endpoint publishes real five-minute demand as daily JSON files.

### Price Endpoint

The `referenceTradingPrice` endpoint publishes reference trading prices at 30-minute intervals in ZIP files.

The two datasets are joined by timestamp.

That means a five-minute demand observation that does not fall on a `:00` or `:30` timestamp receives a genuine `NULL` price.

EcoLens does not interpolate a price simply to make the table look complete.

### Historical Data

AEMO WA does not provide a historical range query comparable to the NEM Archive.

There is no single endpoint where EcoLens can request an arbitrary date range.

Instead, historical ingestion requests each day's file individually from the same daily endpoints used by the live path.

This means a historical backfill requires one HTTP request per day for each endpoint.

### Publication Lag

WEM data typically runs about two days behind.

Today's and yesterday's files reliably return 404 responses, so the ingestion process uses a four-day lookback window to give AEMO enough time to publish the files.

Therefore, “live WEM data” really means:

> **The most recent data AEMO WA has actually published.**

It does not necessarily mean data from the current day.

### Timezone Handling

WEM uses fixed AWST, or UTC+8, without daylight saving time.

EcoLens converts these timestamps to UTC before storing them.

### Fallback Behavior

WEM uses the same general fallback structure as NEM:

```text
Live fetch
    ↓
Development CSV cache
    ↓
Synthetic stub
```

The WEM synthetic stub generates a complete fake fuel mix, including:

* Coal
* Gas
* Wind
* Solar
* Battery
* Biomass

This prevents downstream code from failing when it expects those columns to exist.

However, the WEM stub logs at error level rather than warning level.

That decision came from a previous bug in which a fixed random seed caused every fake reading to be identical for approximately four and a half real days. The issue deserved a stronger signal than a normal warning.

## What Could Be Improved?

### WEM Is Structurally Staler Than NEM

The approximately two-day publication lag is a limitation of the public WEM data source itself.

It is not something EcoLens can solve through a configuration change.

However, it means WEM forecasts operate with older ground truth than forecasts for NEM regions.

The forecast API could make this difference explicit in its freshness or confidence metadata rather than treating all six regions as equally current.

### Five-Minute Price Data Is Intentionally Incomplete

Price is only available every 30 minutes.

The demand rows between those timestamps retain `NULL` prices by design.

That is the honest representation of the source, but it means downstream features that require a price at every five-minute interval must implement their own forward-fill or other alignment strategy.

### Historical WEM Data Is Limited

WEM does not have a deep historical archive equivalent to NEM's MMSDM fallback.

Once a daily file disappears from AEMO WA's retention window, it may no longer be available.

A longer historical backfill would therefore require a new integration or an independently maintained archive. It is not simply a configuration change.

---

# 3. OpenElectricity: The Independent Cross-Check

## What It Is

OpenElectricity, formerly known as OpenNEM, is an independent third-party platform that tracks Australia's generation mix and emissions.

It is built using AEMO data but exposes that information through its own API and official Python SDK.

Unlike the AEMO sources, OpenElectricity requires an API key.

## Why EcoLens Needs It

AEMO tells EcoLens:

* How much electricity a region consumed
* What the wholesale price was

But AEMO's demand and price feeds do not directly provide the complete generation mix needed for carbon analysis.

OpenElectricity fills that gap with information about:

* Coal
* Gas
* Hydro
* Wind
* Utility solar
* Rooftop solar
* Battery charging
* Battery discharging
* Biomass
* Pumped hydro
* Emissions intensity

This allows EcoLens to answer a more meaningful question than “demand increased.”

It can begin to answer:

> **Demand increased, but what type of generation supplied that additional electricity?**

That distinction is central to a carbon-intelligence platform.

## How the Data Is Processed

OpenElectricity has experienced some of the most consequential integration issues in the project.

The problems were not all in the network layer. Several came from incorrect assumptions about the SDK and API's actual behavior.

### Missing API Keys Can Look Like Success

The installed SDK raises an exception immediately when no API key is configured.

There is no anonymous fallback comparable to the AEMO or BoM paths.

When the key was missing:

1. Client construction failed.
2. The error was caught by a per-region exception handler.
3. The ingestion run completed as “successful.”
4. Zero rows were written.

That final state looked like “there was no new data,” rather than “the source is broken.”

The result was that dependent charts, including Carbon Intensity and Emissions Trend, remained stale for more than a week while the AEMO feeds continued working normally.

### Fuel-Type Mapping Was Incomplete

The API uses detailed fuel codes such as:

* `coal_black`
* `coal_brown`
* `gas_ccgt`
* `gas_ocgt`

The original mapping table expected simpler labels such as:

* `coal`
* `gas`

As a result, real coal and gas records were silently dropped from the generation totals.

This was a serious issue because coal and gas often represent a large portion of generation.

### Emissions Units Were Off by 1,000

The API returns emissions in tonnes of CO₂e per interval.

The code initially treated the values as kilograms.

That created a 1,000-fold unit error.

The problem was discovered when the Executive Dashboard's Carbon Intensity KPI displayed zero-like values. The raw emissions values were then compared with concurrent generation for a known coal-heavy region, revealing the mismatch.

### Timestamps Were Shifted Into the Future

OpenElectricity timestamps were initially shifted by the region's UTC offset:

* 10 hours for NEM
* 8 hours for WEM

This happened because the code applied a local-time conversion to timestamps that the SDK had already returned with the correct timezone information.

The result was a double shift.

The fix was to trust the SDK's timestamp and strip the timezone information without shifting the actual clock value.

### The SDK Could Hang for Long Periods

A backfill request once stalled for more than 20 minutes with almost no CPU activity and no visible error.

The underlying async HTTP client uses a DNS resolver whose worker-thread stalls are not always interrupted by ordinary request timeouts.

The current implementation addresses this by:

* Wrapping requests in an explicit bounded timeout
* Creating a fresh client for each retry

### Region Filtering Was Incorrect

For a period of time, all five NEM regions received the same network-wide generation number, merely relabeled as different regions.

That meant NSW1 and TAS1 could appear to have identical generation mixes.

The issue was fixed by passing OpenElectricity's own `network_region` parameter so that each region is queried separately.

### Converting the SDK Output

The SDK returns long-form records such as:

```text
ts, fuel_type, value
```

EcoLens pivots these into the wide schema expected by `raw.openelectricity_mix`.

The transformation also correctly combines multiple raw fuel codes into a single destination field.

For example:

* `battery`
* `battery_discharging`

can both contribute to:

```text
battery_discharge_mw
```

The implementation must sum these values rather than allow one mapping to overwrite the other.

## What Could Be Improved?

### Missing Authentication Should Fail Loudly

The most serious structural risk is that a missing or expired API key can produce a successful run with zero rows.

A dedicated health check should distinguish between:

* No new data because the source genuinely has nothing new
* No new data because authentication failed
* No new data because the API returned an unexpected response

That would have detected the week-long staleness incident much earlier.

### Add Scheduled Contract Tests

Many OpenElectricity bugs came from assumptions about:

* Fuel-code names
* Units
* Timestamp behavior
* Region filtering

A small scheduled contract test against the real API could verify basic expectations, such as:

* Units fall within plausible ranges.
* Different regions do not all return identical totals.
* Known fuel categories are present.
* Timestamps remain within the expected time window.

This would catch API or SDK drift before it reaches dashboard KPIs.

### Handle Partial Emissions Data More Explicitly

Emissions intensity is currently calculated only when both generation and emissions are available for the same interval.

If one half arrives and the other does not, the intensity remains unpopulated.

A later-arriving counterpart is not automatically used to backfill the missing calculation.

A reconciliation step could improve this behavior.

---

# 4. Bureau of Meteorology: The Explanation Behind Demand Changes

## What It Is

The Bureau of Meteorology, or BoM, is Australia's national weather service.

EcoLens collects hourly observations from six airport-adjacent weather stations:

* Sydney
* Brisbane
* Melbourne
* Adelaide
* Hobart
* Perth

Each station represents one grid region.

## Why EcoLens Needs It

Electricity demand is strongly influenced by weather.

For example:

* Heatwaves increase air-conditioning demand.
* Cold weather increases heating demand.
* Wind and cloud cover affect renewable generation.
* Apparent temperature may explain human comfort and energy use better than temperature alone.

EcoLens therefore collects:

* Temperature
* Apparent temperature
* Humidity
* Wind
* Pressure
* Cloud cover

These features help the forecasting system distinguish unusual weather from unusual grid behavior.

## How the Data Is Processed

### Live Data from BoM

The live path uses BoM's public per-station JSON endpoint:

```text
bom.gov.au/fwo/{station_id}/observations.json
```

The endpoint is free and does not require an API key in practice.

However, it returns `403 Forbidden` when called without a browser-like `User-Agent` header. That behavior was discovered through live testing rather than from a clearly documented API contract.

### Historical Data from Open-Meteo

BoM's public feed exposes only a rolling window of approximately 72 hours.

It does not provide an arbitrary date-range query.

For historical backfills, EcoLens therefore uses Open-Meteo's ERA5 reanalysis archive.

This source is:

* Free
* Available without an API key
* Hourly
* Available as far back as 1940

However, it is not the same underlying provider as BoM, so the historical data is not a perfect field-for-field replacement.

### Rainfall Is Not Pretended to Match

BoM reports a field such as “rainfall since 9am.”

Open-Meteo provides hourly precipitation, which represents a different quantity.

EcoLens leaves the historical rainfall field as genuinely `NULL` instead of mapping Open-Meteo's precipitation into a field with a different meaning.

That is an important distinction. A complete-looking value is not necessarily a correct value.

### Cloud Cover Conversion

Cloud cover is handled differently because the conversion is well-defined.

Open-Meteo provides cloud cover as a percentage from 0 to 100.

BoM uses the 0–8 “oktas” scale.

EcoLens performs a documented unit conversion rather than an approximate guess.

### Station-to-Coordinate Mapping

BoM identifies weather stations using station IDs.

Open-Meteo queries historical weather using geographic coordinates.

EcoLens maintains a mapping from each BoM station to its latitude and longitude so that the two providers can represent the same regional weather location.

### Fallback Behavior

The weather pipeline follows the same general pattern as the AEMO integrations:

```text
Live BoM data
    ↓
Development cache
    ↓
Synthetic stub
```

The synthetic weather stub includes a plausible daily temperature curve:

* Lowest before dawn
* Rising during the morning
* Peaking during the afternoon

This is more useful than flat random noise because temperature naturally has a strong daily pattern.

## What Could Be Improved?

### Historical Rainfall Is Structurally Different

BoM's live rainfall field and Open-Meteo's historical rainfall-related data are not equivalent.

This creates a real inconsistency:

* Recent live rows may contain rainfall values.
* Older historical rows contain `NULL`.

Any future model feature based on rainfall would therefore be trained on a column with different completeness depending on the time period.

That difference should be documented and monitored explicitly.

### The BoM Endpoint Is Not a Strong Contract

The live endpoint has no documented service-level agreement in this implementation.

It is a public JSON feed that currently works, but it depends on behavior such as accepting a browser-like `User-Agent`.

A more resilient approach would use BoM's official data services where appropriate rather than relying indefinitely on an undocumented public endpoint.

### One Station Per Region Is a Coarse Approximation

Six stations are a reasonable starting point, but each grid region covers a large and geographically diverse area.

NSW1, in particular, is represented by a single Sydney-area observation despite covering a much larger state.

Potential improvements include:

* Averaging multiple stations per region
* Weighting stations by population or demand
* Learning a regional weather correction
* Using additional spatial weather features

The trade-off is increased ingestion complexity and more API requests.

---

# 5. AEMO Public Holidays: The Quiet Fifth Source

## What It Is

The holiday source is a small lookup table containing:

* Public holiday dates
* Holiday names
* Workday flags
* Regional coverage

Unlike the other four sources, this is not a time series.

It is refreshed once a year, currently scheduled for January 2nd.

It is also the only source in this pipeline that makes no HTTP request in the current implementation.

Instead, the code derives a baseline set of shared national holidays from a static table.

## Why EcoLens Needs It

Electricity demand on a public holiday can look very different from demand on a normal weekday.

On a holiday:

* Offices may be closed.
* Factories may operate at reduced capacity.
* Commercial activity may change.
* Residential demand patterns may shift.

Without a holiday indicator, the forecasting model may interpret a holiday-related demand drop as an unusual event rather than a predictable calendar effect.

## How It Is Processed

The implementation is relatively simple:

1. A static table contains holiday names and month-day pairs.
2. The requested year is expanded into dates.
3. The dates are replicated across the six regions.
4. Each date is marked with:

```text
is_workday = False
```

5. The records are written to the warehouse.
6. dbt joins the regional holiday table to the demand-and-weather model.

There is no external request, so there is no upstream API failure or circuit breaker event to handle.

## What Could Be Improved?

This is the most visibly incomplete of the five sources.

### Easter-Linked Holidays Are Missing

Good Friday and Easter Monday are explicitly not included.

The code notes that these dates should be calculated from Easter, but the current implementation does not yet include an Easter-date algorithm or calendar library.

That matters because these holidays can significantly affect demand patterns, especially when they create long weekends and widespread business closures.

### State-Specific Holidays Are Missing

The current table covers only a national baseline.

It does not include the full set of state-specific holidays, such as:

* Melbourne Cup Day in Victoria
* State-specific Labour Day dates
* Other regional holidays

As a result, every region is currently under-flagged relative to its actual calendar.

### The Fix Is Relatively Low-Risk

Compared with the other integrations, improving this source is straightforward.

It requires:

* An Easter-date calculation
* A complete annual holiday list from AEMO, or
* A small per-state holiday table

The changes can remain isolated within the holiday module without introducing a complicated authentication or network-dependency problem.

---

# How All Five Sources Come Together

All five sources enter the shared ingestion pipeline described in `ingestion.md`:

```text
Circuit breaker
        ↓
DuckDB staging
        ↓
R2 or MinIO snapshot
        ↓
Idempotent Postgres load
        ↓
dbt transformation
```

However, combining these sources introduces several important details.

## Cross-Source Joins Use “As Of” Matching

The sources do not all publish data at exactly the same timestamps.

For example:

* AEMO reports demand every five minutes.
* BoM reports hourly observations.
* OpenElectricity has its own generation-mix cadence.
* WEM price data is only available every 30 minutes.

An exact timestamp join would leave most demand rows without weather or generation data.

EcoLens therefore uses an “as-of” join:

> For each demand timestamp, use the most recent source reading at or before that timestamp.

This approach reflects how the data actually arrives and avoids discarding useful context simply because two providers use slightly different reporting schedules.

## Every Ingestion Run Is Logged

Each ingestion run, whether successful or failed, is recorded in:

```text
meta._ingest_log
```

This log also supports the public data-quality summary.

For example:

* A failed run counts as a failed test.
* A run with detected anomalies is marked as warned.
* Consecutive failures appear as open risks on the dashboard.

This means the data-quality view is built from the ingestion system itself rather than from a separate monitoring layer added afterward.

## The Circuit Breaker Is Shared Infrastructure

All five sources use the same Redis-backed circuit breaker.

The current behavior is:

* Five consecutive failures trip the breaker.
* The system waits 60 seconds before attempting a half-open retry.

This shared implementation ensures that different upstream sources degrade consistently instead of each having its own slightly different failure-handling logic.

---

# Cross-Cutting Improvements Worth Prioritizing

Looking across all five sources, the same themes appear repeatedly.

## 1. Silent Degradation Is the Main Recurring Risk

Several serious incidents had the same basic pattern:

* AEMO NEM's live URL was invalid.
* WEM's synthetic fallback could remain active.
* OpenElectricity's missing API key produced zero rows.
* The pipeline reported something close to “success, nothing new.”

The common problem was not necessarily that the system failed.

It was that the system failed in a way that looked normal.

A source-agnostic freshness check would help:

> Track the last successful ingestion of a real, non-synthetic row per source, rather than tracking only the last successful job execution.

That would detect silent degradation much earlier.

## 2. Assumptions About External Data Are Often Wrong

The OpenElectricity integration demonstrated how easily assumptions can fail:

* Fuel names were different from expected.
* Units were different.
* Timestamp semantics were different.
* Region filtering behaved differently than assumed.

These issues were discovered by checking real API responses.

A scheduled suite of sanity checks against real endpoints—not only mocks—could catch future drift much earlier.

Useful checks might include:

* Plausible value ranges
* Expected timestamp windows
* Non-identical regional totals
* Presence of major fuel categories
* Correct unit magnitudes
* Freshness thresholds

## 3. Historical Backfills Need Their Own Design

Every source has a different historical-data strategy:

* NEM uses DispatchIS and MMSDM archives.
* WEM downloads individual daily files.
* BoM uses Open-Meteo as a historical substitute.
* OpenElectricity relies on its own API behavior and retention.
* Holidays use a locally maintained calendar.

None of the providers offers a perfectly consistent historical interface.

That means backfilling cannot be treated as a small extension of live ingestion.

For any future sixth source, the design should explicitly ask:

> **How will this source be backfilled, and what happens when its original historical data is no longer available?**

That question deserves to be answered at the beginning of the integration, not after the live path is already working.

---

# Final Takeaway

EcoLens depends on five sources, but each source has a different role:

* **AEMO NEM** provides the main demand and price signal.
* **AEMO WEM** brings in Western Australia's separate grid.
* **OpenElectricity** explains the generation mix and emissions.
* **BoM** provides weather context.
* **AEMO's holiday calendar** explains predictable changes in demand behavior.

The difficult part is not simply fetching data.

The difficult part is making data from different providers agree on:

* Time
* Units
* Regions
* Missing values
* Historical coverage
* Failure behavior
* Data freshness

The most important lesson is that a pipeline can be technically operational while still producing misleading results.

A job that completes successfully is not necessarily a healthy data source.

EcoLens becomes more trustworthy when it makes those distinctions visible—especially when the data is incomplete, stale, synthetic, or based on an imperfect historical substitute.
