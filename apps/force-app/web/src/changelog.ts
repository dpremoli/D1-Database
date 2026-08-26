// Bundled with each build (not fetched), so it always matches whatever version is actually
// installed and needs no network call. Add an entry here as part of any release that bumps
// apps/force-app/desktop/package.json's version — newest first.
export interface ChangelogEntry {
	version: string;
	date: string;   // YYYY-MM-DD
	notes: string[];
}

export const CHANGELOG: ChangelogEntry[] = [
	{
		version: '0.1.6',
		date: '2026-08-26',
		notes: [
			'Settings > About: shows the running version and this changelog.',
			'The "update ready" prompt now waits for an active recording to finish instead of interrupting it, and lets you postpone an update and keep working — Settings > About always shows where to install it later.',
			'Settings > About: Restart & Install button to apply a downloaded update without waiting for the prompt.',
		],
	},
	{
		version: '0.1.5',
		date: '2026-08-26',
		notes: [
			'Settings > General: shows the running version and a manual Check for updates button.',
		],
	},
	{
		version: '0.1.4',
		date: '2026-08-26',
		notes: [
			'Fixed laggy crop-handle dragging on the Signals charts.',
			'Fixed the live force plot stalling on slower machines during long recordings.',
			'The left nav no longer reserves horizontal space it doesn’t use.',
			'Fixed the Simulated/Replay/NI-DAQ source row sometimes appearing clipped at the top of the Recording panel.',
			'Spectrogram view is single-axis only (a heatmap can’t usefully overlay multiple axes); Waterfall still supports all three.',
		],
	},
	{
		version: '0.1.3',
		date: '2026-08-23',
		notes: [
			'Live recording backup: streams to a crash-safety server in real time and recovers cleanly from a network outage mid-recording.',
			'Settings > Logs: view, filter, search, and download the backend log without leaving the app.',
			'Auto-update installs silently and relaunches automatically instead of opening the full installer wizard.',
			'Fixed the capture-drive setting silently failing to persist on a packaged install.',
		],
	},
];
