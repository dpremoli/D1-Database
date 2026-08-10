import { describe, it, expect, afterEach } from 'vitest';
import net from 'node:net';
import { isPortFree, findAvailablePort } from './port';

describe('port resolver', () => {
  let holder: net.Server | undefined;

  afterEach(async () => {
    await new Promise<void>((resolve) => (holder ? holder.close(() => resolve()) : resolve()));
    holder = undefined;
  });

  it('reports a genuinely free port as free', async () => {
    expect(await isPortFree(48213)).toBe(true);
  });

  it('reports a held port as not free', async () => {
    holder = net.createServer();
    await new Promise<void>((resolve) => holder!.listen(48214, '127.0.0.1', () => resolve()));
    expect(await isPortFree(48214)).toBe(false);
  });

  it('falls back to the next free port when the preferred one is held', async () => {
    holder = net.createServer();
    await new Promise<void>((resolve) => holder!.listen(48215, '127.0.0.1', () => resolve()));
    const chosen = await findAvailablePort(48215, 5);
    expect(chosen).not.toBe(48215);
    expect(chosen).toBeGreaterThan(48215);
  });

  it('throws when nothing in range is free', async () => {
    holder = net.createServer();
    await new Promise<void>((resolve) => holder!.listen(48216, '127.0.0.1', () => resolve()));
    // range 0 means only the preferred port is checked, and it's held.
    await expect(findAvailablePort(48216, 0)).rejects.toThrow();
  });
});
