// CSV export helpers shared by the Plot dashboard's tables (signal statistics, wear trend,
// diagnostics clusters) and the FRM PNG export. Pure text building plus one browser download
// path; the table views own their column lists, so units live in the header names (mean_fx_N).
import { ref } from 'vue';

export interface CsvColumn<T> {
	/** Header cell, units included (e.g. `mean_fx_N`). */
	header: string;
	/** Cell value; NaN, infinities, null and undefined export as an empty cell. */
	value: (row: T) => string | number | boolean | null | undefined;
}

// RFC 4180: quote a cell containing a comma, quote, CR or LF, doubling embedded quotes.
function cell(v: string | number | boolean | null | undefined): string {
	if (v == null) return '';
	if (typeof v === 'number' && !Number.isFinite(v)) return '';
	const s = String(v);
	return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Header row plus one line per row, CRLF-separated and CRLF-terminated (RFC 4180). */
export function toCsv<T>(columns: CsvColumn<T>[], rows: T[]): string {
	const lines = [columns.map((c) => cell(c.header)).join(',')];
	for (const r of rows) lines.push(columns.map((c) => cell(c.value(r))).join(','));
	return lines.join('\r\n') + '\r\n';
}

/** Make a string safe to embed in a download filename (operation tags can hold `/` or spaces). */
export function safeFilePart(s: string | null | undefined): string {
	return String(s ?? '').trim().replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '');
}

/** Save a Blob through a temporary `<a download>`. Shared with the FRM PNG export. */
export function downloadBlob(blob: Blob, filename: string) {
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url; a.download = filename;
	document.body.appendChild(a); a.click(); a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadText(filename: string, text: string, mime = 'text/csv;charset=utf-8') {
	// A BOM lets Excel read UTF-8 CSV without mangling non-ASCII characters.
	const bom = mime.startsWith('text/csv') ? '﻿' : '';
	downloadBlob(new Blob([bom + text], { type: mime }), filename);
}

/** Copy text to the clipboard; resolves false when the browser refuses (no permission, no HTTPS). */
export async function copyText(text: string): Promise<boolean> {
	try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

/** A "Copy" button's action plus a `copied` flag that reads true for 1.5 s after a successful copy.
 *  Nothing is copied when `text()` is empty. */
export function useCopyFeedback(text: () => string) {
	const copied = ref(false);
	async function copy() {
		const t = text();
		if (!t || !(await copyText(t))) return;
		copied.value = true;
		setTimeout(() => { copied.value = false; }, 1500);
	}
	return { copied, copy };
}
