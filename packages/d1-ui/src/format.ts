// Small display helpers shared by the pages.

const EN_GB = 'en-GB';

export function formatDate(value: string | null | undefined, fallback = ''): string {
	if (!value) return fallback;
	const d = new Date(value);
	if (Number.isNaN(d.getTime())) return fallback;
	return d.toLocaleDateString(EN_GB, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function formatNumber(value: number | string | null | undefined, unit = '', digits = 3): string {
	if (value === null || value === undefined || value === '') return '';
	const n = Number(value);
	if (!Number.isFinite(n)) return '';
	// toLocaleString rounds, and "20.000" would suggest a precision nobody measured.
	const text = n.toLocaleString(EN_GB, { maximumFractionDigits: digits });
	return unit ? `${text} ${unit}` : text;
}

// Text for a visible error from an Axios/Directus failure.
export function errorText(e: any, fallback = 'Request failed'): string {
	return e?.response?.data?.errors?.[0]?.message || e?.message || fallback;
}

// A record that is missing and one the signed-in user may not read look the same on purpose
// (Directus answers 403 for both, d1-trace 404).
export function isNotVisible(e: any): boolean {
	const status = e?.response?.status;
	return status === 403 || status === 404;
}

// A measured quantity for display. formatNumber() rounds to a fixed number of decimals, which
// turns a strain rate of 0.000001 into "0"; this keeps the leading digits whatever the size:
// tiny values switch to exponent form, large ones drop the noise decimals, trailing zeros go.
export function formatQuantity(value: number | string | null | undefined): string {
	if (value === null || value === undefined || value === '') return '';
	const n = typeof value === 'number' ? value : Number(value);
	if (!Number.isFinite(n)) return '';
	if (n === 0) return '0';
	const abs = Math.abs(n);
	if (abs < 0.001 || abs >= 1e9) return n.toExponential(2).replace(/\.?0+e/, 'e').replace('e+', 'e');
	const digits = abs >= 1000 ? 1 : abs >= 1 ? 3 : 5;
	return n.toLocaleString(EN_GB, { maximumFractionDigits: digits });
}
