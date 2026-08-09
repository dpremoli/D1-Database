# ADR-0010 — Force-App: Shared Plotting Package, Repo Extraction, Electron Packaging

- **Status:** Proposed
- **Date:** 2026-08-09 (revised same day — see *Revision note*)
- **Deciders:** Maintainer + Claude (architecture discussion)

## Revision note

The first draft of this ADR framed the problem as **database reachability**: that
force-app development was blocked because Directus and Postgres live on
`d1-server` while development happens elsewhere. That framing was wrong and has
been removed. The equipment-connected development machine is on the same
tailnet as `d1-server` and already reaches Directus over it — `apps/force-app`
defaults `DIRECTUS_URL` to `https://d1-server.tail54eeb6.ts.net` and has been
working that way.

Correcting the premise changed three things:

- The **local disposable Directus + Postgres stack** dropped out of the critical
  path. Its only remaining justification is isolation for risky schema changes,
  which is better served — far more cheaply — by an actual database backup.
- The **repo split** kept its justification, but a different one: likely
  handover to another student or lab, plus an independent release cadence for
  desktop updates. Not reachability.
- The **dashboard duplication** turned out to be a 45-line divergence, not a
  genuine fork, which makes a shared package the obvious resolution and makes
  the split cheaper once it is done.

## Context

`apps/force-app/` (backend, web, backup-server) is a Windows-only,
hardware-tied recording and plotting client — NI-DAQ acquisition, LabAmp
control — built against the same Directus instance as the core LIMS, but
living inside the D1-Database monorepo alongside a very different stack
(Postgres/Redis/Minio/Directus/Ollama via `docker-compose.yml`).

**The two-machine constraint is permanent, and it is not a networking
problem.** The DAQ and LabAmp are physically wired to a development machine
that is not `d1-server` and will not become `d1-server`. Both machines are on
the same tailnet, so the database is reachable; what cannot be collapsed is the
hardware. Any plan that assumes force-app development can happen "next to the
database" is assuming something false. Development happens on the
equipment-connected machine, against Directus over Tailscale.

Three real drivers remain:

1. **Ownership is likely to diverge.** force-app may be handed to another
   student or another lab. GitHub cannot grant repository access to a
   subdirectory, so a shared boundary eventually becomes an access-control
   problem.
2. **Release cadence must diverge.** Field-deployed recording PCs need updates
   without manual `git pull`s, on a schedule unrelated to the LIMS server's.
   force-app has no CI wiring today — `.github/workflows/ci.yml` contains no
   reference to it.
3. **The plotting code has already drifted.** A near-identical
   `ForceDashboard.vue` exists in `core/extensions/d1-force-dashboard/` (a
   Directus module, bind-mounted live into the running container) and
   `apps/force-app/web/src/force/` (the standalone app).

On (3), the divergence was measured rather than assumed. `ForceDashboard.vue`
is 2039 lines in the extension and 2060 in the standalone app, and `diff`
reports only **45 changed lines**. They reduce to three environment concerns:

| Concern | Directus extension | Standalone app |
|---|---|---|
| Opening a record | `router.push('/content/…')` | `window.open(directusUrl + '/admin/content/…')` |
| Downloading an asset | cookie-authed `<a href="/assets/…">` | Bearer-authed fetch → blob |
| Layout density | roomier padding | tighter padding |

Plus one substantive difference: a **bug fix present only in the standalone
copy** (the operations list failing to self-filter on a deep link, with a
`scrollIntoView` for off-screen rows). The drift is running in the direction
that is hardest to notice — the Directus surface is the stale one. The same
pattern holds for `FrmCloud.vue` (674 vs 690), `ForceChart.vue` (392 vs 392),
`FrmOctree.vue` (372 vs 375) and five further shared files: roughly 4,000
duplicated lines in total.

Two further facts about the current deployment shape:

- **The standalone app is already served from `d1-server`.**
  `infra/caddy/Caddyfile` has a `handle_path /app/*` block serving
  `/srv/force-app` same-origin with Directus, reachable over Tailscale at
  `https://<node>.<tailnet>.ts.net/app/`.
- **The `/recorder/*` proxy points at the wrong machine for recording.** Caddy
  forwards it to `host.docker.internal:8200`, i.e. `d1-server`'s own host, but
  the recorder runs on the equipment machine. The browser surface can therefore
  plot history correctly but cannot drive a recording. This is not worth fixing
  in Caddy: Electron resolves it by construction, since a bundled sidecar is on
  `localhost:8200` by definition. It does draw a clean line — **`/app/` is the
  read-only historical viewing surface; Electron is the recording surface.**

Finally, an unrelated gap surfaced while assessing how safe it is to develop
against the live database: **there is no backup of production Postgres.** No
`pg_dump` service in `docker-compose.yml`, no scheduled task on the
`d1-server` host, only a named `pgdata` volume. A corrupted or deleted volume
loses the research database outright. (The `backup` code under
`apps/force-app/` is the live *capture* backup server — unrelated to database
backups.)

## Decision

Agreed for planning purposes; not yet executed. The sequence below is ordered
so that the irreversible step comes last and each step makes the next cheaper.

### 0. Back up the production database (prerequisite) — **DONE 2026-08-09**

This is a prerequisite, not a nicety. It is what makes "develop against the
live Directus over Tailscale" a defensible position rather than a gamble, and
it delivers the safety the first draft of this ADR wanted a whole local stack
for, at a fraction of the cost.

Implemented as `scripts/backup-postgres.ps1`, run nightly at 02:00 by the
Windows scheduled task **"D1 Postgres Nightly Backup"** on `d1-server`:

- `pg_dump -Fc` of `d1_database` plus `pg_dumpall --globals-only` for cluster
  roles — a per-database dump does not contain role definitions, so without
  the latter a restore onto a fresh cluster fails on missing grants.
- Written to `D:\D1-Backups\postgres` (6 TB free), 14-day retention, ~1.31 GB
  per archive (2710 MB database). Pruning runs only after a fully successful
  backup, so a broken job cannot delete the last good archives.
- The dump is written inside the container and copied out with `docker cp`,
  not streamed to stdout: PowerShell applies text encoding to redirected
  output and silently corrupts binary streams.
- The task runs as an interactive user rather than SYSTEM, because Docker
  Desktop's named pipe is not reachable from the SYSTEM account — that
  configuration produces a task that appears healthy and fails every night.

**Restore verified, not assumed.** The archive was restored into a scratch
database (`pg_restore -j 2`, exit 0, zero errors) and row counts compared
against production across eight tables — `physical_samples` 143,
`manufacturing_operations` 10,283, `machining_force_analysis` 189,
`fast_run_data` 10,040, `directus_files` 233,738, `directus_revisions` 23,519,
`audit_logs` 129,724, `directus_users` 15 — all matching exactly. The scratch
database was then dropped. A scheduled run was also triggered manually and
completed with `LastTaskResult: 0`.

Re-verify restorability periodically; the procedure is documented in the
script's header comment.

### 1. Extract plotting into a shared workspace package

Create `packages/force-plotting` as an npm workspace holding the single copy of
`ForceDashboard.vue`, `FrmCloud.vue`, `ForceChart.vue`, `FrmOctree.vue`,
`SpectrumView.vue`, `filterChain.ts`, `frmExport.ts`, `liveCache.ts`,
`liveCloud.ts` and `signalStats.ts`.

The three environment concerns become an injected host adapter:

```ts
interface ForceHost {
  api: AxiosInstance                               // Directus SDK vs standalone Bearer client
  openRecord(collection: string, id: string): void // router.push vs window.open
  downloadAsset(fileId: string): Promise<void>     // cookie <a> vs Bearer blob
  dense?: boolean                                  // layout density
}
```

`core/extensions/d1-force-dashboard` keeps its existing 12-line `defineModule`
registration and gains a Directus adapter. `apps/force-app/web` mounts the same
components with its standalone adapter. One implementation, two surfaces, the
duplication gone and the standalone-only bug fix reaching Directus in the
process.

This is the boundary work, and it is a prerequisite for a clean split: a clean
boundary is what makes extraction mechanical, and extracting before the
boundary is clean just distributes the drift across two repositories where it
is harder to see.

### 2. Extract `apps/force-app` into its own repository

`packages/force-plotting` **and** the thin Directus module wrapper both move
into the force-app repository, because that is where plotting expertise lives.
Three paths therefore have to travel together — `apps/force-app`,
`packages/force-plotting` and `core/extensions/d1-force-dashboard`. That rules
out `git subtree split`, which takes a single prefix; use `git filter-repo`
with one `--path` per directory to preserve history across all three:

```
git filter-repo --path apps/force-app \
                --path packages/force-plotting \
                --path core/extensions/d1-force-dashboard
```

Run it against a fresh clone — `filter-repo` rewrites history in place and
refuses to run on a repository with existing remotes by default.

force-app then builds two artifacts from one codebase: the Electron installer,
and a versioned `directus-extension-d1-force-dashboard` bundle. D1-Database
consumes the latter as a pinned dependency.

This is the point of the inversion: improvements to plotting are not *ported*
into Directus, they are **published**, and D1-Database bumps a version.
Porting is what drifts; a versioned dependency does not. It also lets the
Directus surface deliberately lag a release during an experiment rather than
lagging by accident.

### 3. Package the recorder backend as a PyInstaller sidecar

Freeze the existing Python backend into a binary spawned, health-checked and
restarted by Electron's main process, replacing the current Windows Scheduled
Task. The backend is already Windows-only (`nidaqmx`, direct LabAmp protocol
handling), so this is a packaging change, not a platform change. No Docker on
client machines.

### 4. Ship updates via `electron-builder`'s `autoUpdater`

Feed hosted either as static files behind the Caddy proxy already running on
`d1-server`, or via private GitHub Releases.

**Sequencing:** (0) and (1) are independent of everything else, safe, and
reversible — do them first, in that order. (2) is the irreversible step and
should be executed deliberately once (1) has settled. (3)–(4) are a distinct
later phase. Do not attempt this in one pass.

## Alternatives considered

### (a) Stand up a local disposable Directus + Postgres dev stack first

The first draft made this step 1, on the grounds that the database was
unreachable from the development machine.

Demoted, because the premise was false — see *Revision note*. The database is
reachable over Tailscale and force-app already uses it that way. The residual
argument is isolation for schema experiments, and for that a verified backup
(step 0) buys more safety per unit of effort than a second full stack to
install and maintain on an acquisition machine. A local throwaway stack remains
a reasonable *tool* to reach for when a specific change is destructive or
uncertain; it is not a prerequisite for day-to-day work.

### (b) Retire `core/extensions/d1-force-dashboard` entirely

Since `/app/` is already served same-origin from `d1-server`, the standalone
app could simply replace the in-admin dashboard.

Rejected: in-admin plotting is a genuinely useful surface for LIMS users who
are not running the desktop app, and sending them to a separate URL loses the
record context they are already sitting in. With the divergence measured at 45
lines, deleting a working surface to avoid duplication is the wrong trade —
sharing the code removes the duplication without removing the feature.

### (c) Embed `/app/` in the Directus module via an iframe

A ~50-line Directus module could iframe the already-deployed `/app/` build,
giving automatic freshness with no shared package.

Rejected: it would work, but it trades a solved problem for several unsolved
ones — nested navigation and scroll chrome, theme inheritance, passing record
context across the frame boundary, and CSP `frame-src` configuration. The
adapter approach in step 1 achieves the same single-source-of-truth outcome
with better integration, given how small the actual divergence is. Worth
reconsidering only if the adapter interface starts accumulating environment
concerns well beyond the current three.

### (d) Partial extraction via git subtree/submodule as an ongoing sync mechanism

Use a subtree or submodule to give force-app semi-independent versioning
without a full split.

Ruled out: adds subtree-merge / submodule-pin tooling to every change without
delivering the independent access control that motivates the split. Note this
is distinct from a *one-time* history-preserving extraction (`git filter-repo`,
step 2), which is a single operation rather than an ongoing obligation.

### (e) Split the repository immediately, before the shared package

Extract now and resolve the duplication afterwards.

Ruled out: the duplication is the boundary violation. Splitting first preserves
it under two repositories instead of one, and converts a local refactor into a
cross-repository publishing exercise. Deferring the split costs nothing — a
history-preserving extraction remains available at any time.

### (f) Rewrite the recorder backend in Node/TypeScript

Avoids bundling a second language runtime inside the Electron app.

Ruled out: the backend's value is in already-working, tested hardware
integration. A rewrite is large, high-risk, and buys nothing that a
PyInstaller sidecar does not already achieve at far lower cost.

## Consequences

### Positive

- A verified database backup closes a gap that currently risks total loss of
  the research database, independent of anything force-app related.
- One plotting implementation instead of two. Roughly 4,000 duplicated lines
  removed, and the standalone-only bug fix propagates to the Directus surface.
- The in-admin Directus dashboard survives, and stays current by version bump
  rather than by remembering to copy files across.
- The repo split becomes mechanical rather than fraught, and stays optional
  until access control actually requires it.
- force-app becomes independently versioned and CI-able — a prerequisite for
  Electron auto-update to field machines.
- Electron resolves the `/recorder/*` proxy pointing at the wrong host, and
  clarifies the split of surfaces: `/app/` for historical viewing, Electron for
  recording.

### Negative / Costs

- The host-adapter interface is a new abstraction to maintain. If the two
  surfaces diverge much further than the current three concerns, it will need
  revisiting — see alternative (c).
- After the split, D1-Database gains a published dependency on an artifact
  built in another repository: a release step, a version bump, and a
  possible-lag failure mode that does not exist today.
- The schema remains a cross-repository contract after the split, requiring an
  explicit sync step that will not update itself.
- Sidecar lifecycle management, error surfacing to the Electron UI, and
  eventual code-signing are real engineering work, separate from and after the
  repo split.
- Splitting the repository is hard to fully reverse (history, issues, PR links)
  and should be executed deliberately.
- Developing against the live Directus instance remains the default. Step 0
  makes this recoverable, not risk-free; destructive schema changes still
  warrant a throwaway stack or a fresh dump taken immediately beforehand.

## Open decisions (not yet resolved)

- **Schema contract mechanism after the split.** force-app is an API *client*,
  not a migration runner, so copied DDL is the wrong shape. The leading
  candidate is TypeScript types generated from Directus's OpenAPI spec,
  committed to the force-app repo and regenerated on a deliberate cadence, with
  the existing Connectivity Doctor extended to report schema mismatches at
  runtime. Not yet decided.
- Where the Electron auto-update feed is hosted — Caddy on `d1-server` vs
  private GitHub Releases.
- CI setup for the force-app repo (none exists today), including how the
  Directus extension bundle is published and consumed.
- **Off-host copy of the backups.** Retention is settled (14 days on `D:`),
  but the archives currently live on the same physical machine as the
  database. That covers volume corruption, a bad migration and accidental
  deletion; it does not cover loss of the machine. An off-host or offline copy
  is still needed.
- **`directus_revisions` bloat.** 1812 MB of the 2710 MB database — 67% — is
  Directus revision history, and it dominates both backup size and duration.
  A retention policy on revisions would shrink every future archive
  substantially. Out of scope for this ADR, but worth its own decision.

## References

- Architecture discussion, 2026-08-09, and its revision the same day (this ADR
  records both).
- `apps/force-app/` — current implementation.
- `core/extensions/d1-force-dashboard/` — the duplicate dashboard, bind-mounted
  live into the running Directus container.
- `infra/caddy/Caddyfile` — `/app/`, `/recorder/*`, `/filter/*` and `/octrees/*`
  routes.
- `db/migrations/` — schema source of truth (106 migrations as of this ADR).
- `docker-compose.yml` — production stack on `d1-server`; note the absence of
  any backup service.
