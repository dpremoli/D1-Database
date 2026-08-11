import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests',
  timeout: 60_000,
  // Both tests spawn the real backend on a port the supervisor resolves itself; running them
  // concurrently risks two Electron instances racing for the same fallback port.
  workers: 1,
  reporter: 'list',
});
