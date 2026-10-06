// "Save chart as SVG / PNG" for the signal charts. The builder is a pure function (data in, SVG
// text out) so it unit-tests without a DOM; the PNG path rasterises that same SVG through an
// offscreen canvas. Styled like the FRM figure (frmExport.ts): light background, serif text, a
// framed axis with "nice" ticks, and a title + subtitle, so a chart pasted into a report matches.
import { fmt, niceTicks } from './frmExport';
import { downloadBlob } from './csvExport';

/** Envelope series (`kind: 'env'`) carry `t/min/max`; spectra (`kind: 'line'`) carry `f/amp`. */
export interface ChartSnapshot {
	title: string;                 // "Fx · force": axis and mode
	kind: 'env' | 'line';
	data: any;
	color?: string;
	xUnit?: string;
	yUnit?: string;
	logY?: boolean;
	cropStart?: number | null;
	cropEnd?: number | null;
	viewStart?: number | null;
	viewEnd?: number | null;
	compare?: { id: string; label: string; color: string; data: any }[] | null;
}

export interface ChartSvgOpts extends ChartSnapshot {
	/** Operation tag, shown ahead of the chart title. */
	opLabel?: string;
	subtitle?: string;
	width?: number;
	height?: number;
	/** Upper bound on points per trace in the file (default 800). */
	maxPoints?: number;
}

export function escapeXml(s: string): string {
	return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

interface Trace { x: number[]; lo: number[]; hi: number[] }

/** Cut a series to the view window and thin it to at most `max` points. Each bucket keeps its
 *  min and max, so extremes (and spectral peaks) survive. */
export function decimateTrace(xs: ArrayLike<number>, lo: ArrayLike<number>, hi: ArrayLike<number>,
	x0: number, x1: number, max: number): Trace {
	let a = 0, b = xs.length - 1;
	while (a < b && xs[a + 1] < x0) a++;
	while (b > a && xs[b - 1] > x1) b--;
	const n = b - a + 1;
	if (n <= 0) return { x: [], lo: [], hi: [] };
	const x: number[] = [], l: number[] = [], h: number[] = [];
	if (n <= max) {
		for (let i = a; i <= b; i++) { x.push(xs[i]); l.push(lo[i]); h.push(hi[i]); }
		return { x, lo: l, hi: h };
	}
	const size = Math.ceil(n / max);
	for (let s = a; s <= b; s += size) {
		const e = Math.min(b, s + size - 1);
		let mn = Infinity, mx = -Infinity;
		for (let i = s; i <= e; i++) {
			if (lo[i] < mn) mn = lo[i];
			if (hi[i] > mx) mx = hi[i];
		}
		x.push((xs[s] + xs[e]) / 2); l.push(mn); h.push(mx);
	}
	return { x, lo: l, hi: h };
}

function traceOf(kind: 'env' | 'line', d: any, x0: number, x1: number, max: number): Trace | null {
	if (!d) return null;
	if (kind === 'env') return d.t?.length ? decimateTrace(d.t, d.min, d.max, x0, x1, max) : null;
	return d.f?.length ? decimateTrace(d.f, d.amp, d.amp, x0, x1, max) : null;
}

/** The y-axis title for a chart: what is plotted and its unit, e.g. "Force (N)". Empty without a unit. */
export function yAxisTitle(kind: 'env' | 'line', unit: string | undefined, logY = false): string {
	if (!unit) return '';
	const name = unit === 'rpm' ? 'Speed' : unit === 'σ' ? 'Residual' : kind === 'env' ? 'Force' : 'Amplitude';
	return `${name}${logY ? ' (log scale)' : ''} (${unit})`;
}

const FONT = '"Times New Roman", Georgia, serif';

/** A standalone, report-styled SVG of one chart. Never throws on empty data (returns a figure
 *  with the title and "no data"). */
export function buildChartSvg(o: ChartSvgOpts): string {
	const W = o.width ?? 900, H = o.height ?? 420;
	const max = o.maxPoints ?? 800;
	const color = o.color || '#0d9488';
	const cmp = (o.compare ?? []).filter((c) => c.data?.t?.length);
	const mL = 78, mR = 26, mT = o.subtitle ? 66 : 46, mB = 62 + (cmp.length ? 26 : 0);
	const pw = W - mL - mR, ph = H - mT - mB;
	const title = [o.opLabel, o.title].filter(Boolean).join(' · ');
	const head = `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family='${FONT}'>`
		+ `<rect width="${W}" height="${H}" fill="#fff"/>`
		+ `<text x="${W / 2}" y="28" text-anchor="middle" font-size="20" font-weight="bold" fill="#000">${escapeXml(title)}</text>`
		+ (o.subtitle ? `<text x="${W / 2}" y="49" text-anchor="middle" font-size="13" fill="#777">${escapeXml(o.subtitle)}</text>` : '');

	const xsAll: ArrayLike<number> | undefined = o.kind === 'env' ? o.data?.t : o.data?.f;
	if (!xsAll || xsAll.length < 2) {
		return `${head}<text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-size="16" fill="#777">no data</text></svg>`;
	}
	const dx0 = xsAll[0], dx1 = xsAll[xsAll.length - 1];
	let x0 = o.viewStart != null ? Math.max(dx0, o.viewStart) : dx0;
	let x1 = o.viewEnd != null ? Math.min(dx1, o.viewEnd) : dx1;
	if (!(x1 > x0)) { x0 = dx0; x1 = dx1; }

	const main = traceOf(o.kind, o.data, x0, x1, max) ?? { x: [], lo: [], hi: [] };
	const cmpTraces = cmp.map((c) => ({ c, tr: decimateTrace(c.data.t, c.data.min, c.data.max, x0, x1, max) }));
	let lo = Infinity, hi = -Infinity;
	for (let i = 0; i < main.x.length; i++) { if (main.lo[i] < lo) lo = main.lo[i]; if (main.hi[i] > hi) hi = main.hi[i]; }
	for (const { tr } of cmpTraces) {
		for (let i = 0; i < tr.x.length; i++) {
			const m = (tr.lo[i] + tr.hi[i]) / 2;
			if (m < lo) lo = m;
			if (m > hi) hi = m;
		}
	}
	if (o.kind === 'line') lo = 0;
	if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
	if (hi === lo) hi = lo + 1;
	if (o.kind === 'env') {   // same "include 0 when cheap" rule as the on-screen chart
		const R = hi - lo;
		if (lo > 0 && lo <= R * 0.5) lo = 0; else if (hi < 0 && -hi <= R * 0.5) hi = 0;
	}

	const sx = (x: number) => mL + ((x - x0) / (x1 - x0)) * pw;
	const useLog = o.logY === true && o.kind === 'line' && hi > 0;
	let sy: (y: number) => number;
	let yticks: number[];
	if (useLog) {
		let minPos = Infinity;
		for (const v of main.hi) if (v > 0 && v < minPos) minPos = v;
		const floor = Math.max(isFinite(minPos) ? minPos : hi / 1e5, hi / 1e5);
		const L0 = Math.log10(floor), L1 = Math.log10(hi), den = (L1 - L0) || 1;
		sy = (y) => mT + (1 - (Math.log10(Math.max(y, floor)) - L0) / den) * ph;
		yticks = [];
		for (let k = Math.ceil(L0); k <= Math.floor(L1); k++) yticks.push(10 ** k);
		if (yticks.length < 2) yticks = [floor, hi];
	} else {
		sy = (y) => mT + (1 - (y - lo) / (hi - lo)) * ph;
		yticks = niceTicks(lo, hi, 5);
	}
	const xticks = niceTicks(x0, x1, Math.max(4, Math.round(pw / 90))).filter((t) => t >= x0 - 1e-9 && t <= x1 + 1e-9);

	const f1 = (v: number) => v.toFixed(1);
	const out: string[] = [head];
	out.push(`<defs><clipPath id="plot"><rect x="${mL}" y="${mT}" width="${pw}" height="${ph}"/></clipPath></defs>`);
	out.push('<g stroke="#5a5a5a" stroke-opacity="0.28" stroke-width="1">');
	for (const t of yticks) out.push(`<line x1="${mL}" x2="${mL + pw}" y1="${f1(sy(t))}" y2="${f1(sy(t))}"/>`);
	for (const t of xticks) out.push(`<line x1="${f1(sx(t))}" x2="${f1(sx(t))}" y1="${mT}" y2="${mT + ph}"/>`);
	out.push('</g>');
	if (o.kind === 'env' && lo < 0 && hi > 0) {
		out.push(`<line x1="${mL}" x2="${mL + pw}" y1="${f1(sy(0))}" y2="${f1(sy(0))}" stroke="#444" stroke-width="1"/>`);
	}

	const area = (tr: Trace, a = 0, b = tr.x.length - 1) => {
		let p = 'M';
		for (let i = a; i <= b; i++) p += `${f1(sx(tr.x[i]))},${f1(sy(tr.hi[i]))} `;
		p += 'L ';
		for (let i = b; i >= a; i--) p += `${f1(sx(tr.x[i]))},${f1(sy(tr.lo[i]))} `;
		return p + 'Z';
	};
	out.push('<g clip-path="url(#plot)">');
	if (o.kind === 'env' && main.x.length) {
		const hasCrop = o.cropStart != null && o.cropEnd != null;
		out.push(`<path d="${area(main)}" fill="${escapeXml(color)}" fill-opacity="${hasCrop ? 0.12 : 0.25}" stroke="${escapeXml(color)}" stroke-opacity="0.5" stroke-width="0.8"/>`);
		if (hasCrop) {
			// the analysed window at full saturation, as on screen, plus its two edges
			const a = main.x.findIndex((v) => v >= o.cropStart!);
			let b = -1;
			for (let k = main.x.length - 1; k >= 0; k--) if (main.x[k] <= o.cropEnd!) { b = k; break; }
			if (a >= 0 && b >= a) out.push(`<path d="${area(main, a, b)}" fill="${escapeXml(color)}" fill-opacity="0.35" stroke="${escapeXml(color)}" stroke-width="1"/>`);
			for (const t of [o.cropStart!, o.cropEnd!]) {
				if (t < x0 || t > x1) continue;
				out.push(`<line x1="${f1(sx(t))}" x2="${f1(sx(t))}" y1="${mT}" y2="${mT + ph}" stroke="#334155" stroke-width="1" stroke-dasharray="5 3"/>`);
			}
		}
	} else if (main.x.length) {
		let p = 'M';
		for (let i = 0; i < main.x.length; i++) p += `${f1(sx(main.x[i]))},${f1(sy(main.hi[i]))} `;
		out.push(`<path d="${p}" fill="none" stroke="${escapeXml(color)}" stroke-width="1.3"/>`);
	}
	for (const { c, tr } of cmpTraces) {
		let p = '';
		for (let i = 0; i < tr.x.length; i++) p += `${i ? 'L' : 'M'}${f1(sx(tr.x[i]))},${f1(sy((tr.lo[i] + tr.hi[i]) / 2))} `;
		if (p) out.push(`<path d="${p}" fill="none" stroke="${escapeXml(c.color)}" stroke-width="1.5" stroke-dasharray="6 3"/>`);
	}
	out.push('</g>');

	out.push(`<rect x="${mL}" y="${mT}" width="${pw}" height="${ph}" fill="none" stroke="#000" stroke-width="1.2"/>`);
	out.push('<g fill="#000" font-size="13" stroke="#000" stroke-width="1">');
	for (const t of xticks) {
		out.push(`<line x1="${f1(sx(t))}" x2="${f1(sx(t))}" y1="${mT + ph}" y2="${mT + ph + 5}"/>`
			+ `<text x="${f1(sx(t))}" y="${mT + ph + 20}" text-anchor="middle" stroke="none">${escapeXml(fmt(t))}</text>`);
	}
	for (const t of yticks) {
		out.push(`<line x1="${mL - 5}" x2="${mL}" y1="${f1(sy(t))}" y2="${f1(sy(t))}"/>`
			+ `<text x="${mL - 9}" y="${f1(sy(t) + 4)}" text-anchor="end" stroke="none">${escapeXml(fmt(t))}</text>`);
	}
	out.push('</g>');

	// axis titles, with units
	const xTitle = o.kind === 'env' ? 'Time' : 'Frequency';
	const xLab = o.xUnit ? `${xTitle} (${o.xUnit})` : xTitle;
	const yLab = yAxisTitle(o.kind, o.yUnit, useLog) || (o.kind === 'env' ? 'Force' : 'Amplitude');
	out.push(`<text x="${mL + pw / 2}" y="${mT + ph + 44}" text-anchor="middle" font-size="15" font-style="italic" fill="#000">${escapeXml(xLab)}</text>`);
	out.push(`<text transform="translate(20 ${mT + ph / 2}) rotate(-90)" text-anchor="middle" font-size="15" font-style="italic" fill="#000">${escapeXml(yLab)}</text>`);

	// legend: this cut plus each comparison cut
	if (cmp.length) {
		const y = H - 14;
		let x = mL;
		const entries = [{ label: o.opLabel || o.title, color, dash: '' }, ...cmp.map((c) => ({ label: c.label, color: c.color, dash: ' stroke-dasharray="6 3"' }))];
		for (const e of entries) {
			out.push(`<line x1="${x}" x2="${x + 24}" y1="${y - 4}" y2="${y - 4}" stroke="${escapeXml(e.color)}" stroke-width="2"${e.dash}/>`
				+ `<text x="${x + 30}" y="${y}" font-size="13" fill="#000">${escapeXml(e.label)}</text>`);
			x += 30 + e.label.length * 7 + 18;
		}
	}
	out.push('</svg>');
	return out.join('');
}

export function svgBlob(svg: string): Blob { return new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }); }

/** Rasterise an SVG string at `scale`x its size (default 2) through an offscreen canvas. */
export function svgToPngBlob(svg: string, width: number, height: number, scale = 2): Promise<Blob> {
	return new Promise((resolve, reject) => {
		const url = URL.createObjectURL(svgBlob(svg));
		const img = new Image();
		img.onload = () => {
			try {
				const cv = document.createElement('canvas');
				cv.width = Math.round(width * scale); cv.height = Math.round(height * scale);
				const g = cv.getContext('2d');
				if (!g) throw new Error('no 2d context');
				g.fillStyle = '#fff'; g.fillRect(0, 0, cv.width, cv.height);
				g.drawImage(img, 0, 0, cv.width, cv.height);
				cv.toBlob((b) => (b ? resolve(b) : reject(new Error('PNG encode failed'))), 'image/png');
			} catch (e) { reject(e); } finally { URL.revokeObjectURL(url); }
		};
		img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('SVG failed to load')); };
		img.src = url;
	});
}

/** Build the SVG and save it as `<base>.svg` or `<base>.png`. Resolves false if it could not. */
export async function saveChartImage(o: ChartSvgOpts, format: 'svg' | 'png', base: string): Promise<boolean> {
	const svg = buildChartSvg(o);
	try {
		if (format === 'svg') downloadBlob(svgBlob(svg), `${base}.svg`);
		else downloadBlob(await svgToPngBlob(svg, o.width ?? 900, o.height ?? 420, 2), `${base}.png`);
		return true;
	} catch { return false; }
}
