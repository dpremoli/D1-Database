import { describe, expect, it } from 'vitest';
import { nidaqUnavailableReason } from './nidaqHardware';

describe('nidaqUnavailableReason', () => {
	it('allows NI-DAQ when hardware is present (real or NI MAX simulated)', () => {
		expect(nidaqUnavailableReason({ hardware_present: true, runtime_available: true })).toBeNull();
		expect(nidaqUnavailableReason({ hardware_present: true, runtime_available: true, nimax_simulated: true })).toBeNull();
	});

	it('explains a missing device vs a missing driver', () => {
		expect(nidaqUnavailableReason({ hardware_present: false, runtime_available: true })).toMatch(/No NI-DAQ device found/);
		expect(nidaqUnavailableReason({ hardware_present: false, runtime_available: false })).toMatch(/driver isn't installed/);
	});

	it('does not disable on an unknown answer', () => {
		expect(nidaqUnavailableReason(null)).toBeNull();
		expect(nidaqUnavailableReason({ simulated: true })).toBeNull(); // older backend
	});
});
