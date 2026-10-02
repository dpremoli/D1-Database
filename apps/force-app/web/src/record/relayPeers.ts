// Which pop-out windows are listening on the 'force-app-live' BroadcastChannel right now (#107).
//
// The opener used to latch "a pop-out exists" the first time one sent a sync-request and never
// clear it short of a disconnect, so after closing the only pop-out every replay frame still paid
// for a full snapshot (every FRM point, trace bin and spectrum, structured-cloned 5x a second) that
// nothing received — which is what made the colour-scale editor sluggish during replay. Pop-outs
// now send a heartbeat and a 'bye' on close; a peer that goes quiet (crashed, or closed too fast
// to say bye) expires after ttlMs.
export const RELAY_HEARTBEAT_MS = 1000;
export const RELAY_PEER_TTL_MS = 3500;

export class RelayPeers {
	private peers = new Map<string, { seen: number; retainSec: number }>();
	constructor(private ttlMs = RELAY_PEER_TTL_MS) {}

	/** A peer spoke (sync-request or heartbeat). retainSec: how much trace history it wants. */
	seen(id: string, now: number, retainSec = 0) {
		this.peers.set(id, { seen: now, retainSec: Number.isFinite(retainSec) ? retainSec : 0 });
	}
	bye(id: string) { this.peers.delete(id); }
	clear() { this.peers.clear(); }

	private prune(now: number) {
		for (const [id, p] of this.peers) if (now - p.seen > this.ttlMs) this.peers.delete(id);
	}
	/** Whether anyone is still listening. */
	alive(now: number): boolean {
		this.prune(now);
		return this.peers.size > 0;
	}
	/** The most trace history any live peer wants, or null with none. */
	maxRetainSec(now: number): number | null {
		this.prune(now);
		let m: number | null = null;
		for (const p of this.peers.values()) if (m === null || p.retainSec > m) m = p.retainSec;
		return m;
	}
}
