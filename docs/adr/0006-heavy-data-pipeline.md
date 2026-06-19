# ADR-0006 — Direct-to-MinIO heavy-data pipeline

- **Status:** Accepted
- **Date:** 2026-06-18
- **Deciders:** Maintainer + Claude (Phase 4 planning)

## Context

Phase 4 introduces ingestion of 10–100 GB force-sensor files produced by the
FAST rig and associated equipment. These files are stored in the D1F binary
format (`.d1f`): a 64-byte header followed by float32 row-major data across six
channels (Fx, Fy, Fz, Mx, My, Mz).

Files at this scale cannot flow through the Directus API. The Directus adapter
buffers uploaded content in its own disk-I/O layer before handing it off to
storage; routing a 50 GB file through that path would:

1. Saturate the Directus container's ephemeral storage.
2. Block all other API traffic on the same connection pool for the duration of
   the upload.
3. Exceed the memory envelope of the container on any reasonable deployment.

At the same time, processing logic (streaming statistics, SVG plot generation)
must remain server-side and centralised. Pushing that logic to the client would
scatter implementation details across MATLAB scripts, Python clients, and future
acquisition software, creating a maintenance and auditability problem.

The system already has MinIO (S3-compatible object storage) as its binary-data
substrate (see `docs/api-contract.md` §11). The question is how to route large
uploads to it without touching the Directus layer.

## Decision

Large force-sensor files are uploaded **directly to MinIO** via presigned
multipart URLs. Metadata registration and post-processing are decoupled and
sequenced as follows:

1. **Presign** — the client calls `POST /api/presign-upload` on the
   heavy-data worker to obtain a set of presigned part URLs and an upload ID.
2. **Upload** — the client PUTs each part directly to MinIO using the presigned
   URLs. The core API and Directus are not in the data path.
3. **Complete** — the client calls `POST /api/complete-upload` on the worker to
   assemble the multipart upload in MinIO.
4. **Register** — the client creates a `test_sessions` record via the standard
   Directus API (`POST /items/test_sessions`), setting `file_storage_pointer` to
   the MinIO object URI and `status` to `pending_processing`.
5. **Webhook** — a Directus Flow fires on `test_sessions` item creation and
   POSTs to `http://heavy-data-worker:8080/api/webhook/session`.
6. **Queue** — the webhook handler enqueues a job on the `heavy-data` Redis
   queue (rq library) and returns HTTP 202 immediately.
7. **Worker** — a Python worker container dequeues the job, streams the `.d1f`
   file from MinIO in bounded chunks (never exceeding `WORKER_MEMORY_LIMIT_MB`
   in memory), computes summary statistics, generates an SVG plot via a strided
   read (at most 10 000 points), and writes results back via
   `PATCH /items/test_sessions/{id}`.

The worker runs in `plugins/heavy-data-worker/` as a Docker Compose service. It
authenticates to Directus using the same static Operator machine token pattern
established in Phase 3 (`WORKER_DIRECTUS_TOKEN` environment variable). The
plugin contract is fully described in `docs/plugin-contract.md` in
adapter-agnostic terms.

## Alternatives considered

### (a) Directus file upload API

Directus exposes `POST /files` which can accept multipart file uploads and
forward them to a configured storage adapter (MinIO in this case). This was
ruled out because:

- Directus reads the entire upload into its adapter layer before writing to
  MinIO. For 10–100 GB files this is not viable within any reasonable container
  memory or disk budget.
- Simultaneous large uploads would starve the Directus process of file
  descriptors and CPU, degrading API responsiveness for all other clients.
- The Directus file API path is an internal adapter detail, not part of the
  stable contract defined in ADR-0002.

### (b) Client-side pre-processing

An alternative is to have the acquisition client (MATLAB, Python) compute
statistics and generate plots locally before uploading a summary record rather
than the raw file. This was ruled out because:

- Processing logic must be centralised. Distributing it across MATLAB scripts on
  equipment nodes makes version control, bug fixing, and algorithm changes
  operationally difficult.
- Some acquisition clients (embedded MATLAB, LabVIEW) have constrained compute
  environments unsuited to processing multi-GB float arrays.
- The raw `.d1f` file must be archived regardless of whether a client-side
  summary is produced; centralised re-processing against the raw archive is a
  core requirement.

## Consequences

### Positive

- **No memory spike in the core API.** Directus and PostgreSQL are not in the
  upload data path. Their resource envelopes remain predictable regardless of
  file size.
- **Scales to arbitrarily large files.** MinIO multipart upload supports
  objects up to 5 TB. The worker's streaming read keeps memory consumption
  bounded by `WORKER_MEMORY_LIMIT_MB` regardless of file size.
- **Plugin is swappable.** The worker contract (`docs/plugin-contract.md`) is
  Directus-agnostic. A replacement worker (different language, different
  algorithm) can be deployed without changing the schema or the client.
- **Consistent authentication model.** The worker reuses the static Operator
  machine token pattern from Phase 3; no new auth mechanism is introduced.
- **Async by default.** The webhook returns 202 immediately. Client UX is
  non-blocking; status polling against `test_sessions.status` tells the client
  when processing is complete.

### Negative / Costs

- **Operational complexity.** The pipeline now involves five components:
  Directus, PostgreSQL, MinIO, Redis, and the worker container. Each is a
  potential failure point. The runbook (`docs/runbooks/heavy-data-pipeline.md`)
  documents failure modes and recovery procedures.
- **MinIO is required.** The pipeline cannot function without a running MinIO
  instance and a bootstrapped bucket. There is no graceful fallback to local
  filesystem storage.
- **Redis is required.** The rq queue depends on Redis. A Redis outage causes
  webhooks to fail (the handler cannot enqueue jobs). Sessions will remain in
  `pending_processing` status; jobs do not self-heal without manual
  re-enqueuing.
- **Eventual consistency.** There is a window between file upload and worker
  completion during which `test_sessions.status` is `pending_processing` or
  `processing`. Clients must poll or watch the status field rather than
  expecting synchronous results.
- **Four-step client protocol.** Clients must implement presign → upload parts
  → complete → register rather than a single POST. This is handled by the
  provided Python client example; MATLAB clients will require a corresponding
  implementation.

## References

- ADR-0001: PostgreSQL is the durable core
- ADR-0002: Directus is a swappable adapter
- ADR-0005: Directus RBAC structure (machine user / Operator token pattern)
- `docs/plugin-contract.md` — full adapter-agnostic plugin interface
- `docs/runbooks/heavy-data-pipeline.md` — operational procedures
- `docs/api-contract.md` §11 — file storage URI convention
- `plugins/heavy-data-worker/` — worker container source
