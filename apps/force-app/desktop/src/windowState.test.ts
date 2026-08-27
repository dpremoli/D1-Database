import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { WindowStateStore, isOnSomeDisplay } from './windowState';

let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'window-state-test-'));
});
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('WindowStateStore', () => {
  it('returns undefined for a key that was never saved', () => {
    const store = new WindowStateStore(dir);
    expect(store.get('main')).toBeUndefined();
  });

  it('round-trips saved bounds', () => {
    const store = new WindowStateStore(dir);
    store.save('main', { x: 10, y: 20, width: 1500, height: 950 });

    expect(store.get('main')).toEqual({ x: 10, y: 20, width: 1500, height: 950 });
  });

  it('keeps different keys independent, e.g. main window vs. a pop-out', () => {
    const store = new WindowStateStore(dir);
    store.save('main', { width: 1500, height: 950 });
    store.save('/live/force', { width: 1400, height: 900 });

    expect(store.get('main')).toEqual({ width: 1500, height: 950 });
    expect(store.get('/live/force')).toEqual({ width: 1400, height: 900 });
  });

  it('persists across separate store instances (same file on disk)', () => {
    new WindowStateStore(dir).save('main', { width: 1600, height: 1000, maximized: true });

    expect(new WindowStateStore(dir).get('main')).toEqual({ width: 1600, height: 1000, maximized: true });
  });

  it('does not throw when the underlying file is missing or corrupt', () => {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'window-state.json'), '{ not valid json');

    expect(new WindowStateStore(dir).get('main')).toBeUndefined();
  });
});

describe('isOnSomeDisplay', () => {
  // A typical single-monitor desktop, minus the taskbar.
  const one = [{ x: 0, y: 0, width: 1920, height: 1080 }];
  // Plus a second monitor placed to the left, as Windows reports it (negative origin).
  const two = [...one, { x: -1920, y: 0, width: 1920, height: 1080 }];

  it('accepts a window fully inside a display', () => {
    expect(isOnSomeDisplay({ x: 100, y: 100, width: 800, height: 600 }, one)).toBe(true);
  });

  it('accepts a window straddling two displays', () => {
    expect(isOnSomeDisplay({ x: -200, y: 100, width: 800, height: 600 }, two)).toBe(true);
  });

  it('rejects a window on a monitor that is no longer connected', () => {
    // Saved while the left-hand monitor was attached; now only the primary remains.
    expect(isOnSomeDisplay({ x: -1800, y: 100, width: 800, height: 600 }, one)).toBe(false);
  });

  it('rejects the off-screen origin Windows reports for a minimized window', () => {
    expect(isOnSomeDisplay({ x: -32000, y: -32000, width: 800, height: 600 }, one)).toBe(false);
  });

  it('treats bounds with no saved position as acceptable (Electron will place it)', () => {
    expect(isOnSomeDisplay({ width: 800, height: 600 }, one)).toBe(true);
  });

  it('accepts anything when no displays are reported, rather than discarding placement', () => {
    expect(isOnSomeDisplay({ x: 10, y: 10, width: 800, height: 600 }, [])).toBe(true);
  });
});
