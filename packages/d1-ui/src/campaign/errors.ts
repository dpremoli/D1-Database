// Classifying failures of the Directus API for the campaign pickers (moved from overview.js).

const errCode = (e: any) => e?.response?.data?.errors?.[0]?.extensions?.code;

// An Axios/Directus failure that means "your role may not read this" (as opposed to a network or
// server error): HTTP 403 or the FORBIDDEN error code.
export function isForbidden(e: any): boolean {
	return e?.response?.status === 403 || errCode(e) === 'FORBIDDEN';
}

// An Axios/Directus failure for a unique-constraint violation (the row already exists).
export function isDuplicate(e: any): boolean {
	return errCode(e) === 'RECORD_NOT_UNIQUE';
}
