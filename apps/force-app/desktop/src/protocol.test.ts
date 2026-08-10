import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { resolveRequestPath } from './protocol';

describe('resolveRequestPath', () => {
  let webDistDir: string;
  let configFilePath: string;

  beforeEach(() => {
    webDistDir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-app-web-'));
    fs.writeFileSync(path.join(webDistDir, 'index.html'), '<html>spa</html>');
    fs.mkdirSync(path.join(webDistDir, 'assets'));
    fs.writeFileSync(path.join(webDistDir, 'assets', 'app.js'), 'console.log(1)');
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-app-userdata-'));
    configFilePath = path.join(userDataDir, 'config.json');
    fs.writeFileSync(configFilePath, '{"directusUrl":"https://example"}');
  });

  afterEach(() => {
    fs.rmSync(webDistDir, { recursive: true, force: true });
    fs.rmSync(path.dirname(configFilePath), { recursive: true, force: true });
  });

  it('serves index.html for the root path', () => {
    const { filePath, is404 } = resolveRequestPath('app://force/', webDistDir, configFilePath);
    expect(is404).toBe(false);
    expect(filePath).toBe(path.join(webDistDir, 'index.html'));
  });

  it('serves a hashed asset by exact path', () => {
    const { filePath, is404 } = resolveRequestPath('app://force/assets/app.js', webDistDir, configFilePath);
    expect(is404).toBe(false);
    expect(filePath).toBe(path.join(webDistDir, 'assets', 'app.js'));
  });

  it('serves config.json from userData rather than the bundled dist', () => {
    const { filePath, is404 } = resolveRequestPath('app://force/config.json', webDistDir, configFilePath);
    expect(is404).toBe(false);
    expect(filePath).toBe(configFilePath);
  });

  it('falls back to index.html for an unknown SPA route (history mode)', () => {
    const { filePath, is404 } = resolveRequestPath('app://force/settings', webDistDir, configFilePath);
    expect(is404).toBe(false);
    expect(filePath).toBe(path.join(webDistDir, 'index.html'));
  });

  it('rejects a request whose host is not "force"', () => {
    const { is404 } = resolveRequestPath('app://other/index.html', webDistDir, configFilePath);
    expect(is404).toBe(true);
  });

  it('blocks path traversal outside webDistDir', () => {
    const { is404 } = resolveRequestPath('app://force/..%2f..%2fsecrets.txt', webDistDir, configFilePath);
    expect(is404).toBe(true);
  });
});
