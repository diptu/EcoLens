-- 0013_meta_landing_blobs.sql — Postgres-backed alternative to the S3/MinIO
-- audit-trail landing bucket, used when `Settings.landing_backend ==
-- "postgres"` (see `pipeline/landing.py`). Same role as the Parquet
-- objects under `s3://ecolens/raw/{source}/...`: one row per landed
-- batch, replayable via `load_to_postgres`.

CREATE TABLE IF NOT EXISTS meta._landing_blobs (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    key         text        NOT NULL UNIQUE,
    body        bytea       NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
