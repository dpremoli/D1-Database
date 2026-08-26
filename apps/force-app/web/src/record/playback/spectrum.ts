// Playback FFT transport. Spectra are computed by the recorder sidecar's /dsp/spectrum, which
// runs the SAME scipy welch_spectra() the live recording path uses — so a replayed cut's FFT is
// bit-identical to a live one's rather than a second implementation that could drift.
//
// Two behaviours make a few-per-second call affordable while scrubbing:
//   throttle  — at most one call per minIntervalMs (300 by default, matching the backend's own
//               live-FFT throttle in session._update_fft)
//   coalesce  — while a call is in flight only the NEWEST pending request survives, so dragging
//               the scrub bar can never build a queue of stale windows to work through.

export interface SpectrumReply { fs: number; f: number[]; spectra: Record<string, number[]> }
export interface SpectrumRequest {
	fs: number;
	names: string[];
	samples: Float32Array;   // channel-major, names.length * n
	nperseg?: number;
	force?: boolean;         // bypass the throttle (scrub release)
}
export interface SpectrumClient {
	request(req: SpectrumRequest): void;
	onReply: (r: SpectrumReply) => void;
	onError: (e: Error) => void;
	flush(): Promise<void>;  // settle all in-flight + pending work (tests, and dispose)
	dispose(): void;
}

export function createSpectrumClient(baseUrl: string, opts: { minIntervalMs?: number } = {}): SpectrumClient {
	const minInterval = opts.minIntervalMs ?? 300;
	let pending: SpectrumRequest | null = null;
	let inFlight: Promise<void> | null = null;
	let lastSent = -Infinity;
	let disposed = false;

	const c: SpectrumClient = {
		onReply: () => {},
		onError: () => {},
		request(req) {
			if (disposed) return;
			if (!req.force && !inFlight && performance.now() - lastSent < minInterval) return;
			pending = req;                       // newest wins; an older pending one is discarded
			if (!inFlight) inFlight = pump();
		},
		async flush() {
			while (inFlight) await inFlight;
		},
		dispose() { disposed = true; pending = null; },
	};

	async function pump(): Promise<void> {
		while (pending && !disposed) {
			const req = pending;
			pending = null;
			lastSent = performance.now();
			try {
				const q = new URLSearchParams({ fs: String(req.fs), names: req.names.join(',') });
				if (req.nperseg) q.set('nperseg', String(req.nperseg));
				const res = await fetch(`${baseUrl}/dsp/spectrum?${q}`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/octet-stream' },
					// Send the exact bytes: a subarray view would post the whole backing buffer.
					body: req.samples.slice().buffer,
				});
				if (!res.ok) throw new Error(`spectrum: ${res.status} ${(await res.text()).slice(0, 200)}`);
				if (!disposed) c.onReply(await res.json());
			} catch (e: any) {
				if (!disposed) c.onError(e instanceof Error ? e : new Error(String(e)));
			}
		}
		inFlight = null;
	}

	return c;
}
