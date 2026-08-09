# ADR-0010 — Force-App Extraction: Standalone Repo, Local Dev Stack, Electron Packaging

- **Status:** Proposed
- **Date:** 2026-08-09
- **Deciders:** Maintainer + Claude (architecture discussion)

## Context

`apps/force-app/` (backend, web, backup-server) is a Windows-only, hardware-tied
recording and plotting client — NI-DAQ acquisition, LabAmp control — built
against the same Directus instance as the core LIMS, but currently living
inside the D1-Database monorepo alongside a very different stack
(Postgres/Redis/Minio/Directus/Ollama via `docker-compose.yml`).

Directus and Postgres run on a separate physical machine (`d1-server`),
reachable from the development machine only over Tailscale. This creates a
concrete development bottleneck: when force-app work requires a schema or
data fix, there is no way to iterate on backend + database together from the
dev machine — either the live `d1-server` instance has to be modified
directly (no dev/staging isolation, real risk to production data), or backend
work proceeds on assumptions about a schema that can't be inspected or
changed from where the work is happening.

Independently, this constraint surfaced a second problem while investigating
it: a duplicate ~2000-line `ForceDashboard.vue` implementation exists in two
places — `core/extensions/d1-force-dashboard/` (a Directus extension,
deployed on `d1-server`) and `apps/force-app/web/src/force/` (the standalone
app). The two have already drifted apart (different imports, different local
state) despite being near-identical forks.

The longer-term goal is to package force-app as an Electron desktop app (no
Docker on end-user machines) with auto-update, so it can be pushed to
field-deployed recording PCs without manual `git pull`s. force-app currently
has no CI wiring in the monorepo (`.github/workflows/ci.yml` has no reference
to it).

## Decision

This direction was discussed and is agreed on for planning purposes; the
migration itself has not yet been executed. Recommended sequence:

1. **Stand up a local, disposable Directus + Postgres dev stack** (Docker,
   dev-machine only — never shipped to end users) seeded from `db/migrations`
   plus a small anonymized seed. This is what actually solves "can't reach
   the database": schema changes needed to support force-app get authored and
   tested against a throwaway instance, then promoted to `d1-server` by
   applying the same migration files there once validated.
2. **Extract `apps/force-app` into its own repository.** The one dependency
   that must survive the split is the Directus schema. Treat `db/migrations`
   (or a generated schema snapshot / OpenAPI-derived TS types) as a versioned
   contract that force-app's repo consumes on a deliberate cadence — copied
   and updated when touched, not live-coupled to the monorepo.
3. **Resolve the `ForceDashboard` duplication as part of the split, not
   after.** Decide whether `core/extensions/d1-force-dashboard` stays as the
   "view historical data inside the Directus admin UI" surface while
   force-app owns only live recording, or whether one implementation absorbs
   the other. Shipping the split with the drift still unresolved just
   preserves it under two repos instead of one.
4. **Package the existing Python recorder backend as a PyInstaller-frozen
   sidecar binary**, spawned/health-checked/restarted by Electron's main
   process in place of the current Windows Scheduled Task. The backend is
   already Windows-only (`nidaqmx`, direct LabAmp protocol handling) so this
   is a packaging change, not a platform change — no Docker required on
   client machines.
5. **Ship updates via `electron-builder`'s `autoUpdater`**, with the feed
   hosted either as static files behind the Caddy proxy already running on
   `d1-server`, or via private GitHub Releases.

**Sequencing:** do (1) and (2) together first — cheap, reversible, and the
part that actually unblocks day-to-day development; (3) happens as part of
(2). Treat (4)–(5), the Electron packaging, as a distinct later phase once
the repo split has settled. Don't attempt all of this in one pass.

## Alternatives considered

### (a) Grant direct development access to the live `d1-server` instance

Skip the local stack; work against the real Directus/Postgres over Tailscale.

Not adopted as the primary approach because it doesn't solve the underlying
problem — there is still no isolation to trial and discard schema changes
safely, and mistakes affect real data immediately. It remains a useful
*complement* once a local stack exists (e.g. a read-only staging instance on
`d1-server` for testing against realistic data volumes a synthetic seed won't
reproduce), but is not a substitute for local iteration.

### (b) Partial extraction via git subtree/submodule, keep one repo

Use a subtree or submodule to give force-app semi-independent versioning
without a full split.

Ruled out: adds subtree-merge / submodule-pin tooling complexity without
solving the actual blocker (database reachability), and doesn't cleanly
enable independent CI or release versioning, which is the real motivation for
a separate repo.

### (c) Rewrite the recorder backend in Node/TypeScript to avoid a Python sidecar

Avoids bundling a second language runtime inside the Electron app.

Ruled out: the backend's value is in already-working, tested hardware
integration (`nidaqmx`, LabAmp protocol). A rewrite is large, high-risk, and
buys nothing that bundling the existing binary as a PyInstaller sidecar
doesn't already achieve at far lower cost.

## Consequences

### Positive

- A disposable local database removes the two-machine reachability
  constraint entirely for day-to-day schema + backend iteration.
- force-app becomes independently versioned and CI-able — a prerequisite for
  Electron auto-update to field machines, which can't happen from inside the
  monorepo's release cadence.
- Forces an explicit decision on the dashboard duplication instead of
  letting the two copies keep drifting silently.
- Electron packaging becomes a mostly mechanical step once the schema
  contract and repo boundary are settled: the acquisition backend's logic
  doesn't change, only how it's launched and updated.

### Negative / Costs

- The schema contract (copied migrations or generated types) requires an
  explicit sync step going forward — it will not update itself and can drift
  if forgotten, trading one kind of coupling for another, lower-frequency one.
- A local Directus + Postgres stack is new dev-machine setup and maintenance
  (for the maintainer/Claude only, not end users).
- Sidecar lifecycle management, error surfacing to the Electron UI, and
  eventual code-signing are real engineering work, separate from and after
  the repo split — not a one-afternoon task.
- Splitting the repo is hard to fully reverse (history, issues, PR links) and
  should be executed deliberately once the sequence above is agreed, not
  incidentally alongside other work.

## Open decisions (not yet resolved)

- `core/extensions/d1-force-dashboard` vs `apps/force-app/web/src/force`:
  merge, retire one, or keep both with an explicit ownership split?
- Exact mechanism for syncing the schema contract across repos — copied
  migration files, generated OpenAPI/TS types, or a small shared package.
- Where the Electron auto-update feed is hosted — Caddy on `d1-server` vs
  private GitHub Releases.
- CI setup for the new force-app repo (none exists for it today).

## References

- Architecture discussion, 2026-08-09 (this ADR records that discussion).
- `apps/force-app/` — current implementation to be extracted.
- `core/extensions/d1-force-dashboard/` — the duplicate dashboard.
- `db/migrations/` — schema source of truth (106 migrations as of this ADR).
- `docker-compose.yml` — current full-stack dev environment
  (postgres/redis/minio/directus/workers/ollama/filter-service/proxy).
