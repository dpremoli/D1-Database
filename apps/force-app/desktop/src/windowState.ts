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

export interface DisplayArea { x: number; y: number; width: number; height: number }

/** Would a window at these bounds land on a screen the machine currently has?
 *
 * Guards two ways a saved position goes stale: a monitor that has since been undocked (the saved
 * rect sits in coordinates no display covers any more), and the ≈ -32000 origin Windows reports
 * for a minimized window. Either one would otherwise reopen the app somewhere the operator cannot
 * see or reach it. Bounds with no saved x/y are fine — Electron places those itself. An empty
 * display list means we could not enumerate screens, in which case honouring the saved placement
 * beats discarding it. Overlap only needs to be partial: straddling two monitors is legitimate. */
export function isOnSomeDisplay(bounds: WindowBounds, displays: DisplayArea[]): boolean {
  if (bounds.x === undefined || bounds.y === undefined) return true;
  if (displays.length === 0) return true;
  return displays.some((d) =>
    bounds.x! < d.x + d.width &&
    bounds.x! + bounds.width > d.x &&
    bounds.y! < d.y + d.height &&
    bounds.y! + bounds.height > d.y);
}
