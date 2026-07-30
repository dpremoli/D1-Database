// Service endpoints for the standalone app. The app runs on its OWN origin and talks to
// Directus + the filter/octree sidecars cross-origin (CORS + Bearer). Because the SPA is a
// static bundle, we support two configuration styles:
//   1. Build-time: VITE_* env vars (baked in). Good for a fixed deployment.
//   2. Runtime: an optional /config.json served next to index.html, so the SAME bundle can be
//      pointed at different Directus instances without a rebuild. Runtime wins when present.

export interface AppConfig {
	/** Directus REST base (items + assets + auth). No trailing slash. */
	directusUrl: string;
	/** Filter sidecar base (/run, /fft). No trailing slash. */
	filterUrl: string;
	/** Octree static server base. No trailing slash; the app appends /<octreePath>/. */
	octreeUrl: string;
	/** Local recording backend (Phase 2). No trailing slash. */
	recorderUrl: string;
}

const stripSlash = (s: string) => s.replace(/\/+$/, '');

// Build-time defaults from env (fall back to same-origin relative paths for a co-hosted setup).
const config: AppConfig = {
	directusUrl: stripSlash(import.meta.env.VITE_DIRECTUS_URL ?? ''),
	filterUrl: stripSlash(import.meta.env.VITE_FILTER_URL ?? '/filter'),
	octreeUrl: stripSlash(import.meta.env.VITE_OCTREE_URL ?? '/octrees'),
	recorderUrl: stripSlash(import.meta.env.VITE_RECORDER_URL ?? 'http://localhost:8200'),
};

// Fetch /config.json once at boot (optional). Any keys present override the env defaults.
export async function loadRuntimeConfig(): Promise<void> {
	try {
		const res = await fetch('/config.json', { cache: 'no-store' });
		if (!res.ok) return;
		const j = (await res.json()) as Partial<AppConfig>;
		if (j.directusUrl) config.directusUrl = stripSlash(j.directusUrl);
		if (j.filterUrl) config.filterUrl = stripSlash(j.filterUrl);
		if (j.octreeUrl) config.octreeUrl = stripSlash(j.octreeUrl);
		if (j.recorderUrl) config.recorderUrl = stripSlash(j.recorderUrl);
	} catch {
		/* no runtime config file — env defaults stand */
	}
}

export function getConfig(): Readonly<AppConfig> {
	return config;
}
