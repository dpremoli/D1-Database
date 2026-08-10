import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ConfigStore, defaultConfig } from './config';

describe('ConfigStore', () => {
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-app-config-'));
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('seeds config.json with defaults on first run', () => {
    const store = new ConfigStore(dir);
    const cfg = store.seedIfMissing();
    expect(cfg).toEqual(defaultConfig());
    expect(fs.existsSync(path.join(dir, 'config.json'))).toBe(true);
  });

  it('leaves an existing config.json untouched on a second seed call', () => {
    const store = new ConfigStore(dir);
    store.seedIfMissing();
    store.write({ ...defaultConfig(), directusUrl: 'https://custom.example' });
    const cfg = store.seedIfMissing();
    expect(cfg.directusUrl).toBe('https://custom.example');
  });

  it('setRecorderPort patches only recorderUrl, preserving other fields', () => {
    const store = new ConfigStore(dir);
    store.seedIfMissing();
    store.write({ ...defaultConfig(), directusUrl: 'https://custom.example' });
    const cfg = store.setRecorderPort(8231);
    expect(cfg.recorderUrl).toBe('http://127.0.0.1:8231');
    expect(cfg.directusUrl).toBe('https://custom.example');
  });
});
