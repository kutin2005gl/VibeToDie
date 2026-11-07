FROM golang:1.27-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/slack-bot ./cmd/bot

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/slack-bot /slack-bot
# Socket Mode: the bot dials out to Slack, so there is no port to expose.
ENTRYPOINT ["/slack-bot"]
