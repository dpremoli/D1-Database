import { describe, expect, it } from 'vitest';
import { RelayPeers } from './relayPeers';

describe('RelayPeers (#107)', () => {
	it('has no peer until one speaks', () => {
		const p = new RelayPeers(1000);
		expect(p.alive(0)).toBe(false);
		p.seen('a', 0);
		expect(p.alive(10)).toBe(true);
	});

	it('forgets a peer that said bye', () => {
		const p = new RelayPeers(1000);
		p.seen('a', 0);
		p.bye('a');
		expect(p.alive(1)).toBe(false);
	});

	it('expires a peer that stopped sending heartbeats', () => {
		// The bug: one sync-request latched "a pop-out exists" for the rest of the session.
		const p = new RelayPeers(1000);
		p.seen('a', 0);
		expect(p.alive(900)).toBe(true);
		expect(p.alive(1100)).toBe(false);
	});

	it('a heartbeat keeps a peer alive', () => {
		const p = new RelayPeers(1000);
		p.seen('a', 0);
		p.seen('a', 800);
		expect(p.alive(1500)).toBe(true);
	});

	it('reports the largest history any live peer wants', () => {
		const p = new RelayPeers(1000);
		expect(p.maxRetainSec(0)).toBeNull();
		p.seen('a', 0, 60);
		p.seen('b', 500, 120);
		expect(p.maxRetainSec(600)).toBe(120);
		p.bye('b');
		expect(p.maxRetainSec(700)).toBe(60);
		expect(p.maxRetainSec(2000)).toBeNull();
	});
});
