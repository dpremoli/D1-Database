import net from 'node:net';

export function isPortFree(port: number, host = '127.0.0.1'): Promise<boolean> {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, host);
  });
}

/** Prefer `preferred`; otherwise scan upward through `range` candidate ports. A stale process
 * holding the default port must not wedge the app — see the sidecar spec's "Port" note. */
export async function findAvailablePort(preferred: number, range = 20): Promise<number> {
  if (await isPortFree(preferred)) return preferred;
  for (let p = preferred + 1; p <= preferred + range; p++) {
    if (await isPortFree(p)) return p;
  }
  throw new Error(`no free port found in [${preferred}, ${preferred + range}]`);
}
