import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('electron', () => ({ shell: { openExternal: vi.fn() } }));

import { shell } from 'electron';
import { classifyWindowOpen } from './windowOpen';

function details(url: string) {
  return { url } as Electron.HandlerDetails;
}

describe('classifyWindowOpen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  it('allows app://force URLs to open as a new Electron window', () => {
    const result = classifyWindowOpen(details('app://force/live/frm?x=1'));
    expect(result.action).toBe('allow');
    expect(shell.openExternal).not.toHaveBeenCalled();
  });

  it('routes an external Directus admin URL to the system browser and denies the Electron window', () => {
    const url = 'https://d1-server.tail54eeb6.ts.net/admin/content/x/1';
    const result = classifyWindowOpen(details(url));
    expect(result.action).toBe('deny');
    expect(shell.openExternal).toHaveBeenCalledWith(url);
  });

  it('denies an unparsable URL without throwing', () => {
    const result = classifyWindowOpen(details('not a url'));
    expect(result.action).toBe('deny');
  });

  it('denies non-http(s) schemes (e.g. file://) without calling shell.openExternal', () => {
    const result = classifyWindowOpen(details('file:///etc/passwd'));
    expect(result.action).toBe('deny');
    expect(shell.openExternal).not.toHaveBeenCalled();
  });
});
