# Brontes roadmap

## Delivered — read-only home charging workflow

- [x] Dependency-light Python 3.13 package, SQLite ledger and loopback HTTP
  service.
- [x] Read-only VW EU Data Act adapter through the existing CarConnectivity
  CLI, including SoC, odometer, charging state/type and reported power.
- [x] Read-only MyEnergi Zappi adapter using `~/.netrc` and Digest
  authentication, including connection state, charging state, power and charge
  energy counter.
- [x] Scheduled host polling: Zappi every 2 minutes and VW every 15 minutes.
- [x] Durable raw vehicle and Zappi observations.
- [x] Zappi meter-counter deltas persisted as idempotent, metered home charging
  intervals.
- [x] Read-only public Octopus Agile settlement-price retrieval and
  settlement-period cost calculation.
- [x] Budget Charge pause/resume consolidation: multiple intervals remain one
  logical home session until a deterministic session boundary.
- [x] Home-session closure on either Zappi unplug or a later increased VW
  odometer observation.
- [x] Retry of uncosted sessions after an Octopus outage.
- [x] Durable notification outbox and retry through `hermes send --to telegram`.
- [x] Road Trip HTTPS handoff, GitHub Pages deployment, exact target vehicle
  `Volkswagen ID.Buzz GTX`, percent-encoded callback values and Europe/London
  local date/time.
- [x] Unit tests for adapters, ledger idempotency, interval costing, split
  Budget Charge sessions, outage recovery, API and notification paths.

**Current acceptance criteria met:** repeated source intervals do not
 double-count; Budget Charge gaps do not prematurely close a session; unplugging
or later driving closes the session; missing Agile prices defer completion for
retry; notification delivery is persisted before sending and is not duplicated
on success; provider polling is read-only.

## Next — home charging resilience and low-SoC protection

- [ ] Read the MyEnergi ChargeSchedules collection and expose diagnostics.
- [ ] Model Brontes-owned Single Charges using the `brontes-buzz-` prefix.
- [ ] Implement serialized, collection-replacement-safe Single Charge writes:
  read full collection, preserve manual entries, write complete collection,
  re-read and verify.
- [ ] Implement configurable low-SoC protection:
  connected at home plus SoC at or below threshold creates or updates a
  Brontes-owned charge to the configured target by the local deadline.
- [ ] Keep all MyEnergi schedule writes disabled until explicit operator
  enablement and live verification.
- [ ] Improve handling and diagnostics for Zappi counter reset, unavailable
  telemetry and missing home meter history.

**Acceptance criteria:** an equivalent owned schedule is a no-op; manual
schedules are never changed; a concurrent collection change is safely retried;
all schedule writes are auditable and verified by a fresh read.

## Next — operational hardening

- [ ] Replace host-specific CarConnectivity default paths in `scripts/poll.py`
  with an explicit credential-free deployment configuration or installation
  wrapper.
- [ ] Add a systemd service/timer option and restart-recovery runbook, while
  retaining the current local scheduler deployment as a supported option.
- [ ] Add SQLite backup, restore and integrity-check procedures.
- [ ] Add captured, redacted provider-contract fixtures and integration tests.
- [ ] Extend health/status to include latest provider reads, Zappi state,
  current SoC/odometer, uncosted intervals and notification queue state.
- [ ] Add structured logging for state changes, retries and external failures.
- [ ] Add configurable retention/backup policy for local ledger data.

**Acceptance criteria:** a restart during an active charge retains all data and
never creates more than one completed session and one delivered notification; a
provider outage is visible in status and recovers without data loss.

## Next — away charging and user corrections

- [ ] Detect probable away charging from VW SoC increase while not connected to
  home Zappi.
- [ ] Classify AC/DC from reported charge type, then power, then safe inferred
  evidence; retain uncertainty when driving and charging are combined.
- [ ] Finalise away DC after confirmed charge end; retain away AC until odometer
  reconciliation.
- [ ] Estimate away energy/cost only with explicit provenance and configurable
  assumed AC/DC rates.
- [ ] Implement a structured manual charge-report API for Hermes.
- [ ] Match manual reports to recent candidate sessions deterministically;
  return ambiguity rather than guessing.
- [ ] Preserve original values and provenance in a correction audit trail.

**Acceptance criteria:** a short missed DC charge can be manually recorded once;
a correction supersedes an estimate without deleting it; two plausible matches
produce an ambiguity response; a completed DC notification is idempotent.

## Future — policy and user experience

- [ ] Hermes-facing read/status and controlled-operation API with complete
  validation.
- [ ] Monthly cost summaries, effective p/kWh and charging-efficiency analysis.
- [ ] Calendar-aware departure targets and journey-specific SoC planning.
- [ ] Volkswagen pre-conditioning or charge control, only if a separate,
  write-capable integration is verified and explicitly enabled.
- [ ] Ampernomics/export integration.

## Explicitly deferred

- Volkswagen write operations, including cabin pre-conditioning and charge
  control.
- Automatic journey planning and calendar integration.
- A dedicated Brontes graphical UI.
- An independent Telegram bot.
- A Brontes implementation of MyEnergi's Agile optimiser; MyEnergi remains the
  optimiser and Brontes accounts for observed delivery and actual prices.
