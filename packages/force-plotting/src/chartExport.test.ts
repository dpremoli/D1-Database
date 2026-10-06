import { describe, expect, it } from 'vitest';
import { buildChartSvg, decimateTrace, escapeXml } from './chartExport';

const env = (n: number) => {
	const t = Array.from({ length: n }, (_, i) => i * 0.1);
	return { t, min: t.map((_, i) => -5 - (i % 7)), max: t.map((_, i) => 5 + (i % 11)) };
};

describe('buildChartSvg', () => {
	it('carries the title, axis titles with units and the viewBox size', () => {
		const svg = buildChartSvg({ opLabel: 'AB-12 / pass 3', title: 'Fx · force', kind: 'env', data: env(50), xUnit: 's', yUnit: 'N', width: 800, height: 400 });
		expect(svg).toContain('viewBox="0 0 800 400"');
		expect(svg).toContain('AB-12 / pass 3 · Fx · force');
		expect(svg).toContain('Time (s)');
		expect(svg).toContain('Force (N)');
		expect(svg).toContain('fill="#fff"');
	});
	it('titles a spectrum with its units', () => {
		const f = Array.from({ length: 40 }, (_, i) => i + 1);
		const svg = buildChartSvg({ title: 'Fz · spectrum', kind: 'line', data: { f, amp: f.map((v) => 100 / v) }, xUnit: 'Hz', yUnit: 'N', logY: true });
		expect(svg).toContain('Frequency (Hz)');
		expect(svg).toContain('Amplitude (log scale) (N)');
	});
	it('escapes text from labels', () => {
		const svg = buildChartSvg({
			opLabel: 'A<B> & "C"', title: 'Fx', kind: 'env', data: env(10), yUnit: 'N',
			compare: [{ id: 'x', label: "it's <b>", color: '#f00', data: env(10) }],
		});
		expect(svg).toContain('A&lt;B&gt; &amp; &quot;C&quot;');
		expect(svg).toContain('it&apos;s &lt;b&gt;');
		expect(svg).not.toContain('<b>');
		expect(escapeXml('&<>"\'')).toBe('&amp;&lt;&gt;&quot;&apos;');
	});
	it('draws the compare legend and the crop band', () => {
		const svg = buildChartSvg({
			opLabel: 'Pass 1', title: 'Fy · force', kind: 'env', data: env(60), cropStart: 1, cropEnd: 4,
			compare: [{ id: 'a', label: 'Pass 2', color: '#f59e0b', data: env(60) }],
		});
		expect(svg).toContain('Pass 2');
		expect(svg).toContain('stroke="#f59e0b"');
		expect(svg).toContain('stroke-dasharray="5 3"');
	});
	it('renders a no-data figure for an empty series', () => {
		const svg = buildChartSvg({ title: 'Fx · force', kind: 'env', data: null });
		expect(svg).toContain('no data');
		expect(svg.endsWith('</svg>')).toBe(true);
	});
	it('decimates long traces to the point budget', () => {
		const d = env(100000);
		const tr = decimateTrace(d.t, d.min, d.max, d.t[0], d.t[d.t.length - 1], 500);
		expect(tr.x.length).toBeLessThanOrEqual(500);
		expect(Math.max(...tr.hi)).toBe(Math.max(...d.max));
		expect(Math.min(...tr.lo)).toBe(Math.min(...d.min));
		const svg = buildChartSvg({ title: 'Fx', kind: 'env', data: d, maxPoints: 500 });
		expect(svg.length).toBeLessThan(40000);
	});
});
