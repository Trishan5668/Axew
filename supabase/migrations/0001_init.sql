-- 0001_init.sql
-- Baseline migration. AXEW is local-first; cloud features (auth/billing/OpusClip)
-- are opt-in via the AXEW_CLOUD_ENABLED feature flag. This migration only
-- enables required Postgres extensions so subsequent migrations apply cleanly.

create extension if not exists "pgcrypto";
create extension if not exists "uuid-ossp";
