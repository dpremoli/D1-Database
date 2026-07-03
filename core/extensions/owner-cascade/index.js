// Directus hook: owner-cascade
//
// When a tool_box or cutting_insert is saved with cascade_ownership = true,
// propagates the current owner value to all child records and resets the flag.
// Ownership is a person (owner_person_id → people), not a directus_user.
//
// Cascade path:
//   tool_box.owner_person_id  →  cutting_inserts.owner_person_id  →  insert_edges.owner_person_id
//   cutting_insert.owner_person_id  →  insert_edges.owner_person_id

export default ({ action }) => {
    action('items.update', async ({ payload, keys, collection }, { database }) => {
        if (!payload.cascade_ownership) return;
        if (!['tool_boxes', 'cutting_inserts'].includes(collection)) return;

        if (collection === 'tool_boxes') {
            for (const boxId of keys) {
                // Resolve owner from payload or current DB value
                const ownerPerson = payload.owner_person_id !== undefined
                    ? (payload.owner_person_id ?? null)
                    : ((await database('tool_boxes').where('tool_box_id', boxId).select('owner_person_id').first())?.owner_person_id ?? null);

                await database('cutting_inserts')
                    .where('tool_box_id', boxId)
                    .update({ owner_person_id: ownerPerson });

                const insertIds = await database('cutting_inserts')
                    .where('tool_box_id', boxId)
                    .pluck('insert_id');

                if (insertIds.length > 0) {
                    await database('insert_edges')
                        .whereIn('insert_id', insertIds)
                        .update({ owner_person_id: ownerPerson });
                }

                await database('tool_boxes')
                    .where('tool_box_id', boxId)
                    .update({ cascade_ownership: false });
            }
        }

        if (collection === 'cutting_inserts') {
            for (const insertId of keys) {
                const ownerPerson = payload.owner_person_id !== undefined
                    ? (payload.owner_person_id ?? null)
                    : ((await database('cutting_inserts').where('insert_id', insertId).select('owner_person_id').first())?.owner_person_id ?? null);

                await database('insert_edges')
                    .where('insert_id', insertId)
                    .update({ owner_person_id: ownerPerson });

                await database('cutting_inserts')
                    .where('insert_id', insertId)
                    .update({ cascade_ownership: false });
            }
        }
    });
};
