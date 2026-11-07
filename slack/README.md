# slack

Trợ lý BOA: a Slack bot that lets staff talk to BOA from Slack. It is a client of the gateway, like the web UI: every call goes through `/api/sessions/*` with the token of the person who wrote, so Slack never grants more than the web does.

Plan and progress: [docs/plan/plan-slack-chatbot.md](../docs/plan/plan-slack-chatbot.md).

**Status:** gateway client, chat bridge, approval cards and the web-like thread (timeline, answers, link to the web) are in. Still to do: a run against a real Slack app (end to end).

## Create the Slack app

1. At <https://api.slack.com/apps> choose **Create New App → From a manifest**, pick the workspace and paste [manifest.json](manifest.json). It sets the scopes, the `message.im` and `app_mention` events, interactivity, Socket Mode and the `/boa` command.
2. **Basic Information → App-Level Tokens**: create a token with the `connections:write` scope. This is `SLACK_APP_TOKEN` (`xapp-…`).
3. **Install App**: install to the workspace. The **Bot User OAuth Token** is `SLACK_BOT_TOKEN` (`xoxb-…`).

Socket Mode means the bot opens the connection to Slack itself: no public URL, no published port.

## Configuration

Put the variables below in the root `.env` (the root `.env.example` lists them); `docker compose` passes them to the bot.

| Variable | Meaning |
| --- | --- |
| `SLACK_BOT_TOKEN` | `xoxb-…`; required unless `SLACK_DRY_RUN` |
| `SLACK_APP_TOKEN` | `xapp-…`; required unless `SLACK_DRY_RUN` |
| `SLACK_TOKEN_KEY` | 32 bytes, base64 (`openssl rand -base64 32`); encrypts refresh tokens in the database |
| `SLACK_DATABASE_URL` | Postgres; compose defaults to the `db` service. To use another (e.g. Neon) set it in the root `.env` |
| `NEXUS_URL` | gateway base URL; compose sets `http://gateway:8080` |
| `NEXUS_PROVIDER` | model provider for new sessions, default `anthropic` |
| `BOA_WEB_URL` | optional web base URL (e.g. `http://localhost:3000`); set, every answer has a **Mở trên web** button to `/rooms?session=<id>` |
| `SLACK_DRY_RUN` | `1` replaces Slack with the console: type `<user> <text>` lines on stdin and read what the bot would send on stdout (see below) |

The bot exits at start with the list of missing or malformed values. Messages name the variable, never its value.

Keep `SLACK_TOKEN_KEY` out of git. Losing it invalidates every link; people just link again.

## Linking an account

Flow: sign in on the web, open Settings → Account and press the Slack link button to get a one-time code (valid 10 minutes), then send `/boa link <code>` to the bot. The bot never sees the password; it stores only a refresh token for that person, encrypted, and acts with their rights. With the code it sends the Slack handle, user id and workspace from the `/boa` payload, so the web can show which Slack account is linked (display only; the full name needs the `users:read` scope, without it the web shows the handle). Linking again from the same Slack account revokes the session of the earlier link.

## Run

```bash
docker compose up --build slack    # with the SLACK_* variables set in the root .env
cd slack && go test -race ./...    # unit tests, no network
```

`internal/store` also has a contract test against a real Postgres. Point `SLACK_TEST_DATABASE_URL` at a throwaway database (its `slack_*` tables are emptied) to run it; without the variable that part is skipped.

`internal/render` keeps the bot in step with the web in two ways. `testdata/*.json` are real sessions (traces dropped, names and addresses replaced) and `testdata/*.golden` is what the bot shows for each: the timeline, the answer and the approval card. After a deliberate change, run `go test ./internal/render -run TestGolden -update` and read the diff. `labels_test.go` reads the label tables of `frontend/src` (agent names, review and failure texts, action titles) and fails when they differ from the Go copies in `labels.go`; it is skipped when the frontend is not beside `slack/`.

## Layout

| Path | What |
| --- | --- |
| `cmd/bot/` | wiring and signal handling |
| `internal/config/` | environment → `Config`, validated at start |
| `internal/store/` | pgx store (`accounts`, `threads`, `handled`) with `schema.sql`, plus an in-memory twin for tests |
| `internal/secret/` | AES-GCM sealing of refresh tokens |

## Using it

- Send the bot a direct message. An @mention in a channel runs no agent: the bot answers only the sender (ephemeral) and points them to a direct message, so answers (orders, customer emails) never land where others can read them. Each Slack thread is one conversation (one session on the web); reply inside the thread to follow up or to answer a question the bot asked.
- A new room records where it came from: the bot sends `origin` `{kind: "slack", channel, thread_ts, permalink}` with `POST /api/sessions` (the permalink from `chat.getPermalink`, left out if Slack gives none), so the room is `source: "slack"` and admins can open the thread from the web. A room opened again because the old one is full keeps the same thread.
- `/boa link <code>`, `/boa unlink`, `/boa status`, `/boa help`. Answers to slash commands are visible only to you.
- Someone who has not linked gets instructions and no agent runs. A linked person gets exactly the rights they have on the web, and the session shows in their own list there.
- A thread reads like the room on the web. While the run goes on, the bot's first reply is a timeline of milestones (who Jev chose, the Coordinator's plan, each step's start, answers, reviews, redos, failures and skips) with what is happening now; it stays in the thread afterwards as the record of the run. The answer comes as a new message, built from the agent's checked `result` as the web builds it (claim keys and `**` removed, "Cần xác nhận:", "Đề xuất:", drafts, "Chi tiết"; `DOC-ID#khoản` citations kept).
- A request that needs approval (for example sending an email to a customer) ends on a card, a message of its own after the answer, with the details and **Duyệt** / **Từ chối** buttons. The click goes to the gateway with the token of whoever clicked, so only the person who made the request can decide; anyone else is told so. The card then shows what happened per action (done, failed, or unknown) and when the decision was made. A second click does nothing.

## Dry run

With `SLACK_DRY_RUN=1` the bot needs no Slack app. Against a running gateway (provider `fake` needs `AI_ALLOW_FAKE=1` on ai-service; set `NEXUS_PROVIDER=fake`):

```
U1 /boa link <code from the web>
U1 how long do I have to refund an order?
U1 >1.000002 order 5            # a reply inside the thread that started at ts 1.000002
U1 !approve 7 1.000002 1.000003 # click Duyệt (!reject: Từ chối): session id, thread ts, card ts
```

## Layout

`internal/nexus` (gateway client: per-person tokens, rotation, SSE), `internal/bridge` (the flow), `internal/render` (Vietnamese text), `internal/slackio` (Socket Mode and the console), `internal/store`, `internal/secret`, `internal/config`.
