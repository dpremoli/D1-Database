// Directus hook: d1-default-owner
//
// The owner of a sample, manufacturing operation, test session or campaign should default to
// whoever creates the record, but stay editable. Directus has no native "default to current user
// but editable" for a normal field (the `user-created` special is auto + readonly), so this filter
// fills the owner on create when the caller didn't supply one.
//
// Ownership points at `people` (owner_person_id), not directus_users, so we resolve the creating
// user to their person row and default that.
//
// Since ADR-0011 the owner is also what lets the creator see and edit the record they just made:
// the Lab Member permission filters match `owner_person_id.user_id` to the signed-in user, so a
// record created with no owner would be invisible to its creator. A user with no `people` row (or a
// machine user) gets no default, as before.

const OWNED_COLLECTIONS = new Set([
  'physical_samples',
  'manufacturing_operations',
  'test_sessions',
  'campaigns',
]);

const isBlank = (value) => value === undefined || value === null;

export default ({ filter }) => {
  filter('items.create', async (payload, meta, context) => {
    if (!OWNED_COLLECTIONS.has(meta?.collection)) return payload;
    const user = context?.accountability?.user;
    const db = context?.database;
    if (!user || !db || !payload) return payload;

    // Only set when the user left it blank — explicit choices win. Resolve the person once.
    const items = Array.isArray(payload) ? payload : [payload];
    const blank = items.filter((item) => item && typeof item === 'object' && isBlank(item.owner_person_id));
    if (blank.length === 0) return payload;
    const person = await db('people').where('user_id', user).first('person_id');
    if (person) for (const item of blank) item.owner_person_id = person.person_id;
    return payload;
  });
};
