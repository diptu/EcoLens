# Todo's

## Book keeping

[] save raw and raw.marts in seperate database uing seperate Database_URL (so taht i can save 2*512 mb data)
[] update services/ingestion/scripts/select_features.py based on services/forecast-api/notebooks/feature_selection.ipynb and update warehouse pipeline accordingly.

## operational-tasks

[] *Pipeline Operations*: Implement all pipeline operations , test with 30 min, single day, 1 month for each of nem,wem,bom,oe, holiday

[] *Model Operations* : Update with LSTM model for now

[] *Active Tasks*: Show all active task with their status.

[] *Scheduled Operations* : Update with all cron job (data fetch, remove older data from postgresql)

[] *Recent Training Runs* : Show 3 Recent Training Runs if training run is>=3.

[] *Model Training & Tuning* : fine tune the model on recent n-hours data.

[]*System Commands* Rebuild Features should run featrure selection script and select cloumns for forecasting models based on raw data and upload in raw.marts schem.

[] *Vacuum Database*: Vacuum Database should run cronjob using celery to clear older data defiend in .env file.

[]*System Diagnostics* : System Diagnostics should show which sytem are healthy and which are not.