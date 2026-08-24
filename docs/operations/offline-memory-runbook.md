# Offline memory operations

## Backup and migration

Stop Memoli before a filesystem backup, then copy `memory.db`, its `-wal`/`-shm`
companions when present, and the configured Trajectory database/payload directory.
Keep the files as one recovery set. Start a copy first after upgrades; schema
migrations are transactional and unknown future versions fail closed.

## Phased enablement

1. Keep `consolidation_enabled=false`; migrate the database and verify keyword
   recall.
2. Enable SQLite Trajectory capture and Episode projection.
3. Configure the extractor credential environment variable. In deterministic mode,
   expect only explicit marked lines; implicit learning requires the structured
   OpenAI-compatible Extractor.
4. Inspect Candidate and governance backlogs. Confirm the `memory-governor` Profile
   and Policy Gate versions.
5. Enable Card statement projection and embeddings; enable auto-scan last.

Never enable auto-scan unless completed Trajectories use stable session/scope IDs,
redaction is configured, and remote extractor privacy policy permits the configured
sensitivity ceiling.

## Diagnosis and recovery

`/memory` shows component state and `/status` includes runtime state.
`/memory candidates` lists user-review work. Memory diagnostics expose only counts,
oldest timestamps, lease counts, attempts, dead-letter counts, and error class names;
they do not expose Candidate or provider response text.

Use `/memory recovery` to distinguish governance dead-letter jobs from quarantined
consolidation requests. Retry with `/memory retry-job <id> confirm` or
`/memory retry-request <id> confirm`; suppress an uncommitted request with
`/memory suppress-request <id> confirm`. A quarantined request older than 86400
seconds is displayed as `stale-dead-letter`, but TTL never retries, releases,
consumes, or replays it automatically. Force-release is an operator-only repository
API requiring actor and reason, and is allowed only when no Candidate was committed.
Expired active leases recover automatically.
Card and statement data are derived: rebuild their projection jobs from governed
Claims. Semantic vectors are also derived and can be rebuilt without changing
Claims, Card history, or Trajectories.

Internal projection state `ready` means completed/ready-output. Backlog counts only
`pending`, `retry`, and `running`; inspect dead-letter separately. Embedding provider
configuration failures and the historical Episode projection `KeyError` are outside
this trigger change. If the Episode error still reproduces independently, open a
separate bugfix change rather than changing memory authority data.

## Rollback

Disable consolidation and auto-scan first. The online Agent continues with existing
governed Claims and non-semantic recall. Disable embeddings independently if the
provider is unavailable. Restore the complete database backup only while the
runtime is stopped; never copy an older `memory.db` over a running WAL database.
Rolling back application code after schema v6 requires restoring a compatible full
backup; do not manually drop ledger tables. Suppressed/quarantined bindings and
governance dead-letter audit must be retained during rollback.
