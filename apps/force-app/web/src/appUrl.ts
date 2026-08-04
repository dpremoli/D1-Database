// Build an absolute URL for an in-app route that respects the Vite base path. The SPA is served
// under a base (e.g. `/app/` behind Caddy for Tailscale, `/` in dev), and the router uses
// `createWebHistory(import.meta.env.BASE_URL)`. `window.open(location.origin + '/live/frm')` drops
// the base and hits Directus → ROUTE_NOT_FOUND. Prefix the base so pop-out windows land in the SPA.
export function appUrl(routePath: string): string {
	const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, ''); // '/app' or ''
	const path = routePath.startsWith('/') ? routePath : `/${routePath}`;
	return new URL(base + path, location.origin).href;
}
