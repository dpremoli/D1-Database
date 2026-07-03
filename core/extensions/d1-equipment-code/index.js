// Directus hook: d1-equipment-code
//
// Equipment (and misc gear) has no meaningful natural code, so on create we mint
// a short, human-friendly 6-char identifier when none is supplied. The alphabet
// excludes easily-confused characters (0/O/1/I) so codes are safe to read/write
// off a label. Runs as a `filter` so the code is set before the row is inserted.

// Crockford-ish, unambiguous alphabet.
const ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';

function generate(length = 6) {
	let out = '';
	for (let i = 0; i < length; i++) out += ALPHABET[Math.floor(Math.random() * ALPHABET.length)];
	return out;
}

export default ({ filter }, { database }) => {
	filter('items.create', async (payload, meta) => {
		if (meta?.collection !== 'equipment') return payload;
		if (payload && payload.equipment_code) return payload; // respect a supplied code

		// A handful of tries is astronomically safe against the unique index.
		for (let attempt = 0; attempt < 10; attempt++) {
			const code = generate(6);
			const clash = await database('equipment').where('equipment_code', code).first('equipment_id');
			if (!clash) {
				payload.equipment_code = code;
				break;
			}
		}
		return payload;
	});
};
