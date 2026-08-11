// Ambient type for the bridge apps/force-app/desktop/src/preload.ts exposes. `window.forceApp` is
// only present when the SPA runs inside the Electron shell — the same bundle also serves the
// read-only /app/ browser surface (infra/caddy/Caddyfile), where it is undefined.
export {};

declare global {
  interface Window {
    forceApp?: {
      onNavigate: (callback: (path: string) => void) => void;
    };
  }
}
