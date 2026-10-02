#!/usr/bin/env bash
# List the CI checks that the current change touches, one shell command per line,
# based on files changed against the base ref plus uncommitted work.
# Mirrors .github/workflows/ci.yml; keep the two in step.
#
# Usage: plan_checks.sh [base-ref]   (default origin/main)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

base="${1:-origin/main}"
git rev-parse -q --verify "$base" >/dev/null || base="$(git rev-list --max-parents=0 HEAD | tail -1)"

files="$( { git diff --name-only "$base"...HEAD; git diff --name-only HEAD; git ls-files --others --exclude-standard; } | sort -u)"
[[ -z "$files" ]] && { echo "# no changes against $base"; exit 0; }

has() { grep -qE "$1" <<<"$files"; }

echo "# changed files against $base: $(wc -l <<<"$files")"
# shellcheck disable=SC2086
echo "pre-commit run --files $(tr '\n' ' ' <<<"$files")"
echo "bash tests/phase0_smoke.sh"

has '^(core/extensions/(d1-geometry-preview|d1-home|d1-report)/|scripts/sync_geometry\.sh)' && {
  echo "bash scripts/sync_geometry.sh --check"
  echo "node --experimental-strip-types --test core/extensions/d1-geometry-preview/test/geometry.test.ts"
}
has '^(db/|tests/phase(1|6|7)_)' && \
  echo "bash .claude/skills/db-migration/scripts/verify_migration.sh   # needs a scratch DATABASE_URL"

for p in heavy-data-worker analysis-worker llm-text-to-sql; do
  has "^plugins/$p/" && echo "docker build -t d1-$p plugins/$p/ && docker run --rm d1-$p python -m pytest tests/ -v --tb=short"
done
has '^plugins/llm-text-to-sql/' && echo "docker run --rm d1-llm-text-to-sql python eval/run_eval.py"
for p in $(grep -oE '^plugins/[^/]+/' <<<"$files" | sort -u | cut -d/ -f2); do
  case "$p" in heavy-data-worker|analysis-worker|llm-text-to-sql) ;; *)
    [[ -d "plugins/$p/tests" ]] && echo "(cd plugins/$p && python -m pytest tests/ -q)   # not in CI" ;;
  esac
done

has '^scripts/.*\.py$|^tests/scripts/' && echo "python -m pytest tests/scripts -q   # not in CI; *_golden_exactly may differ by machine"
# Force app: nothing below runs in ci.yml; the release job runs only backend/backup-server/desktop.
has '^packages/force-plotting/' && echo "npm test -w @d1/force-plotting && npm run typecheck -w @d1/force-plotting   # not in CI"
has '^(apps/force-app/web/|packages/force-plotting/)' && \
  echo "npm test -w force-app-web && npm run typecheck -w force-app-web && npm run lint:theme -w force-app-web   # not in CI"
has '^apps/force-app/desktop/' && \
  echo "npm test -w force-app-desktop   # off Windows, sidecar 'stop() terminates' fails (needs taskkill): ignore that one"
has '^core/extensions/d1-force-dashboard/' && echo "npm run build:extension   # not in CI"
has '^apps/force-app/backend/' && echo "(cd apps/force-app/backend && python -m pytest -q)   # release job only"
for s in backup-server bug-report-relay; do
  has "^apps/force-app/$s/" && echo "(cd apps/force-app/$s && python -m pytest -q)   # not in ci.yml"
done
has '^(apps/force-app/(backend|web)/|packages/force-plotting/)' && \
  echo "# then the force-app-verify skill: sim recording over HTTP + through the UI"
has '^apps/force-app/desktop/package\.json$|^apps/force-app/web/src/changelog\.ts$' && \
  echo "bash .claude/skills/force-app-release/scripts/preflight.sh --fast   # version/changelog/lockfile agree"
exit 0
