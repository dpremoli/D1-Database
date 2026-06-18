<!-- Keep PRs within the current phase's scope (see plan.md). -->

## What & why

<!-- What does this change, and which plan.md phase / spec section does it serve? -->

## Checklist

- [ ] Scoped to the current phase (`plan.md`)
- [ ] Schema changes are migrations only (`db/migrations/`), reversible up & down
- [ ] No depended-on logic added to Directus config (core stays swappable, ADR-0002)
- [ ] Tests written **and run locally** (`make test`) — not left for CI to find
- [ ] An ADR added/updated for any significant decision (`docs/adr/`)
- [ ] No secrets or real/large data committed (`SECURITY.md`)
- [ ] `plan.md` status tracker updated if a phase milestone changed

## How tested

<!-- Commands run and what you observed. -->
