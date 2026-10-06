// R13: what the "update downloaded" dialog says about the release. electron-updater hands over
// `info.releaseNotes` as an HTML string (GitHub releases), or as an array of { version, note } when
// it was asked for several versions at once. A native dialog shows plain text only, and a long
// changelog would push the buttons off screen, so it is flattened and trimmed here.

export const RELEASE_NOTES_MAX_CHARS = 1500;
export const RELEASE_NOTES_TRUNCATED = '… full notes in Settings → About';

const ENTITIES: Record<string, string> = {
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#39;': "'",
  '&apos;': "'",
  '&nbsp;': ' ',
};

/** HTML to readable plain text: block ends become line breaks, list items get a dash, the rest of
 * the tags go, and the common entities are decoded. */
export function htmlToPlainText(html: string): string {
  return html
    .replace(/<\s*(script|style)\b[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi, '')
    .replace(/<\s*br\s*\/?>/gi, '\n')
    .replace(/<\s*li\b[^>]*>/gi, '\n- ')
    .replace(/<\s*\/\s*(p|div|h[1-6]|ul|ol|tr|pre|blockquote)\s*>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&(?:amp|lt|gt|quot|#39|apos|nbsp);/g, (m) => ENTITIES[m])
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function notesOf(raw: unknown): string {
  if (typeof raw === 'string') return htmlToPlainText(raw);
  if (!Array.isArray(raw)) return '';
  const entries = raw
    .map((e) => {
      const rec = (e ?? {}) as { version?: unknown; note?: unknown };
      return { version: typeof rec.version === 'string' ? rec.version : '', note: typeof rec.note === 'string' ? htmlToPlainText(rec.note) : '' };
    })
    .filter((e) => e.note);
  // One version needs no heading; several would otherwise run together.
  if (entries.length === 1) return entries[0].note;
  return entries.map((e) => (e.version ? `${e.version}\n${e.note}` : e.note)).join('\n\n');
}

/** The release notes as plain text for the dialog, '' when there are none. */
export function formatReleaseNotes(raw: unknown, maxChars = RELEASE_NOTES_MAX_CHARS): string {
  const text = notesOf(raw);
  if (text.length <= maxChars) return text;
  let cut = text.slice(0, maxChars);
  // Don't split a surrogate pair, and prefer to stop at a line or word end.
  if (/[\ud800-\udbff]$/.test(cut)) cut = cut.slice(0, -1);
  const boundary = Math.max(cut.lastIndexOf('\n'), cut.lastIndexOf(' '));
  if (boundary > maxChars * 0.6) cut = cut.slice(0, boundary);
  return `${cut.trimEnd()}${RELEASE_NOTES_TRUNCATED}`;
}
