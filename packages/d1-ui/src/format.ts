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
