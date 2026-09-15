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
		version: '0.1.22',
		date: '2026-09-15',
		notes: [
			'No user-facing changes — a formatting fix to the bug-report relay to get CI passing again after 0.1.21.',
		],
	},
	{
		version: '0.1.21',
		date: '2026-09-15',
		notes: [
			'New Metadata Doctor (Plot dashboard): flags operations where the archived .mat file\'s recorded parameters disagree with, or are missing from, the database — undersized crop windows, conflicting feed/depth-of-cut/speed/diameter, unlinked samples — with one-click fixes that route through the existing "Save changes" dialog. A severity badge and filter show flagged ops directly in the Operations list; a workpiece diameter field was added to the metadata box so it has somewhere to adopt into.',
			'Fixed: the operation code and sequence fields in the Plot dashboard\'s metadata box looked editable but any edits were silently discarded — both are now shown as the fixed, non-editable values they always actually were.',
			'End-of-cut save dialog: the detected cut start/end can now be dragged to adjust before saving, with a note and one-click reset if you want to revert to the auto-detected window.',
			'Report a bug/feature page: you can now tag whether you\'re filing a bug or a feature request, your signed-in email is always attached to the report, and the page shows your recently-filed reports with their open/closed status.',
			'Fixed: leaving the Plot page and coming back reloaded it from scratch every time, including re-fetching the drive list on every visit to Settings > General.',
			'Fixed: discarding a just-finished recording (instead of saving it) could leave its plot data showing on the next recording.',
			'Fixed: the Signals/FRM column on the Plot page could fall slightly short of matching the record window\'s exact height.',
			'Fixed: the FRM point cloud in Lite mode could vanish when zoomed in, not reappearing until you zoomed back out.',
			'Fixed: a Full-res (Potree) point cloud kept showing the old crop window after the crop was adjusted and saved — it\'s now automatically rebuilt on the next save.',
		],
	},
	{
		version: '0.1.20',
		date: '2026-09-13',
		notes: [
			'Plot dashboard: dragging the FRM point-cloud crop handles is now instant even on multi-million-point cuts (previously visibly laggy) — the crop preview moved onto the GPU instead of being recomputed on every drag frame.',
			'Plot dashboard: the mouse cursor no longer lags when scrubbing across multiple open charts at once.',
			'Fixed: a saved crop override stopped being applied once you left Live mode, silently reverting to the auto-detected crop window.',
			'Plot dashboard: dark mode grid lines and axis ticks are now dim instead of bright white, and axis text is larger and easier to read.',
			'Plot dashboard: an optional second axis showing the tool\'s radial position (distance from the part centre) can now be added to the Signals charts.',
			'Plot dashboard: Power, Spectrogram, and Waterfall views now have the same per-axis layout, axis labels, hover readout, and zoom/pan as Force/FFT (previously collapsed multi-axis panels to a single axis and had no interactive axes at all).',
			'Plot dashboard: editing an operation\'s metadata (subtype, sequence, cutting parameters, notes) and adjusting its crop now save together in one combined "Save changes" summary, including a preview of the regenerated operation name.',
			'Fixed: the Plot page could scroll slightly on a normal-size monitor even though nothing was actually cut off.',
		],
	},
	{
		version: '0.1.19',
		date: '2026-09-11',
		notes: [
			'New Polar Plot panel (Record page → Add panel, with its own pop-out window): plots torque or force against spindle angle for a finished or replayed cut — the milling counterpart to the FRM map.',
			'Fixed: the FRM map could come up blank, or show a "no host installed" error, immediately after a recording finished — unless you had opened the Plot page earlier in the same session.',
			'Diagnostics Workbench: a very long or high-speed cut, a straight-line cut, or a recipe with the frame-transform step switched off no longer crashes the analysis bake — each now fails with a clear reason.',
			'Diagnostics Workbench: the framed-view recompute now returns a readable error (not a bare server error) when a crop is too large or a seed layer is missing; clicking a pipeline step to revert the view now redirects the view you are actually looking at and clears its stale colouring.',
			'Force capture files can now carry torque (Mz) and machine tool-position (X/Y/Z) channels alongside force, as groundwork for milling support. Older capture files load unchanged.',
		],
	},
	{
		version: '0.1.18',
		date: '2026-08-29',
		notes: [
			'The "recording in progress" banner shown when you navigate away from Record is now blue with live elapsed time, sample count, and peak force, instead of looking like a red error banner.',
			'Disabling a safety alarm in Settings, or silencing one that has tripped, now explains exactly what you are turning off and asks you to confirm.',
			'Quitting the app while a recording is in progress now warns you and lets you cancel, instead of silently stopping the acquisition.',
			'Fixed: a healthy tacho sensor could trigger a false "No tacho signal" alarm in the first couple of seconds of every real recording.',
			'Fixed: acknowledging one safety alarm could silently silence a different alarm that fired at the same moment, without ever showing it to you.',
			'Bug reports can now include more diagnostic detail (amp mode, NI-DAQ hardware, disk space, more log history, and this window\'s console) to make problems easier to diagnose remotely.',
			'Connectivity Doctor now checks that the NI-DAQ chassis and the Lab Amp are actually connected and responding, not just that the drivers/software are installed.',
		],
	},
	{
		version: '0.1.13',
		date: '2026-08-28',
		notes: [
			'Fixed: dropdown search menus (Sample, Machine, Tool, Operator, Insert, Edge, replay cut picker) stayed dark in light mode.',
			'Fixed: after picking a replay cut and clicking "change" to pick a different one, the list only ever showed one option instead of the full recent-cuts list.',
			'Recording panel: Insert/Edge and Machine/Operator fields are now side by side to save vertical space; picking an Edge auto-fills its parent Insert.',
			'The Tool field now shows the tool\'s name instead of its code.',
			'Record page panels can now extend further down the window, and the floating add-panel/reset-layout buttons are slightly larger and fade to translucent until hovered.',
			'The plotting window can now save a manually adjusted crop as the operation\'s official crop point, used automatically on future replays.',
			'The sidebar\'s collapsed nav handle is easier to hover onto without shrinking its visible size.',
		],
	},
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
