// Directus hook: actor-identity
//
// The Postgres audit trigger (db/migrations/...0009_audit.sql) records who made
// each change by reading current_setting('d1.actor_identity', TRUE). Nothing set
// that GUC for writes made through the Directus API, so API-originated changes
// were attributed to NULL.
//
// This filter hook fires inside the SAME database transaction as every item
// create / update / delete (Directus passes that transaction as
// context.database). It sets d1.actor_identity to the authenticated identity
// using set_config(..., true) — transaction-local — so the AFTER trigger reads
// it back within the same transaction.
//
// We use the authenticated Directus user id (machine tokens each have their own
// user, e.g. the Rig_1 sampling node) rather than a client-supplied header: it
// cannot be spoofed by the caller and is always present for authenticated writes.

export default ({ filter }) => {
  const setActor = async (payload, _meta, context) => {
    // accountability is null for unauthenticated/public requests.
    const actor = context?.accountability?.user || "public";
    if (context?.database) {
      await context.database.raw(
        "SELECT set_config('d1.actor_identity', ?, true)",
        [String(actor)],
      );
    }
    // Filter hooks MUST return the (first) payload argument unchanged.
    return payload;
  };

  filter("items.create", setActor);
  filter("items.update", setActor);
  filter("items.delete", setActor);
};
