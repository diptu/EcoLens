# End-to-End Hybrid ML Pipeline Strategy


## Step-by-Step 30-Minute Resampling & Integration Strategy

Step 1: Establish the Master 30-Minute Temporal Spine
Create a continuous time grid running every 30 minutes from August 2025 onwards for each regional grid (NSW1, QLD1, VIC1, SA1, TAS1, WEM).

Step 2: Downsample 5-Minute Data to 30 Minutes
AEMO & OpenElectricity (Demand & Power): Aggregate the six 5-minute ticks within every 30-minute window.

For energy and demand values, take the mean or total over the interval.

For instantaneous power and prices, take the average (or the final reading of the window, depending on your modeling preference).

OpenElectricity Metrics: Ensure that if any 5-minute interval within the 30-minute window contained a null for renewable_proportion, the aggregated 30-minute window handles it safely rather than defaulting to zero.

Step 3: Match Native 30-Minute Data Directly
BoM Weather: Because your meteorological observations already operate on a 30-minute cadence, map them directly onto the master 30-minute spine with zero interpolation required.

Step 4: Broadcast Calendar and Holiday Flags
Map daily public holiday markers down to every 30-minute timestamp for that calendar day, ensuring all blocks within a holiday inherit the correct status.

Step 5: Feature Engineering on the 30-Minute Grid
Calculate historical lag features (e.g., lag of 1 step = 30 minutes ago, lag of 48 steps = 24 hours ago) and rolling averages directly on the 30-minute table.

Strip away raw logs and retain only the curated feature columns.

Step 6: Sync to NeonDB
Push only the clean, unified 30-minute feature records from  local DuckDB instance into  NeonDB (PostgreSQL) feature store. Downstream ML models will then train and serve predictions on a clean, consistent half-hourly cadence.