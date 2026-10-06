import { describe, expect, it } from 'vitest';
import { RELEASE_NOTES_MAX_CHARS, RELEASE_NOTES_TRUNCATED, formatReleaseNotes, htmlToPlainText } from './releaseNotes';

describe('htmlToPlainText', () => {
  it('turns lists and paragraphs into lines and drops other tags', () => {
    const html = '<h2>What\'s new</h2><ul><li>Fixed <b>flat</b> forces</li><li>Faster &amp; safer</li></ul><p>Thanks</p>';
    expect(htmlToPlainText(html)).toBe("What's new\n\n- Fixed flat forces\n- Faster & safer\nThanks");
  });
  it('drops script and style blocks entirely', () => {
    expect(htmlToPlainText('a<script>alert(1)</script>b<style>p{}</style>c')).toBe('abc');
  });
  it('decodes the common entities', () => {
    expect(htmlToPlainText('1 &lt; 2 &gt; 0 &quot;x&quot; &#39;y&#39;&nbsp;z')).toBe('1 < 2 > 0 "x" \'y\' z');
  });
});

describe('formatReleaseNotes', () => {
  it('is empty when there are no notes', () => {
    expect(formatReleaseNotes(undefined)).toBe('');
    expect(formatReleaseNotes(null)).toBe('');
    expect(formatReleaseNotes('')).toBe('');
    expect(formatReleaseNotes([])).toBe('');
    expect(formatReleaseNotes([{ version: '1.0.0', note: null }])).toBe('');
  });
  it('flattens an HTML string', () => {
    expect(formatReleaseNotes('<p>Fix <i>one</i></p>')).toBe('Fix one');
  });
  it('uses a single array entry without a heading', () => {
    expect(formatReleaseNotes([{ version: '2.0.0', note: '<p>Only this</p>' }])).toBe('Only this');
  });
  it('labels each version when there are several', () => {
    expect(
      formatReleaseNotes([
        { version: '2.0.0', note: '<p>B</p>' },
        { version: '1.9.0', note: '<p>A</p>' },
      ]),
    ).toBe('2.0.0\nB\n\n1.9.0\nA');
  });
  it('ignores values of the wrong type', () => {
    expect(formatReleaseNotes(42)).toBe('');
    expect(formatReleaseNotes([null, 3, { version: 1, note: 'ok' }])).toBe('ok');
  });
  it('trims long notes and says where the rest is', () => {
    const long = Array.from({ length: 400 }, (_, i) => `word${i}`).join(' ');
    const out = formatReleaseNotes(long);
    expect(out.endsWith(RELEASE_NOTES_TRUNCATED)).toBe(true);
    expect(out.length).toBeLessThanOrEqual(RELEASE_NOTES_MAX_CHARS + RELEASE_NOTES_TRUNCATED.length);
    // cut at a word boundary, not mid-word
    expect(out.replace(RELEASE_NOTES_TRUNCATED, '')).toMatch(/word\d+$/);
  });
  it('leaves notes at the limit untouched', () => {
    const exact = 'a'.repeat(RELEASE_NOTES_MAX_CHARS);
    expect(formatReleaseNotes(exact)).toBe(exact);
  });
});
