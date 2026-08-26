import fs from 'node:fs';
import path from 'node:path';

export interface WindowBounds {
  x?: number;
  y?: number;
  width: number;
  height: number;
  maximized?: boolean;
}

/** Reads/writes `<userData>/window-state.json` — last-used size/position for the main window and
 * each pop-out kind (keyed by URL pathname, e.g. "/live/force", "/live/frm", "/record"), so
 * reopening a window lands where the operator last put it instead of always resetting to a fixed
 * default. `<userData>` is already per-Windows-user (%LOCALAPPDATA%), so this is per-user for free. */
export class WindowStateStore {
  private readonly filePath: string;

  constructor(userDataDir: string) {
    this.filePath = path.join(userDataDir, 'window-state.json');
  }

  private readAll(): Record<string, WindowBounds> {
    try {
      return JSON.parse(fs.readFileSync(this.filePath, 'utf-8'));
    } catch {
      return {};
    }
  }

  get(key: string): WindowBounds | undefined {
    return this.readAll()[key];
  }

  save(key: string, bounds: WindowBounds): void {
    const all = this.readAll();
    all[key] = bounds;
    try {
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
      fs.writeFileSync(this.filePath, JSON.stringify(all, null, 2));
    } catch {
      // Best effort — losing remembered window placement is not worth failing over.
    }
  }
}
