import fs from 'node:fs';
import path from 'node:path';

export type RevealCheck = { ok: true; path: string; isDir: boolean } | { ok: false; reason: string };

/** May the renderer open this path in the file browser? (#96)
 *
 * The request comes from page code, so it is held to what the feature needs: an absolute path
 * that exists and lies inside the backend's current captures folder (the folder itself counts).
 * Symlinks and junctions are resolved on both sides before comparing, so a link inside the folder
 * cannot point the file browser somewhere else. `path.relative` already compares
 * case-insensitively on Windows. */
export function checkRevealTarget(requested: unknown, capturesRoot: string): RevealCheck {
  if (typeof requested !== 'string' || !requested) return { ok: false, reason: 'no path given' };
  if (!path.isAbsolute(requested)) return { ok: false, reason: 'not an absolute path' };
  let target: string;
  let root: string;
  try {
    target = fs.realpathSync(requested);
  } catch {
    return { ok: false, reason: 'that folder no longer exists' };
  }
  try {
    root = fs.realpathSync(capturesRoot);
  } catch {
    return { ok: false, reason: 'the recording folder is not available' };
  }
  const rel = path.relative(root, target);
  if (rel === '..' || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
    return { ok: false, reason: 'only folders inside the recording folder can be opened' };
  }
  let isDir: boolean;
  try {
    isDir = fs.statSync(target).isDirectory();
  } catch {
    return { ok: false, reason: 'that folder no longer exists' };
  }
  return { ok: true, path: target, isDir };
}
