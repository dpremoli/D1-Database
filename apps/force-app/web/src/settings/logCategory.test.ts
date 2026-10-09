import { describe, expect, it } from 'vitest';
import { logCategory } from './logCategory';

const rec = (level: string, logger: string, message: string) => ({ level, logger, message });

describe('logCategory', () => {
	it('classifies backend HTTP client lines as network', () => {
		expect(logCategory(rec('INFO', 'httpx', 'HTTP Request: POST http://127.0.0.1:1/api/$/operationMode/get "HTTP/1.1 200 OK"'))).toBe('network');
		expect(logCategory(rec('DEBUG', 'urllib3.connectionpool', 'Starting new HTTP connection (1): localhost:8055'))).toBe('network');
		expect(logCategory(rec('INFO', 'force_app.labamp', 'HTTP Request: GET /x'))).toBe('network');
	});

	it('classifies web-UI forwarded lines as ui', () => {
		expect(logCategory(rec('INFO', 'force_app.client', '[vue @ /record] mounted'))).toBe('ui');
	});

	it('classifies session and finalize lines as recording', () => {
		expect(logCategory(rec('INFO', 'force_app.session', 'session._finalize_async: finished'))).toBe('recording');
		expect(logCategory(rec('INFO', 'force_app.main', 'finalize took 1.2s'))).toBe('recording');
	});

	it('lets error and warning win over the type', () => {
		expect(logCategory(rec('ERROR', 'force_app.client', '[vue @ /record] ReferenceError: x is not defined'))).toBe('error');
		expect(logCategory(rec('ERROR', 'httpx', 'HTTP Request: POST http://x "HTTP/1.1 500"'))).toBe('error');
		expect(logCategory(rec('CRITICAL', 'force_app.session', 'boom'))).toBe('error');
		expect(logCategory(rec('WARNING', 'force_app.session', 'finalize slow'))).toBe('warning');
	});

	it('falls back to other', () => {
		expect(logCategory(rec('INFO', 'force_app.main', 'backend ready'))).toBe('other');
		expect(logCategory(rec('INFO', '', ''))).toBe('other');
	});
});
