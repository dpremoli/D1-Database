# force-app-reviewer memory

Shared, checked-in notes from earlier force-app reviews. One dated line per lesson; newest last.

- 2026-10-02: seeded. `scheduledTask.test.ts` fails only if Electron's binary is missing (`npm ci --ignore-scripts`): not a regression. The sidecar `stop()` test is `skipIf(!win32)` by design.
- 2026-10-03: force-app suites now run on every PR (ci.yml `force-app-js`, `force-app-python`). A red force job on a PR is real; the Windows-only e2e still runs only at release.
- 2026-10-02: D1LC has five implementations (backend, filter-service, scripts/diag, process_force.m, liveCache.ts); `scripts/diag/d1lc.py` is the one most often forgotten.
