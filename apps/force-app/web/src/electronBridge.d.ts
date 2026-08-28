// Ambient type for the bridge apps/force-app/desktop/src/preload.ts exposes. `window.forceApp` is
// only present when the SPA runs inside the Electron shell — the same bundle also serves the
// read-only /app/ browser surface (infra/caddy/Caddyfile), where it is undefined.
export {};

type UpdateStatus =
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'available'; version: string }
  | { state: 'not-available' }
  | { state: 'downloading'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'installing'; version: string }
  | { state: 'error'; message: string };

declare global {
  interface Window {
    forceApp?: {
      onNavigate: (callback: (path: string) => void) => void;
      getUpdateInfo: () => Promise<{ version: string; packaged: boolean; status: UpdateStatus }>;
      checkForUpdates: () => Promise<{ ok: boolean; reason?: string }>;
      installUpdate: () => Promise<{ ok: boolean; reason?: string }>;
      onUpdateStatus: (callback: (status: UpdateStatus) => void) => void;
    };
  }
}
