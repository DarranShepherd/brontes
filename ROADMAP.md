# Brontes roadmap

## 0.1 — Read-only charging foundation (current)

- [x] Local, dependency-light Python package and loopback HTTP service shape.
- [x] SQLite ledger schema for raw observations, intervals, sessions, costs and notifications.
- [x] Road Trip `x-callback-url` generation.
- [x] Durable outbox with a Hermes-notification adapter boundary.
- [x] Deterministic home charging interval detection and odometer reconciliation.
- [x] Octopus Agile settlement-period costing from Zappi-delivered energy.
- [ ] Live, read-only VW EU Data Act polling after account configuration is supplied.
- [ ] Live, read-only MyEnergi Zappi telemetry after endpoint details are verified.
- [ ] Wire the local Hermes notification bridge to the default Telegram bot/profile.

**Acceptance criteria:** replayed observations do not double-count energy; a home session closes only after an odometer increase; notification delivery is retryable; no write operation is invoked against VW, MyEnergi or Telegram.

## 0.2 — Home charging resilience

- [ ] MyEnergi ChargeSchedules read adapter.
- [ ] Brontes-owned Single Charge model and read-only diagnostics.
- [ ] Concurrency-safe collection replacement write path, disabled unless explicitly enabled.
- [ ] Low-SoC policy simulation and audited decisions.
- [ ] Explicit operator enablement for MyEnergi schedule writes.

## 0.3 — Away charging and corrections

- [ ] VW-derived away charging detection and AC/DC classification.
- [ ] Immediate DC end reconciliation with uncertainty modelling.
- [ ] Structured manual charge/correction API.
- [ ] Provenance-preserving candidate matching and ambiguity responses.

## 0.4 — Operational deployment

- [ ] Credential-free deployment configuration using `~/.netrc` for integration credentials.
- [ ] systemd unit and restart-recovery runbook.
- [ ] Backup/restore procedure for SQLite ledger.
- [ ] Integration-contract tests using captured, redacted fixtures.

## Explicitly deferred

- Volkswagen write operations, including pre-conditioning and charge control.
- Calendar and journey-aware SoC planning.
- Dedicated graphical UI.
- An independent Telegram bot.
