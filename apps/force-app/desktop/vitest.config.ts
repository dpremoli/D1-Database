import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Scope to the unit tests under src/ only. Without this, Vitest's default include glob
    // (**/*.{test,spec}.ts) also picks up tests/smoke.spec.ts, which calls Playwright's test()
    // outside a Playwright test run and fails with "Playwright Test did not expect test() to be
    // called here." The Playwright suite has its own runner (`npm run test:e2e`).
    include: ['src/**/*.test.ts'],
  },
});
