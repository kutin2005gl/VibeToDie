package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/jackc/pgx/v5/pgxpool"

	"nexus/slack/internal/bridge"
	"nexus/slack/internal/config"
	"nexus/slack/internal/nexus"
	"nexus/slack/internal/secret"
	"nexus/slack/internal/slackio"
	"nexus/slack/internal/store"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load(os.Getenv)
	if err != nil {
		log.Fatal(err)
	}
	box, err := secret.New(cfg.TokenKey)
	if err != nil {
		log.Fatal(err)
	}

	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("connect db: %v", err)
	}
	defer pool.Close()
	st := store.New(pool)
	if err := st.Migrate(ctx); err != nil {
		log.Fatalf("migrate: %v", err)
	}

	var events slackio.Events
	var poster slackio.Poster
	if cfg.DryRun {
		// No Slack: read events from stdin and print what would be sent (see slackio.Console).
		console := &slackio.Console{In: os.Stdin, Out: os.Stdout}
		events, poster = console, console
	} else {
		socket := slackio.NewSocket(cfg.BotToken, cfg.AppToken)
		events, poster = socket, socket
	}
	client := nexus.New(nexus.Config{BaseURL: cfg.NexusURL, Store: st, Box: box})
	b := &bridge.Bridge{Gateway: bridge.FromNexus(client), Store: st, Poster: poster, Provider: cfg.Provider,
		WebURL: cfg.WebURL}

	log.Printf("slack bot ready (gateway %s, provider %s, dry run %t)", cfg.NexusURL, cfg.Provider, cfg.DryRun)
	if err := events.Run(ctx, b); err != nil {
		log.Fatalf("slack: %v", err)
	}
	log.Print("slack bot stopping")
}
