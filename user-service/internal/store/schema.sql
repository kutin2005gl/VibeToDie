-- user-service schema, applied by the service on every start (idempotent), so an existing
-- database volume gets it too, not only a fresh one.

CREATE TABLE IF NOT EXISTS users (
    -- Text, not uuid: the id arrives as X-User-Id and a malformed one must read as "not found".
    id            TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    -- Stored lowercased by the service, so the unique key is case-blind.
    email         TEXT        NOT NULL UNIQUE,
    -- argon2id in PHC string format.
    password_hash TEXT        NOT NULL,
    name          TEXT        NOT NULL,
    departments   TEXT[]      NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     TEXT        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    -- One sign-in: rotation keeps the family, reuse of a spent token revokes all of it.
    family_id   TEXT        NOT NULL,
    -- SHA-256 of the token; the token itself is only ever held by the client.
    token_hash  BYTEA       NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS refresh_tokens_family_idx ON refresh_tokens (family_id);

-- Where the sign-in came from ('web' or 'slack'), so the web can show and cancel the Slack link.
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'web';

-- The Slack account behind a Slack sign-in (one row per refresh token family, so rotation keeps it),
-- as the bot reported it when redeeming the code. Display only.
CREATE TABLE IF NOT EXISTS slack_accounts (
    family_id     TEXT        PRIMARY KEY,
    slack_user_id TEXT        NOT NULL,
    user_name     TEXT        NOT NULL DEFAULT '',
    real_name     TEXT        NOT NULL DEFAULT '',
    team_id       TEXT        NOT NULL DEFAULT '',
    team_domain   TEXT        NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE slack_accounts ADD COLUMN IF NOT EXISTS real_name TEXT NOT NULL DEFAULT '';

-- One-time codes that link a Slack account to a user: shown on the web, redeemed from Slack.
CREATE TABLE IF NOT EXISTS slack_link_codes (
    -- SHA-256 of the code; the code itself is only ever held by the person it was shown to.
    code_hash  BYTEA       PRIMARY KEY,
    user_id    TEXT        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ
);
