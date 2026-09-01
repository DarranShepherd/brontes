# Brontes

A deterministic, local-first charging ledger and policy service for a VW ID.Buzz.

> **Hermes interprets and communicates. Brontes decides, records and reconciles.**

## Phase 1: read-only foundation

This initial milestone provides a production-shaped, dependency-light Python service with:

- SQLite persistence for vehicle observations, Zappi observations, charge intervals and sessions;
- read-only adapter boundaries for VW EU Data Act, MyEnergi Zappi and Octopus Agile;
- deterministic home-session detection, interval metering and Agile settlement-period costing;
- odometer-based aggregation of home charging into a logical session;
- Road Trip `x-callback-url` creation, HTTPS handoff and a durable Hermes-notification outbox;
- a local HTTP/JSON API for status, observation ingestion and notification delivery.

No secret, vehicle-control or MyEnergi schedule-write path is enabled in this milestone. The service never sends a notification until a configured Hermes notification endpoint accepts it.

## Architecture

```text
adapters (read-only) -> SQLite ledger -> deterministic services -> API/outbox
                                                 |
                                       Road Trip callback + Hermes event
```

All timestamps are stored in UTC. The API serialises ISO-8601 timestamps with a `Z` suffix.

## Quick start

Brontes targets Python 3.13+ and intentionally uses only the standard library for the initial foundation.

```bash
python3 -m unittest discover -s tests -v
python3 -m brontes
```

The server listens on `127.0.0.1:8088` by default. Set `BRONTES_DATABASE_PATH` to select a SQLite file; otherwise it uses `./data/brontes.sqlite3`.

## Configuration

Non-secret behaviour is configured through environment variables. Integration credentials are read from the user's `~/.netrc`, never from source-controlled files or environment variables. Brontes will use explicit, documented machine names per adapter; it does not log, return, or copy credential values. MyEnergi credentials already use this store. Ask the operator to add any new machine entry before enabling a new live adapter.

| Variable | Default | Purpose |
| --- | --- | --- |
| `BRONTES_DATABASE_PATH` | `data/brontes.sqlite3` | SQLite ledger path |
| `BRONTES_HOST` | `127.0.0.1` | Local API bind host |
| `BRONTES_PORT` | `8088` | Local API port |
| `BRONTES_HERMES_NOTIFICATION_URL` | unset | Local Hermes-mediated notification endpoint |
| `BRONTES_OCTOPUS_PRODUCT_CODE` | `AGILE-24-10-01` | Octopus Agile product used for settlement pricing |
| `BRONTES_OCTOPUS_TARIFF_CODE` | `E-1R-AGILE-24-10-01-B` | Octopus Agile regional tariff used for settlement pricing |
| `BRONTES_TELEGRAM_TARGET` | `telegram` | Hermes notification target for completed sessions |

The `BRONTES_HERMES_NOTIFICATION_URL` must be a local, authenticated Hermes gateway or bridge endpoint. It is not a Telegram Bot API token or a public endpoint. Configuration and account setup remain an explicit deployment step.

## Automatic home charging workflow

The recurring Zappi poll records meter-counter deltas as home charging
intervals and retrieves the matching public Octopus Agile settlement prices.
Budget Charge pauses remain separate intervals under one logical session.
Brontes finalises and queues that logical session only when either:

- Zappi changes from connected to disconnected; or
- a fresh VW observation reports an increased odometer.

It deliberately does **not** close a session merely because charging pauses or
the SoC reaches 80%, because Budget Charge may resume later and the configured
vehicle limit can differ. Pending notifications are persisted, then delivered
through `hermes send` to the configured Telegram target; a failed delivery
remains pending for retry by the next poll.

## Road Trip handoff

Telegram will not make a custom `desroadtrip://` URL tappable. The repository
therefore includes a minimal static handoff page at
`site/roadtrip/index.html`, deployed by `.github/workflows/deploy-pages.yml`.

Brontes wraps each Road Trip callback in an HTTPS link to that page. The
callback itself is Base64URL-encoded in the URL fragment, which browsers do
not send to GitHub Pages. The static page decodes only valid Road Trip
`x-callback-url` callbacks and opens the local Road Trip app. No credentials,
ledger data or per-session pages are published to the repository or Pages.

The expected public handoff address is:

```text
https://darranshepherd.github.io/brontes/roadtrip/
```

Before the first deployment, set the repository's **Settings → Pages → Build
and deployment → Source** to **GitHub Actions**. This is a deliberate
repository setting and is not changed by the workflow itself.

## Local API

- `GET /health` — service, ledger and integration configuration health.
- `GET /status` — current vehicle/Zappi state and pending notifications.
- `POST /observations/vehicle` — persist a validated VW-derived observation.
- `POST /observations/zappi` — persist a validated Zappi-derived observation and process home intervals.
- `POST /reconcile/odometer` — close eligible home sessions when the vehicle has been driven.
- `POST /notifications/deliver` — try delivery of persisted pending notifications.

The ingestion endpoints are deliberately generic. The next milestone wires the live, read-only VW EU Data Act and MyEnergi polling clients to them.

## Safety and operational boundaries

- Brontes does not use an LLM in its decision path.
- Observation data is committed before derived sessions and notifications are created.
- Notification failure never changes charge correctness; messages remain pending for later retry.
- The local API binds to loopback by default.
- Do not commit credentials or session state.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src
```

See [ROADMAP.md](ROADMAP.md) for planned increments and verification criteria.
