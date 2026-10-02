# force-app-reviewer memory

Shared, checked-in notes from earlier force-app reviews. One dated line per lesson; newest last.

- 2026-10-02: seeded. Linux-only false alarms: desktop `sidecar.test.ts` "stop() terminates" needs Windows `taskkill`; `scheduledTask.test.ts` needs the Electron binary. Don't report these as regressions.
- 2026-10-02: D1LC has five implementations (backend, filter-service, scripts/diag, process_force.m, liveCache.ts); `scripts/diag/d1lc.py` is the one most often forgotten.
