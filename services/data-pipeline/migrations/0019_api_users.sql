-- 0019_api_users.sql — real credential store backing
-- `POST /v1/auth/token` (`TODO.md`'s IAM section item 1: "nothing in the
-- project issues tokens... something has to mint the sub/role JWTs
-- data-pipeline now expects").
--
-- `role` is constrained to the same two values `ecolens.api.security.
-- ROLES` already hardcodes — this table is the real backing store for
-- who gets issued which role's token, not a parallel, independent role
-- vocabulary. `password_hash` is bcrypt (`ecolens.auth.service`), never
-- the plaintext. No per-source/per-team scoping columns here on purpose
-- — that's a real, larger authorization feature (fine-grained resource
-- scoping, not just "which of 2 roles") this migration doesn't attempt;
-- see `TODO.md`'s IAM section for that gap tracked honestly.

CREATE TABLE IF NOT EXISTS meta.api_users (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    username      text        NOT NULL UNIQUE,
    password_hash text        NOT NULL,
    role          text        NOT NULL CHECK (role IN ('admin', 'analyst')),
    is_active     boolean     NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);
