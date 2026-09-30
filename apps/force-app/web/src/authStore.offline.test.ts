import { beforeEach, describe, expect, it, vi } from 'vitest';

const store = new Map<string, string>();
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  },
});

// One fake Directus behind axios.create(): routes by path, with a switch for "unreachable".
const server = vi.hoisted(() => ({
  reachable: true,
  password: 'pw-1',
  refreshStatus: 200 as number | 'network',
  calls: [] as string[],
}));
vi.mock('axios', () => {
  const netErr = () => Object.assign(new Error('Network Error'), { response: undefined });
  const httpErr = (status: number) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
  const client = {
    post: async (path: string, body: any) => {
      server.calls.push(`POST ${path}`);
      if (!server.reachable) throw netErr();
      if (path === '/auth/login') {
        if (body.password !== server.password) throw httpErr(401);
        return { data: { data: { access_token: 'at', refresh_token: 'rt', expires: 900000 } } };
      }
      if (path === '/auth/refresh') {
        if (server.refreshStatus === 'network') throw netErr();
        if (server.refreshStatus !== 200) throw httpErr(server.refreshStatus);
        return { data: { data: { access_token: 'at2', refresh_token: 'rt2', expires: 900000 } } };
      }
      return { data: {} };
    },
    get: async (path: string) => {
      server.calls.push(`GET ${path}`);
      if (!server.reachable) throw netErr();
      if (path === '/users/me') {
        return { data: { data: { id: 'u-1', role: 'r', first_name: 'Ada', last_name: 'L', email: 'ada@lab.org', policies: [] } } };
      }
      if (path === '/items/people') return { data: { data: [{ person_id: 'p-1' }] } };
      return { data: {} };
    },
  };
  return { default: { create: () => client } };
});
vi.mock('./config', () => ({ getConfig: () => ({ directusUrl: 'http://directus' }) }));

import { authStore, OfflineLoginError } from './authStore';

beforeEach(() => {
  authStore.clear();
  store.clear();
  server.reachable = true;
  server.password = 'pw-1';
  server.refreshStatus = 200;
  server.calls = [];
});

describe('login', () => {
  it('online: signs in, captures the person link, and enables offline sign-in', async () => {
    expect(await authStore.login('ada@lab.org', 'pw-1')).toEqual({ offline: false });
    expect(authStore.state.user).toMatchObject({ id: 'u-1', person_id: 'p-1' });
    expect(authStore.state.offline).toBe(false);
    expect(store.get('force-app.auth.vault')).toContain('ada@lab.org');
  });

  it('offline: signs in from the stored verifier with no tokens', async () => {
    await authStore.login('ada@lab.org', 'pw-1');
    await authStore.logout();
    server.reachable = false;

    expect(await authStore.login('ada@lab.org', 'pw-1')).toEqual({ offline: true });
    expect(authStore.state.offline).toBe(true);
    expect(authStore.state.accessToken).toBeNull();
    expect(authStore.state.refreshToken).toBeNull();
    expect(authStore.state.user).toMatchObject({ id: 'u-1', person_id: 'p-1' });
    expect(authStore.isAuthenticated.value).toBe(true);
  });

  it('offline: a wrong password, or an account never seen on this PC, is refused with a reason', async () => {
    await authStore.login('ada@lab.org', 'pw-1');
    await authStore.logout();
    server.reachable = false;

    await expect(authStore.login('ada@lab.org', 'bad')).rejects.toMatchObject({ reason: 'wrong-password' });
    await expect(authStore.login('bob@lab.org', 'pw-1')).rejects.toBeInstanceOf(OfflineLoginError);
    expect(authStore.isAuthenticated.value).toBe(false);
  });

  it('online: a 401 is a wrong password, not "offline" -- the verifier is not consulted', async () => {
    await authStore.login('ada@lab.org', 'pw-1');
    await authStore.logout();
    await expect(authStore.login('ada@lab.org', 'wrong')).rejects.toMatchObject({ response: { status: 401 } });
    expect(authStore.state.offline).toBe(false);
  });

  it('online: a password the server now rejects stops working offline too', async () => {
    await authStore.login('ada@lab.org', 'pw-1');
    await authStore.logout();
    server.password = 'pw-2'; // changed on the server
    await expect(authStore.login('ada@lab.org', 'pw-1')).rejects.toMatchObject({ response: { status: 401 } });

    server.reachable = false;
    await expect(authStore.login('ada@lab.org', 'pw-1')).rejects.toMatchObject({ reason: 'unknown' });
  });
});

describe('offline session -> real session', () => {
  it('reauthenticate() upgrades it with the same user and yields tokens', async () => {
    await authStore.login('ada@lab.org', 'pw-1');
    await authStore.logout();
    server.reachable = false;
    await authStore.login('ada@lab.org', 'pw-1');

    await expect(authStore.reauthenticate('pw-1')).rejects.toThrow(/can't reach/i); // still offline: session kept
    expect(authStore.state.offline).toBe(true);

    server.reachable = true;
    await expect(authStore.reauthenticate('nope')).rejects.toThrow(/incorrect password/i);
    expect(authStore.state.offline).toBe(true);

    await authStore.reauthenticate('pw-1');
    expect(authStore.state.offline).toBe(false);
    expect(authStore.state.accessToken).toBe('at');
    expect(authStore.state.user?.id).toBe('u-1');
  });
});

describe('refresh', () => {
  it('an unreachable server does not end the session', async () => {
    await authStore.login('ada@lab.org', 'pw-1');
    server.refreshStatus = 'network';
    expect(await authStore.refresh()).toBe(false);
    expect(authStore.state.refreshToken).toBe('rt');
    expect(authStore.isAuthenticated.value).toBe(true);
  });

  it('a refusal does end it', async () => {
    await authStore.login('ada@lab.org', 'pw-1');
    server.refreshStatus = 401;
    expect(await authStore.refresh()).toBe(false);
    expect(authStore.state.refreshToken).toBeNull();
  });
});
