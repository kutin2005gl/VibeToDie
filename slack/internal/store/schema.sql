-- slack bot schema, applied by the bot on every start (idempotent).

-- One row per linked Slack user. The refresh token is the bot's only credential for that
-- person; it is stored encrypted (AES-GCM) and rotated on every refresh.
CREATE TABLE IF NOT EXISTS slack_accounts (
    slack_user_id     TEXT        PRIMARY KEY,
    user_id           TEXT        NOT NULL,
    refresh_token_enc BYTEA       NOT NULL,
    linked_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One Slack thread = one session (room).
CREATE TABLE IF NOT EXISTS slack_threads (
    channel    TEXT        NOT NULL,
    thread_ts  TEXT        NOT NULL,
    session_id TEXT        NOT NULL,
    user_id    TEXT        NOT NULL,
    state      TEXT        NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (channel, thread_ts)
);

-- Slack redelivers an event when the bot is slow; the first insert wins and the rest are skipped.
CREATE TABLE IF NOT EXISTS slack_handled (
    channel    TEXT        NOT NULL,
    ts         TEXT        NOT NULL,
    handled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (channel, ts)
);
