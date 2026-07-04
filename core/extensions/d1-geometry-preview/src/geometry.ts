// Parametric isometric geometry engine for the sample creator.
//
// Draws a scaled 3-D (isometric, z-up) view of a specimen from its real dimensions,
// with dimension markers like a technical drawing. The shape stretches with the
// measurements (a long thin plate looks long and thin), and standard test coupons
// (ASTM E8 tensile, bend bar) start from standard dimensions that stay editable.

export interface Dims {
	form: string | null;
	diameter_mm?: number | null;
	length_mm?: number | null;
	width_mm?: number | null;
	thickness_mm?: number | null;
	gauge_length_mm?: number | null;
	gauge_width_mm?: number | null;
}

// Standard presets. Tensile = ASTM E8/E8M sheet-type (12.5 mm wide reduced section,
// 50 mm gauge, 200 mm long, 20 mm grip). Bend/fatigue = a plain rectangular bar.
export const PRESETS: Record<string, Partial<Dims>> = {
	tensile_coupon: { length_mm: 200, width_mm: 20, thickness_mm: 3, gauge_length_mm: 50, gauge_width_mm: 12.5 },
	bend_bar: { length_mm: 100, width_mm: 15, thickness_mm: 10 },
};

// Which dimension inputs are relevant per form.
export const FORM_FIELDS: Record<string, string[]> = {
	disc: ['diameter_mm', 'thickness_mm'],
	cylinder: ['diameter_mm', 'length_mm'],
	bar: ['width_mm', 'thickness_mm', 'length_mm'],
	block: ['width_mm', 'length_mm', 'thickness_mm'],
	plate: ['width_mm', 'length_mm', 'thickness_mm'],
	tensile_coupon: ['length_mm', 'width_mm', 'thickness_mm', 'gauge_length_mm', 'gauge_width_mm'],
	bend_bar: ['length_mm', 'width_mm', 'thickness_mm'],
	powder: [],
	other: [],
};

const LABELS: Record<string, string> = {
	diameter_mm: 'Ø Diameter (mm)', length_mm: 'Length (mm)', width_mm: 'Width (mm)',
	thickness_mm: 'Thickness (mm)', gauge_length_mm: 'Gauge length (mm)', gauge_width_mm: 'Gauge width (mm)',
};
export const fieldLabel = (k: string) => LABELS[k] || k;

export const FORMS = [
	{ text: 'Disc', value: 'disc' },
	{ text: 'Cylinder', value: 'cylinder' },
	{ text: 'Block', value: 'block' },
	{ text: 'Plate', value: 'plate' },
	{ text: 'Bar', value: 'bar' },
	{ text: 'Tensile coupon (ASTM E8)', value: 'tensile_coupon' },
	{ text: 'Bend / fatigue bar', value: 'bend_bar' },
	{ text: 'Powder / compact', value: 'powder' },
	{ text: 'Other', value: 'other' },
];

// ── isometric projection (z up) ────────────────────────────────────────────────
const A = Math.PI / 6, CA = Math.cos(A), SA = Math.sin(A), R2 = Math.SQRT2;
type P3 = [number, number, number];
type P2 = [number, number];
const iso = (x: number, y: number, z: number): P2 => [(x - y) * CA, (x + y) * SA - z];

interface Face { pts: P3[]; cls: string }
interface Dim { a: P3; b: P3; label: string }
interface Circle { cx: number; cy: number; cz: number; r: number }

const VW = 260, VH = 210, PAD = 24;

function fitter(faces: Face[], dims: Dim[], circles: Circle[]) {
	const pts: P2[] = [];
	faces.forEach((f) => f.pts.forEach((p) => pts.push(iso(...p))));
	dims.forEach((d) => { pts.push(iso(...d.a), iso(...d.b)); });
	circles.forEach((c) => { for (let t = 0; t < 12; t++) { const th = (t / 12) * 2 * Math.PI; pts.push(iso(c.cx + c.r * Math.cos(th), c.cy + c.r * Math.sin(th), c.cz)); } });
	const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
	const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
	const s = Math.min((VW - 2 * PAD) / ((maxX - minX) || 1), (VH - 2 * PAD) / ((maxY - minY) || 1));
	const ox = PAD - minX * s + (VW - 2 * PAD - (maxX - minX) * s) / 2;
	const oy = PAD - minY * s + (VH - 2 * PAD - (maxY - minY) * s) / 2;
	const to = (p: P3): P2 => { const q = iso(...p); return [q[0] * s + ox, q[1] * s + oy]; };
	return { to, s };
}

const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

function svgWrap(inner: string) {
	return `<svg viewBox="0 0 ${VW} ${VH}" xmlns="http://www.w3.org/2000/svg">`
		+ `<defs><marker id="ga" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">`
		+ `<path d="M0.5,0.5 L6,3 L0.5,5.5" fill="none" stroke="#475569" stroke-width="1"/></marker></defs>${inner}</svg>`;
}

function drawDims(dims: Dim[], to: (p: P3) => P2): string {
	return dims.map((d) => {
		const a = to(d.a), b = to(d.b);
		const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
		return `<line x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}" class="gdim" marker-start="url(#ga)" marker-end="url(#ga)"/>`
			+ `<text x="${mx.toFixed(1)}" y="${(my - 3).toFixed(1)}" class="gdimt">${d.label}</text>`;
	}).join('');
}

function faceSvg(f: Face, to: (p: P3) => P2): string {
	return `<polygon points="${f.pts.map(to).map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')}" class="${f.cls}"/>`;
}

// Box W(x) × L(y) × H(z) with the three viewer-facing faces (top, y=L, x=W — they
// meet at the near vertical edge) + W/L/H dimension markers along the visible edges.
function boxFacesDims(W: number, L: number, H: number, off: number) {
	const faces: Face[] = [
		{ cls: 'gt', pts: [[0, 0, H], [W, 0, H], [W, L, H], [0, L, H]] }, // top
		{ cls: 'gl', pts: [[0, L, 0], [W, L, 0], [W, L, H], [0, L, H]] }, // front-left (y=L)
		{ cls: 'gr', pts: [[W, 0, 0], [W, L, 0], [W, L, H], [W, 0, H]] }, // front-right (x=W)
	];
	const dims: Dim[] = [
		{ a: [0, L + off, 0], b: [W, L + off, 0], label: `${fmt(W)}` }, // width along the front-left base
		{ a: [W + off, 0, 0], b: [W + off, L, 0], label: `${fmt(L)}` }, // length along the right base
		{ a: [W + off, L, 0], b: [W + off, L, H], label: `${fmt(H)}` }, // height at the near edge
	];
	return { faces, dims };
}

function boxSvg(W: number, L: number, H: number): string {
	const off = 0.16 * Math.max(W, L, H);
	const { faces, dims } = boxFacesDims(W, L, H, off);
	const { to } = fitter(faces, dims, []);
	return svgWrap(faces.map((f) => faceSvg(f, to)).join('') + drawDims(dims, to));
}

// Round solid (cylinder / disc): diameter D, height H along z.
function cylSvg(D: number, H: number): string {
	const Rr = D / 2;
	const circles: Circle[] = [{ cx: Rr, cy: Rr, cz: 0, r: Rr }, { cx: Rr, cy: Rr, cz: H, r: Rr }];
	const off = 0.18 * Math.max(D, H);
	const dims: Dim[] = [
		{ a: [-off, Rr, 0], b: [-off, Rr, H], label: `${fmt(H)}` },
	];
	const { to, s } = fitter([], dims, circles);
	const topC = to([Rr, Rr, H]), botC = to([Rr, Rr, 0]);
	const rx = Rr * CA * R2 * s, ry = Rr * SA * R2 * s;
	const body = `<path d="M${(topC[0] - rx).toFixed(1)} ${topC[1].toFixed(1)} L${(botC[0] - rx).toFixed(1)} ${botC[1].toFixed(1)} `
		+ `A${rx.toFixed(1)} ${ry.toFixed(1)} 0 0 0 ${(botC[0] + rx).toFixed(1)} ${botC[1].toFixed(1)} `
		+ `L${(topC[0] + rx).toFixed(1)} ${topC[1].toFixed(1)} Z" class="gl"/>`;
	const top = `<ellipse cx="${topC[0].toFixed(1)}" cy="${topC[1].toFixed(1)}" rx="${rx.toFixed(1)}" ry="${ry.toFixed(1)}" class="gt"/>`;
	// diameter marker across the top ellipse
	const dimD = `<line x1="${(topC[0] - rx).toFixed(1)} " y1="${(topC[1] - ry - 8).toFixed(1)}" x2="${(topC[0] + rx).toFixed(1)}" y2="${(topC[1] - ry - 8).toFixed(1)}" class="gdim" marker-start="url(#ga)" marker-end="url(#ga)"/>`
		+ `<text x="${topC[0].toFixed(1)}" y="${(topC[1] - ry - 11).toFixed(1)}" class="gdimt">Ø${fmt(D)}</text>`;
	return svgWrap(body + top + dimD + drawDims(dims, to));
}

// Flat tensile dogbone: overall L(y) × grip W(x) × thickness T(z), reduced to gauge
// width Wg over gauge length Lg with straight fillet tapers. Extruded for thickness.
function couponSvg(L: number, W: number, T: number, Lg: number, Wg: number): string {
	const cx = W / 2, gh = Wg / 2, wh = W / 2;
	const y1 = (L - Lg) / 2, y2 = (L + Lg) / 2;             // reduced-section span
	const fil = Math.min((L - Lg) / 2 * 0.6, W);            // taper length
	// right-hand outline, bottom→top (x offset from centre, y along length)
	const right: P2[] = [
		[cx + wh, 0], [cx + wh, y1 - fil], [cx + gh, y1], [cx + gh, y2], [cx + wh, y2 + fil], [cx + wh, L],
	];
	const outline: P2[] = [...right, ...right.map((p) => [W - p[0], p[1]] as P2).reverse()];
	const off = 0.14 * L;
	const dims: Dim[] = [
		{ a: [-off, 0, 0], b: [-off, L, 0], label: `${fmt(L)}` },                 // overall length
		{ a: [cx - gh, (L / 2) - off * 0.4, 0], b: [cx + gh, (L / 2) - off * 0.4, 0], label: `${fmt(Wg)}` }, // gauge width
		{ a: [W + off, y1, 0], b: [W + off, y2, 0], label: `G ${fmt(Lg)}` },       // gauge length
	];
	const top: Face = { cls: 'gt', pts: outline.map((p) => [p[0], p[1], T]) };
	const bot: Face = { cls: 'gl', pts: outline.map((p) => [p[0], p[1], 0]) };
	// extrude walls
	const walls: Face[] = [];
	for (let i = 0; i < outline.length; i++) {
		const p = outline[i], q = outline[(i + 1) % outline.length];
		walls.push({ cls: 'gr', pts: [[p[0], p[1], 0], [q[0], q[1], 0], [q[0], q[1], T], [p[0], p[1], T]] });
	}
	const { to } = fitter([top, bot, ...walls], dims, []);
	return svgWrap(faceSvg(bot, to) + walls.map((w) => faceSvg(w, to)).join('') + faceSvg(top, to) + drawDims(dims, to));
}

// Bend / fatigue bar: a long box with two supports and a central load arrow (3-pt).
function bendSvg(L: number, W: number, H: number): string {
	const off = 0.16 * Math.max(L, W, H);
	const { faces, dims } = boxFacesDims(W, L, H, off);
	const { to } = fitter(faces, dims, []);
	let markers = '';
	// supports under the front-bottom edge at 1/6 and 5/6 of length
	for (const fy of [1 / 6, 5 / 6]) {
		const b = to([W / 2, fy * L, 0]);
		markers += `<path d="M${(b[0] - 5).toFixed(1)} ${(b[1] + 12).toFixed(1)} L${b[0].toFixed(1)} ${(b[1] + 2).toFixed(1)} L${(b[0] + 5).toFixed(1)} ${(b[1] + 12).toFixed(1)} Z" class="gsupport"/>`;
	}
	// central downward load arrow on top
	const c = to([W / 2, L / 2, H]);
	markers += `<line x1="${c[0].toFixed(1)}" y1="${(c[1] - 20).toFixed(1)}" x2="${c[0].toFixed(1)}" y2="${(c[1] - 3).toFixed(1)}" class="gload" marker-end="url(#ga)"/>`;
	return svgWrap(faces.map((f) => faceSvg(f, to)).join('') + drawDims(dims, to) + markers);
}

function powderSvg(): string {
	const dots = ['33,62', '45,64', '57,63', '69,64', '39,56', '51,54', '63,57', '50,48']
		.map((p) => { const [x, y] = p.split(','); return `<circle cx="${x}" cy="${y}" r="2.4" class="gh"/>`; }).join('');
	return `<svg viewBox="0 0 100 92" xmlns="http://www.w3.org/2000/svg">`
		+ `<ellipse cx="50" cy="70" rx="34" ry="13" class="gl"/><path d="M18 70 Q50 30 82 70 Z" class="gt"/>${dots}</svg>`;
}

const num = (v: any, def: number): number => {
	const x = typeof v === 'string' ? parseFloat(v) : v;
	return typeof x === 'number' && !Number.isNaN(x) && x > 0 ? x : def;
};

export function buildGeometry(d: Dims): string {
	const g = (d.form || '').toLowerCase();
	if (!g || g === 'other') return '';
	if (g.includes('powder')) return powderSvg();
	if (g.includes('disc')) return cylSvg(num(d.diameter_mm, 30), num(d.thickness_mm ?? d.length_mm, 8));
	if (/cylind|rod/.test(g)) return cylSvg(num(d.diameter_mm, 25), num(d.length_mm, 50));
	if (g.includes('tensile') || g.includes('coupon')) {
		const L = num(d.length_mm, 200), W = num(d.width_mm, 20), T = num(d.thickness_mm, 3);
		const Lg = Math.min(num(d.gauge_length_mm, 50), L * 0.9);
		const Wg = Math.min(num(d.gauge_width_mm, 12.5), W * 0.95);
		return couponSvg(L, W, T, Lg, Wg);
	}
	if (g.includes('bend')) return bendSvg(num(d.length_mm, 100), num(d.width_mm, 15), num(d.thickness_mm, 10));
	// block / plate / bar → box
	return boxSvg(num(d.width_mm, 24), num(d.length_mm, 40), num(d.thickness_mm, g.includes('plate') ? 5 : 20));
}

export function dimsText(d: Dims): string {
	const g = (d.form || '').toLowerCase();
	const keys = FORM_FIELDS[g] || [];
	const short: Record<string, string> = { diameter_mm: 'Ø', length_mm: 'L', width_mm: 'W', thickness_mm: 't', gauge_length_mm: 'G', gauge_width_mm: 'Wg' };
	const parts = keys.filter((k) => (d as any)[k]).map((k) => `${short[k]}${(d as any)[k]}`);
	return parts.length ? parts.join(' · ') + ' mm' : '';
}
