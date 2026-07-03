// Directus hook: d1-default-owner
//
// The researcher `owner` of a manufacturing operation / test session should
// default to whoever creates the record, but stay editable. Directus has no
// native "default to current user but editable" for a normal field (the
// `user-created` special is auto + readonly), so this filter fills the owner on
// create when the caller didn't supply one.
//
// Ownership now points at `people` (owner_person_id), not directus_users — so we
// resolve the creating user to their person row and default that.

const OWNED_COLLECTIONS = new Set(['manufacturing_operations', 'test_sessions']);

export default ({ filter }) => {
  filter('items.create', async (payload, meta, context) => {
    if (!OWNED_COLLECTIONS.has(meta?.collection)) return payload;
    const user = context?.accountability?.user;
    const db = context?.database;
    // Only set when the user left it blank — explicit choices win.
    if (user && db && payload && (payload.owner_person_id === undefined || payload.owner_person_id === null)) {
      const person = await db('people').where('user_id', user).first('person_id');
      if (person) payload.owner_person_id = person.person_id;
    }
    return payload;
  });
};
