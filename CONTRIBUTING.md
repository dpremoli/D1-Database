# Contributing to D1-Database

This is a long, multi-phase, primarily-Claude-authored project with maintainer
review. These conventions keep each session **resumable cold** and the core
**clean and swappable**. Read [`plan.md`](./plan.md) and
[`docs/adr/`](./docs/adr/) before making changes.

## Golden rules (from the ADRs)

1. **The schema is the contract.** Change it only through versioned SQL
   migrations in [`db/migrations/`](./db/migrations/). Never via the Directus UI
   or manual `psql` edits. Descriptive names, units in column names, FK
   constraints, and a `COMMENT` on every table/column are mandatory.
2. **Keep the core swappable.** No depended-on business logic in Directus config
   (ADR-0002). Constraints, audit, concurrency, and views are native Postgres.
3. **Project-specific compute is a plugin**, never part of the core
   ([`plugins/`](./plugins/)), talking to the core only through the documented contract.
4. **Everything is infrastructure-as-code.** A change isn't done until
   `docker compose up` from clean reproduces it.

## Workflow

- **Branches:** work on a feature branch off `main`; open a PR. Don't commit
  directly to `main`.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) —
  `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `build:`.
  Scope by area where useful, e.g. `feat(db): add physical_samples table`.
- **ADRs:** any significant or hard-to-reverse decision gets an ADR
  ([`docs/adr/`](./docs/adr/)) in the same PR.
- **Feature designs:** a substantial feature gets a design spec in
  [`docs/superpowers/specs/`](./docs/superpowers/specs/); update its Status line
  when it ships. Implementation plans are deleted once their feature has
  shipped — see [`docs/superpowers/README.md`](./docs/superpowers/README.md).
- **Phases:** keep changes within the current phase's scope (see `plan.md`);
  update the status tracker when a phase completes.

## Tests — write and run them as you go

Every change ships with a test, and tests are **run before committing** (not
left for CI to discover):

- **Schema/migrations:** migrations must apply up *and* down cleanly; audit
  triggers and constraints have tests (Phase 1+).
- **Plugins/services:** unit tests beside the code; integration tests in
  [`tests/`](./tests/).
- **Foundation:** `bash tests/phase0_smoke.sh` validates repo structure, env
  template, and that `docker-compose.yml` is valid.

## Local tooling

```sh
make help          # list targets
make setup         # install pre-commit hooks (needs python + pre-commit)
make test          # run the current smoke/integration tests
make compose-check # validate docker-compose.yml
```

`make` is optional (Linux/WSL/CI); on Windows you can run the underlying
commands directly — see the [`Makefile`](./Makefile). `pre-commit` runs
`ruff`/`black` (Python), `sqlfluff` (SQL), `hadolint` (Dockerfiles), and basic
hygiene hooks; CI enforces the same set.

## Claude Code skills

[`.claude/skills/`](./.claude/skills/) holds project skills that encode the conventions
above. Claude Code loads them on its own when a task matches, or you can type
`/<name>`:

| Skill | Use it for |
|---|---|
| `db-migration` | Writing a dbmate migration and proving up → down → up (works without Docker via a local Postgres 16) |
| `migration-review` | Reviewing a branch's migrations against the schema rules, in a separate subagent |
| `new-plugin` | Scaffolding a plugin from `plugins/plugin-template` and wiring compose, `.env.example`, Makefile and CI |
| `adr` | Writing an ADR or a design spec and updating its index |
| `ci-local` | Running the CI checks the changed files touch, before committing |

The rest of `.claude/` (local settings, memory, plans) stays gitignored.

## Security

Never commit secrets or real data. Large experimental files belong in MinIO,
never git. See [`SECURITY.md`](./SECURITY.md).
