import { describe, it, expect } from 'vitest';
import { vi } from 'vitest';

const sent: Array<[string, string]> = [];
const fakeWin = { webContents: { send: (channel: string, arg: string) => sent.push([channel, arg]) } };

vi.mock('electron', () => ({
  Menu: { buildFromTemplate: (template: unknown[]) => ({ template }) },
}));

import { buildMenu } from './menu';

describe('buildMenu', () => {
  it('the Connectivity Doctor item sends a navigate IPC message to the current window', () => {
    const menu = buildMenu(() => fakeWin as unknown as Electron.BrowserWindow) as unknown as {
      template: Array<{ label: string; submenu: Array<{ label: string; click: () => void }> }>;
    };
    const help = menu.template.find((m) => m.label === 'Help')!;
    const doctor = help.submenu.find((m) => m.label === 'Connectivity Doctor')!;
    doctor.click();
    expect(sent).toEqual([['navigate', '/settings?tab=connectivity']]);
  });

  it('does nothing when there is no current window', () => {
    const menu = buildMenu(() => null) as unknown as {
      template: Array<{ label: string; submenu: Array<{ label: string; click: () => void }> }>;
    };
    const help = menu.template.find((m) => m.label === 'Help')!;
    const doctor = help.submenu.find((m) => m.label === 'Connectivity Doctor')!;
    expect(() => doctor.click()).not.toThrow();
  });
});
