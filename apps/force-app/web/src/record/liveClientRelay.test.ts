import { afterEach, describe, expect, it } from 'vitest';
import { RecordClient } from './liveClient';

const tick = () => new Promise((r) => setTimeout(r, 20));

describe('pop-out relay handshake', () => {
	const open: { close(): void }[] = [];
	afterEach(() => { for (const c of open.splice(0)) c.close(); });

	it('a pop-out asks for a sync again when the source window connects after it (#108)', async () => {
		const requests: unknown[] = [];
		const source = new BroadcastChannel('force-app-live');   // stands in for the main window
		open.push(source);
		source.onmessage = (ev) => { if (ev.data?.type === 'sync-request') requests.push(ev.data); };

		const popout = new RecordClient();
		open.push({ close: () => popout.disconnect() });
		popout.connectViaRelay();
		await tick();
		expect(requests).toHaveLength(1);   // its first request on opening

		source.postMessage({ type: 'source-ready' });   // what connect() announces
		await tick();
		expect(requests).toHaveLength(2);
	});
});
