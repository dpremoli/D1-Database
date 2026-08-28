#!/usr/bin/env node
// Regression guard for the theming sweep: fails if any of the plot-canvas components' <style>
// blocks hardcode their container `background` again instead of `var(--plot-bg, ...)`. These
// components were fixed so plot canvases (force plots, FRM map, FFT, spectrogram, waterfall)
// follow the light/dark theme rather than staying a permanently-dark "instrument display" — see
// the theming plan. Scoped to this specific, known file list rather than a repo-wide color grep:
// most rgba()/hex usage elsewhere in the app is legitimate semantic status coloring (red/green/
// amber badges, brand colors) unrelated to this bug, and would make a generic guard all noise.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webSrc = path.resolve(__dirname, '../src');
const plottingSrc = path.resolve(__dirname, '../../../../packages/force-plotting/src');

const FILES = [
	path.join(webSrc, 'record/LiveForcePlot.vue'),
	path.join(webSrc, 'record/FinishedForcePlot.vue'),
	path.join(webSrc, 'record/LiveFrm.vue'),
	path.join(webSrc, 'record/LiveFft.vue'),
	path.join(webSrc, 'record/LiveSpectrogram.vue'),
	path.join(webSrc, 'record/LiveWaterfall.vue'),
	path.join(plottingSrc, 'FrmCloud.vue'),
	path.join(plottingSrc, 'FrmOctree.vue'),
	path.join(plottingSrc, 'SpectrumView.vue'),
];

// Only the plot canvas's own root-container selector (the outermost `.live-force { ... }` etc.
// rule) is in scope — a `background:` set to a hardcoded literal there, instead of
// `var(--plot-bg, ...)`. Other rules in these files (buttons, overlays, badges) legitimately use
// fixed accent/status colors and are not this guard's concern.
const CONTAINER_CLASS_RE = /\.(live-force|finished-force|live-frm|live-fft|live-spec|live-wf|frm-cloud|frm-octree|spec-view)\s*\{([^}]*)\}/g;
const BARE_BG_RE = /background:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))\s*;/;

let violations = [];

for (const file of FILES) {
	let src;
	try { src = readFileSync(file, 'utf8'); } catch { continue; }
	let m;
	CONTAINER_CLASS_RE.lastIndex = 0;
	while ((m = CONTAINER_CLASS_RE.exec(src))) {
		const rule = m[2];
		const bgMatch = rule.match(BARE_BG_RE);
		if (bgMatch) {
			const lineNo = src.slice(0, m.index).split('\n').length;
			violations.push(`${path.relative(process.cwd(), file)}:${lineNo}  .${m[1]} { ... ${bgMatch[0]} ... }`);
		}
	}
}

if (violations.length) {
	console.error(`Found ${violations.length} hardcoded plot-canvas background literal(s).`);
	console.error('Route through var(--plot-bg, ...) so plot canvases keep following the theme.\n');
	for (const v of violations) console.error('  ' + v);
	process.exit(1);
} else {
	console.log('No unrouted plot-canvas background literals found.');
}
