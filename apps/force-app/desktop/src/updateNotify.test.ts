import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { APP_USER_MODEL_ID, isUpdateCheckArgv, shouldNotifyReady } from './updateNotify';

const base = { version: '2.0.0', notifiedVersion: null, recording: false, hasWindow: true, focused: false };

describe('shouldNotifyReady', () => {
  it('notifies when the window is not focused', () => expect(shouldNotifyReady(base)).toBe(true));
  it('not when focused', () => expect(shouldNotifyReady({ ...base, focused: true })).toBe(false));
  it('not while recording', () => expect(shouldNotifyReady({ ...base, recording: true })).toBe(false));
  it('not twice for the same version', () => expect(shouldNotifyReady({ ...base, notifiedVersion: '2.0.0' })).toBe(false));
  it('again for a newer version', () => expect(shouldNotifyReady({ ...base, notifiedVersion: '1.9.0' })).toBe(true));
  it('not without a window', () => expect(shouldNotifyReady({ ...base, hasWindow: false })).toBe(false));
});

describe('isUpdateCheckArgv', () => {
  it('finds the flag anywhere after the exe', () => {
    expect(isUpdateCheckArgv(['C:\\Force App.exe', '--update-check'])).toBe(true);
    expect(isUpdateCheckArgv(['x', '--foo', '--update-check'])).toBe(true);
  });
  it('is false for a normal launch', () => expect(isUpdateCheckArgv(['C:\\Force App.exe'])).toBe(false));
});

describe('APP_USER_MODEL_ID', () => {
  it('equals electron-builder.yml appId (Windows toasts need the match)', () => {
    const yml = fs.readFileSync(path.join(__dirname, '..', 'electron-builder.yml'), 'utf-8');
    expect(yml.match(/^appId:\s*(\S+)/m)?.[1]).toBe(APP_USER_MODEL_ID);
  });
});
