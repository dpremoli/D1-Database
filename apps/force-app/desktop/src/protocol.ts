import fs from 'node:fs';
import path from 'node:path';
import { net as electronNet, protocol } from 'electron';

export function registerAppScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'app',
      privileges: {
        standard: true,
        secure: true,
        corsEnabled: true,
        supportFetchAPI: true,
        stream: true,
      },
    },
  ]);
}

/** Maps an `app://force/<path>` request to the file that should serve it. A pure function so the
 * mapping is testable without booting Electron. `/config.json` is special-cased to userData
 * (Task 2's ConfigStore) rather than the bundled dist, because only that file can carry the
 * sidecar's actual resolved port. */
export function resolveRequestPath(
  requestUrl: string,
  webDistDir: string,
  configFilePath: string,
): { filePath: string; is404: boolean } {
  const u = new URL(requestUrl);
  if (u.hostname !== 'force') {
    return { filePath: '', is404: true };
  }
  let pathname = decodeURIComponent(u.pathname);
  if (pathname === '' || pathname === '/') pathname = '/index.html';

  if (pathname === '/config.json') {
    return { filePath: configFilePath, is404: !fs.existsSync(configFilePath) };
  }

  const root = path.normalize(webDistDir);
  const candidate = path.normalize(path.join(root, pathname));
  if (!candidate.startsWith(root)) {
    // Traversal guard: a request like app://force/..%2f..%2fsecrets must not escape webDistDir.
    return { filePath: '', is404: true };
  }
  if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
    return { filePath: candidate, is404: false };
  }
  // SPA history fallback: unknown sub-routes (e.g. /settings) resolve to index.html, matching
  // Caddy's `try_files {path} /index.html` for the /app/ surface.
  const indexPath = path.join(root, 'index.html');
  return { filePath: indexPath, is404: !fs.existsSync(indexPath) };
}

export function handleAppProtocol(webDistDir: string, configFilePath: string): void {
  protocol.handle('app', async (request) => {
    const { filePath, is404 } = resolveRequestPath(request.url, webDistDir, configFilePath);
    if (is404) return new Response('Not found', { status: 404 });
    return electronNet.fetch(`file://${filePath}`);
  });
}
