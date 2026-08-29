import { beforeEach, describe, expect, it } from 'vitest';
import { AlarmController } from './alarms';

function makeController(): AlarmController {
	const a = new AlarmController();
	a.config.audioEnabled = false; // no AudioContext in the test environment
	return a;
}

describe('AlarmController.evaluateTacho', () => {
	let a: AlarmController;
	beforeEach(() => {
		a = makeController();
	});

	it('raises a latched alarm when the tacho reports no signal', () => {
		a.evaluateTacho(false);
		expect(a.active.map((x) => x.kind)).toContain('tacho');
		expect(a.tripped).toBe(true);
	});

	it('stays quiet while the tacho is reading, or before the first reading', () => {
		a.evaluateTacho(true);
		a.evaluateTacho(null); // null = no chunk processed yet, not a fault
		expect(a.active).toHaveLength(0);
	});

	it('does not raise twice for one continuous outage', () => {
		a.evaluateTacho(false);
		a.evaluateTacho(false);
		a.evaluateTacho(false);
		expect(a.active.filter((x) => x.kind === 'tacho')).toHaveLength(1);
	});

	it('is gated on the high-RPM alarm being enabled', () => {
		// The tacho check exists to protect the RPM alarm's integrity, so it follows that alarm's
		// switch rather than being a fourth thing to turn off.
		a.config.rpmEnabled = false;
		a.evaluateTacho(false);
		expect(a.active).toHaveLength(0);
	});
});

describe('AlarmController.acknowledge', () => {
	it('acknowledging specific keys leaves a different active key tripped', () => {
		// Regression: acknowledge() used to be a single global boolean, so silencing the alarm(s)
		// shown in a confirmation dialog would ALSO silence any alarm that fired while that (now
		// async, non-blocking) dialog was still open and never actually shown to the operator.
		const a = makeController();
		a.evaluate({ Fx: 500, Fy: 0, Fz: 0 }, 0, 1200); // force:Fx trips (threshold 400)
		a.evaluateTacho(false); // fires while the "confirm" dialog for the force alarm is still open
		expect(a.active).toHaveLength(2);

		a.acknowledge(['force:Fx']); // only what the dialog actually showed
		expect(a.tripped).toBe(true); // tacho was never shown or consented to — still alerting
		expect(a.active.map((x) => x.kind)).toContain('tacho');
	});

	it('acknowledging every currently-active key clears tripped', () => {
		const a = makeController();
		a.evaluateTacho(false);
		a.acknowledge(['tacho']);
		expect(a.tripped).toBe(false);
	});

	it('defaults to acknowledging everything currently active when no keys are given', () => {
		const a = makeController();
		a.evaluate({ Fx: 500, Fy: 0, Fz: 0 }, 0, 1200);
		a.evaluateTacho(false);
		a.acknowledge();
		expect(a.tripped).toBe(false);
	});

	it('reset clears prior acknowledgment so a new instance of the same key trips again', () => {
		const a = makeController();
		a.evaluateTacho(false);
		a.acknowledge(['tacho']);
		a.reset();
		a.evaluateTacho(false);
		expect(a.tripped).toBe(true);
	});
});

describe('AlarmController.evaluate', () => {
	it('trips the RPM alarm off a genuinely measured overspeed', () => {
		const a = makeController();
		a.evaluate({ Fx: 0, Fy: 0, Fz: 0 }, 1300, 1200); // limit = 1200 * 1.02 = 1224
		expect(a.active.map((x) => x.kind)).toContain('rpm');
	});

	it('cannot trip on a fabricated reading equal to the configured speed', () => {
		// Regression guard for the backend fault this pairs with: RPM used to be reported as
		// exactly cfg.rpm whenever the tacho produced no pulses. That value is always below the
		// 1.02x limit, so the alarm could never fire no matter how the spindle actually behaved —
		// evaluateTacho is what surfaces that case now.
		const a = makeController();
		a.evaluate({ Fx: 0, Fy: 0, Fz: 0 }, 1200, 1200);
		expect(a.active).toHaveLength(0);
		a.evaluateTacho(false);
		expect(a.active.map((x) => x.kind)).toContain('tacho');
	});
});
