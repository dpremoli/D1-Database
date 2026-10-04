// Latest-request-wins guard for async loads that are triggered by clicks or typing.
//
//   const gate = useRequestGate();
//   async function load() {
//     const token = gate.begin();
//     const data = await fetch...;
//     if (!gate.isCurrent(token)) return;   // a newer load (or unmount) replaced this one
//     rows.value = data;
//   }
//   onBeforeUnmount(() => gate.cancel());   // late responses after unmount are dropped
export function useRequestGate() {
	let current = 0;
	return {
		begin(): number {
			return ++current;
		},
		isCurrent(token: number): boolean {
			return token === current;
		},
		cancel(): void {
			current++;
		},
	};
}

// Text for a visible error from an Axios/Directus failure.
export function errorText(e: any, fallback = 'Request failed'): string {
	return e?.response?.data?.errors?.[0]?.message || e?.message || fallback;
}
