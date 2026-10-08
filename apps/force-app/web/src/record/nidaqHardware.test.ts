import { describe, expect, it } from 'vitest';
import { applyNidaqDevices, nidaqHardware, nidaqUnavailableReason, physicalInputs, type NidaqDevicesReply } from './nidaqHardware';

describe('applyNidaqDevices', () => {
	it('updates the shared state, so a reload of the NI-DAQ page re-enables the source', () => {
		applyNidaqDevices({ hardware_present: false, runtime_available: true });
		expect(nidaqHardware.checked).toBe(true);
		expect(nidaqHardware.hardwarePresent).toBe(false);
		applyNidaqDevices({ hardware_present: true, runtime_available: true, nimax_simulated: true });
		expect(nidaqHardware.hardwarePresent).toBe(true);
		expect(nidaqHardware.nimaxSimulated).toBe(true);
	});
	it('ignores an older backend that does not say', () => {
		applyNidaqDevices({ hardware_present: true, runtime_available: true });
		applyNidaqDevices({ simulated: true });
		expect(nidaqHardware.hardwarePresent).toBe(true);
	});
});

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

describe('physical inputs of the connected hardware (#213)', () => {
	const port = (physical: string, kind = 'ai') => ({ id: physical.split('/')[1], kind, physical });
	const tree = {
		hardware_present: true, runtime_available: true, simulated: false,
		chassis: [{ modules: [{ ports: [port('Force1_Mod1/ai0'), port('Force1_Mod1/ai1')] }, { ports: [port('Tacho_Mod3/ai0'), port('Tacho_Mod3/ctr0', 'ci')] }] }],
		standalone: [{ ports: [port('Dev1/ai0')] }],
	} as unknown as NidaqDevicesReply;

	it('are the analog inputs of chassis modules and standalone devices', () => {
		expect(physicalInputs(tree)).toEqual(['Force1_Mod1/ai0', 'Force1_Mod1/ai1', 'Tacho_Mod3/ai0', 'Dev1/ai0']);
		expect(physicalInputs({})).toEqual([]);
	});

	it('are kept for a real device and dropped for the simulated tree or no device', () => {
		applyNidaqDevices(tree);
		expect(nidaqHardware.physicalInputs).toHaveLength(4);
		const same = nidaqHardware.physicalInputs;
		applyNidaqDevices(tree);
		expect(nidaqHardware.physicalInputs).toBe(same); // polled: an unchanged list is not replaced
		applyNidaqDevices({ ...tree, simulated: true });
		expect(nidaqHardware.physicalInputs).toBeNull();
		applyNidaqDevices({ ...tree, hardware_present: false });
		expect(nidaqHardware.physicalInputs).toBeNull();
	});
});
