// Directus hook: owner-cascade
//
// When a tool_box or cutting_insert is saved with cascade_ownership = true,
// propagates the current owner value to all child records and resets the flag.
//
// Cascade path:
//   tool_box.owner  →  cutting_inserts.owner  →  insert_edges.owner
//   cutting_insert.owner  →  insert_edges.owner

export default ({ action }) => {
    action('items.update', async ({ payload, keys, collection }, { database }) => {
        if (!payload.cascade_ownership) return;
        if (!['tool_boxes', 'cutting_inserts'].includes(collection)) return;

        if (collection === 'tool_boxes') {
            for (const boxId of keys) {
                // Resolve owner from payload or current DB value
                const owner = payload.owner !== undefined
                    ? (payload.owner ?? null)
                    : ((await database('tool_boxes').where('tool_box_id', boxId).select('owner').first())?.owner ?? null);

                await database('cutting_inserts')
                    .where('tool_box_id', boxId)
                    .update({ owner });

                const insertIds = await database('cutting_inserts')
                    .where('tool_box_id', boxId)
                    .pluck('insert_id');

                if (insertIds.length > 0) {
                    await database('insert_edges')
                        .whereIn('insert_id', insertIds)
                        .update({ owner });
                }

                await database('tool_boxes')
                    .where('tool_box_id', boxId)
                    .update({ cascade_ownership: false });
            }
        }

        if (collection === 'cutting_inserts') {
            for (const insertId of keys) {
                const owner = payload.owner !== undefined
                    ? (payload.owner ?? null)
                    : ((await database('cutting_inserts').where('insert_id', insertId).select('owner').first())?.owner ?? null);

                await database('insert_edges')
                    .where('insert_id', insertId)
                    .update({ owner });

                await database('cutting_inserts')
                    .where('insert_id', insertId)
                    .update({ cascade_ownership: false });
            }
        }
    });
};
