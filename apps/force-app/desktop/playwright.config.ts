import { defineConfig } from '@playwright/test';

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: 'tests',
  // save-flow.spec.ts's stop/finalize sequence has taken 30-40s on GitHub-hosted CI runners
  // against ~1s locally, seen on two consecutive release builds — backend.log shows every step
  // still completing (consumer/acquisition thread joins, finalize), just under heavy contention,
  // not a hang. The local budget has 4x headroom to spare; CI gets real room plus one retry so a
  // contended runner doesn't fail a release build outright.
  timeout: isCI ? 120_000 : 60_000,
  retries: isCI ? 1 : 0,
  // Both tests spawn the real backend on a port the supervisor resolves itself; running them
  // concurrently risks two Electron instances racing for the same fallback port.
  workers: 1,
  reporter: 'list',
});
