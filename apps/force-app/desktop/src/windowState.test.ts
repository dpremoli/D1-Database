import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { WindowStateStore } from './windowState';

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
