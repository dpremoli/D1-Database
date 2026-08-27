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
		version: '0.1.12',
		date: '2026-08-27',
		notes: [
			'Fixed: a failed download while switching replay cuts could leave the picker showing the new cuts name while the transport kept playing the old cut. The previous cut now stays fully in effect until a new one actually finishes loading.',
			'Fixed: switching to a new replay cut could show the previous cuts RPM target or depth of cut if the new cut had none recorded, instead of reading as not set.',
			'Fixed: a stored outer diameter of exactly 0 (meaning "not set") was being read as a real 0 mm override, showing Diameter and Surface speed as 0.',
			'Fixed: the Capture rate tile could read several times too low for a real recording, since it was reading the decimated cache rate instead of the true acquisition rate.',
			'Fixed: dismissing the cut search without picking a different cut (Escape, or clicking away) used to lose the loaded cuts label and parameter panel even though playback kept running.',
			'Fixed: the FRM panels Fx/Fy/Fz colour toggle had no effect once a replay cut was already loaded.',
		],
	},
	{
		version: '0.1.11',
		date: '2026-08-27',
		notes: [
			'Fixed: replayed cuts could stop short of the centre in the FRM map instead of spiralling all the way in. Replay now reads the real pulses-per-rev and diameters from the database instead of using whatever was left in the recording form.',
			'Fixed: the live FRM colour scale drifted while replaying, so early points looked off compared to the finished-cut view. It now uses the same colour range as the finished view, computed once from the whole cut.',
			'Replay: picking a cut now shows a loading indicator while it downloads, and the cut search collapses to a single line once a cut is picked instead of always showing the full list.',
			'Replay: the feed, diameter, pulses-per-rev, surface speed, depth of cut, capture rate and cut time are now shown as a compact parameter summary once a cut is loaded.',
			'Recording: the numeric setup fields (spindle, feed, diameter, sample rate, pulses/rev) use the same compact card style as the new replay parameter summary.',
		],
	},
	{
		version: '0.1.10',
		date: '2026-08-27',
		notes: [
			'Fixed: the replay scrub bar vanished when the Recording panel was narrow — it collapsed to zero width behind the play button and time readout, leaving playback uncontrollable. The row now wraps and the scrub keeps a usable width.',
		],
	},
	{
		version: '0.1.9',
		date: '2026-08-27',
		notes: [
			'Replay file now plays like a video: play, pause and scrub through a past cut, at true realtime speed by default (with slow-motion down to 0.25×). It drives the same waveform, FFT, FRM and RPM views a live cut does.',
			'Replaying a cut no longer records a second copy of it — it plays the file already in the database, so nothing new is written to disk.',
			'Fixed: replaying a long cut reported a spindle speed several times too high, which also raised a false safety alarm every time.',
			'Fixed: replay ignored the speed you asked for on long cuts, always finishing in about 40 seconds however long the cut really was.',
		],
	},
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
