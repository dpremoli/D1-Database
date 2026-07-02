// Directus hook: d1-default-owner
//
// The researcher `owner` of a manufacturing operation / test session should
// default to whoever creates the record, but stay editable. Directus has no
// native "default to current user but editable" for a normal field (the
// `user-created` special is auto + readonly), so this filter fills `owner` on
// create when the caller didn't supply one.

const OWNED_COLLECTIONS = new Set(['manufacturing_operations', 'test_sessions']);

export default ({ filter }) => {
  filter('items.create', (payload, meta, context) => {
    if (!OWNED_COLLECTIONS.has(meta?.collection)) return payload;
    const user = context?.accountability?.user;
    // Only set when the user left it blank — explicit choices win.
    if (user && payload && (payload.owner === undefined || payload.owner === null)) {
      payload.owner = user;
    }
    return payload;
  });
};
