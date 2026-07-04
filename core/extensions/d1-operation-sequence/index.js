// Directus hook: d1-operation-sequence
//
// Every operation should carry a unique identifier in its code. For machining that
// is the facing/roughing pass number the user enters; for other methods (FAST, heat
// treatment, …) there was none. On create, if operation_sequence is blank and the
// op references a sample, fill it with the next number for that sample — so codes
// like MF1, MF2 stay unique. Never clobbers a value the user supplied (e.g. a
// machining pass number).

export default ({ filter }) => {
	filter('items.create', async (payload, meta, context) => {
		if (meta?.collection !== 'manufacturing_operations') return payload;
		const db = context?.database;
		if (!db || !payload) return payload;
		const sampleId = payload.sample_id;
		const blank = payload.operation_sequence === undefined
			|| payload.operation_sequence === null
			|| payload.operation_sequence === '';
		if (sampleId && blank) {
			const row = await db('manufacturing_operations')
				.where('sample_id', sampleId)
				.max({ m: 'operation_sequence' })
				.first();
			payload.operation_sequence = Number(row?.m ?? 0) + 1;
		}
		return payload;
	});
};
