// Directus hook: box-intake
//
// Fires after a tool_box record is created. If the record has package_quantity >= 1,
// delegates all expansion logic to the Postgres function expand_tool_box_intake().
//
// That function:
//   - Generates box/insert/edge codes in the pattern {short_code}-{box_seq}-{insert_pos}{edge_letter}
//   - Creates package_quantity tool_box records (updating the first, inserting the rest)
//   - Creates insert_types.inserts_per_box cutting_insert records per box
//   - Creates insert_types.edge_count insert_edge records per insert (A, B, C …)
//
// Clone boxes are created with package_quantity = 0 so this hook does not
// recurse into them.

export default ({ action }) => {
    action('items.create', async ({ payload, key, collection }, { database }) => {
        if (collection !== 'tool_boxes') return;

        // package_quantity = 0 is the clone sentinel — do not expand.
        // package_quantity = null means manual entry — do not expand.
        const qty = payload?.package_quantity;
        if (!qty || qty < 1) return;

        await database.raw('SELECT expand_tool_box_intake(?)', [key]);
    });
};
