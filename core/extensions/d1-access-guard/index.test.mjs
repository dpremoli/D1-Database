// Run with: node --test core/extensions/d1-access-guard/index.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import hook from './index.js';

const RULES = JSON.parse(readFileSync(new URL('./rules.json', import.meta.url), 'utf8')).guards;

// An ItemsService stand-in. `canUpdate(collection, id)` decides whether the parent row comes back;
// every construction and read is recorded.
function mount({ canUpdate = () => true, readError = null } = {}) {
  const filters = {};
  const log = { built: [], reads: [] };
  class ItemsService {
    constructor(collection, options) {
      this.collection = collection;
      log.built.push({ collection, options });
    }
    async readByQuery(query) {
      log.reads.push({ collection: this.collection, query });
      if (readError) throw readError;
      const id = query.filter._and[0][query.fields[0]]._eq;
      return canUpdate(this.collection, id) ? [{ [query.fields[0]]: id }] : [];
    }
  }
  hook({ filter: (name, fn) => (filters[name] = fn) }, { services: { ItemsService } });
  return { filters, log };
}

// db(table).whereIn(pk, keys).select(...) -> the rows of `existing`.
function fakeDb(existing = []) {
  const calls = [];
  const db = (table) => ({
    whereIn: (column, keys) => ({
      select: async (...columns) => {
        calls.push({ table, column, keys, columns });
        return existing;
      },
    }),
  });
  db.calls = calls;
  return db;
}

const member = { user: 'user-1', admin: false };
const ctx = (overrides = {}) => ({
  database: fakeDb(),
  schema: { collections: { campaign_samples: { primary: 'id' } } },
  accountability: member,
  ...overrides,
});
const denied = (re) => (err) => {
  assert.equal(err.status, 403);
  assert.equal(err.code, 'FORBIDDEN');
  assert.equal(err.extensions.code, 'FORBIDDEN');
  assert.match(err.message, re);
  return true;
};

test('registers an items.create and an items.update filter', () => {
  assert.deepEqual(Object.keys(mount().filters).sort(), ['items.create', 'items.update']);
});

test('the shipped rules guard exactly the three visibility junctions', () => {
  assert.deepEqual(Object.keys(RULES).sort(), ['campaign_samples', 'project_investigators', 'sample_co_owners']);
  assert.deepEqual(RULES.campaign_samples.map((c) => c.parent), ['campaigns', 'physical_samples']);
  for (const checks of Object.values(RULES)) {
    for (const c of checks) assert.ok(JSON.stringify(c.filter).includes('$CURRENT_USER'), c.parent);
  }
});

test('sample_co_owners create: allowed when the caller may update the sample', async () => {
  const { filters, log } = mount();
  const payload = { sample_id: 's1', user_id: 'u9' };
  assert.equal(await filters['items.create'](payload, { collection: 'sample_co_owners' }, ctx()), payload);
  assert.equal(log.reads.length, 1);
  const [{ collection, query }] = log.reads;
  assert.equal(collection, 'physical_samples');
  assert.deepEqual(query.fields, ['sample_id']);
  assert.equal(query.limit, 1);
  assert.deepEqual(query.filter._and[0], { sample_id: { _eq: 's1' } });
  const sent = JSON.stringify(query.filter._and[1]);
  assert.ok(sent.includes('user-1'), 'the caller replaces $CURRENT_USER');
  assert.ok(!sent.includes('$CURRENT_USER'));
  assert.ok(sent.includes('co_owners'), "it is the sample's update rule: owner or co-owner");
});

test('the read runs as the caller, inside the request transaction', async () => {
  const { filters, log } = mount();
  const c = ctx();
  await filters['items.create']({ sample_id: 's1' }, { collection: 'sample_co_owners' }, c);
  assert.equal(log.built[0].options.knex, c.database);
  assert.equal(log.built[0].options.schema, c.schema);
  assert.equal(log.built[0].options.accountability, member);
});

test('sample_co_owners create: refused when the caller cannot update the sample (self-grant)', async () => {
  const { filters } = mount({ canUpdate: () => false });
  await assert.rejects(
    filters['items.create']({ sample_id: 's1', user_id: 'user-1' }, { collection: 'sample_co_owners' }, ctx()),
    denied(/physical_samples s1/),
  );
});

test('project_investigators create is checked against the project', async () => {
  const { filters, log } = mount({ canUpdate: (c) => c !== 'projects' });
  await assert.rejects(
    filters['items.create']({ project_id: 'p1', user_id: 'user-1' }, { collection: 'project_investigators' }, ctx()),
    denied(/projects p1/),
  );
  assert.equal(log.reads[0].collection, 'projects');
  assert.ok(JSON.stringify(log.reads[0].query.filter).includes('principal_investigator_person'));
});

test('campaign_samples create needs the campaign AND the sample', async () => {
  const both = mount();
  await both.filters['items.create']({ campaign_id: 'c1', sample_id: 's1' }, { collection: 'campaign_samples' }, ctx());
  assert.deepEqual(both.log.reads.map((r) => r.collection), ['campaigns', 'physical_samples']);

  const noSample = mount({ canUpdate: (c) => c === 'campaigns' });
  await assert.rejects(
    noSample.filters['items.create']({ campaign_id: 'c1', sample_id: 's1' }, { collection: 'campaign_samples' }, ctx()),
    denied(/physical_samples s1/),
  );

  const noCampaign = mount({ canUpdate: (c) => c === 'physical_samples' });
  await assert.rejects(
    noCampaign.filters['items.create']({ campaign_id: 'c1', sample_id: 's1' }, { collection: 'campaign_samples' }, ctx()),
    denied(/campaigns c1/),
  );
});

test('an array payload checks every item', async () => {
  const { filters } = mount({ canUpdate: (_c, id) => id !== 's2' });
  await assert.rejects(
    filters['items.create'](
      [{ sample_id: 's1' }, { sample_id: 's2' }],
      { collection: 'sample_co_owners' },
      ctx(),
    ),
    denied(/s2/),
  );
});

test('admins and internal calls are not checked', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const payload = { sample_id: 's1' };
  const meta = { collection: 'sample_co_owners' };
  await filters['items.create'](payload, meta, ctx({ accountability: { user: 'a', admin: true } }));
  await filters['items.create'](payload, meta, ctx({ accountability: null }));
  await filters['items.create'](payload, meta, ctx({ accountability: { user: null, admin: false } }));
  await filters['items.update']({ sample_id: 's2' }, { ...meta, keys: [1] }, ctx({ accountability: { user: 'a', admin: true } }));
  assert.equal(log.reads.length, 0);
});

test('other collections are left alone', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  for (const collection of ['physical_samples', 'campaigns', 'sample_genealogy', 'test_sessions_subject', undefined]) {
    await filters['items.create']({ sample_id: 's1' }, { collection }, ctx());
    await filters['items.update']({ sample_id: 's1' }, { collection, keys: [1] }, ctx());
  }
  assert.equal(log.reads.length, 0);
});

test('no parent key, or a brand-new nested parent, passes (the database or the creator decides)', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  await filters['items.create']({ user_id: 'u9' }, { collection: 'sample_co_owners' }, ctx());
  await filters['items.create']({ sample_id: null, user_id: 'u9' }, { collection: 'sample_co_owners' }, ctx());
  await filters['items.create']({ sample_id: { sample_code: 'NEW-1' } }, { collection: 'sample_co_owners' }, ctx());
  assert.equal(log.reads.length, 0);
});

test('a nested parent object that carries a key is checked by that key', async () => {
  const { filters } = mount({ canUpdate: () => false });
  await assert.rejects(
    filters['items.create']({ sample_id: { sample_id: 's7' } }, { collection: 'sample_co_owners' }, ctx()),
    denied(/s7/),
  );
});

test('a 403 from the read means "cannot update"; any other error is rethrown', async () => {
  const forbiddenRead = Object.assign(new Error('nope'), { code: 'FORBIDDEN', status: 403 });
  await assert.rejects(
    mount({ readError: forbiddenRead }).filters['items.create']({ sample_id: 's1' }, { collection: 'sample_co_owners' }, ctx()),
    denied(/s1/),
  );
  const boom = new Error('connection lost');
  await assert.rejects(
    mount({ readError: boom }).filters['items.create']({ sample_id: 's1' }, { collection: 'sample_co_owners' }, ctx()),
    (err) => err === boom,
  );
});

test('update: repointing the sample key is checked, and refused without the right', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = fakeDb([{ id: 5, sample_id: 's1' }]);
  await assert.rejects(
    filters['items.update']({ sample_id: 's2' }, { collection: 'sample_co_owners', keys: [5] }, ctx({ database })),
    denied(/s2/),
  );
  assert.deepEqual(database.calls, [{ table: 'sample_co_owners', column: 'id', keys: [5], columns: ['id', 'sample_id'] }]);
  assert.equal(log.reads.length, 1);
});

test('update: a key sent with its current value is not a change', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = fakeDb([{ id: 5, campaign_id: 'c1', sample_id: 's1' }]);
  const payload = { campaign_id: 'c1', sample_id: 's1', note: 'x' };
  assert.equal(
    await filters['items.update'](payload, { collection: 'campaign_samples', keys: [5] }, ctx({ database })),
    payload,
  );
  assert.equal(log.reads.length, 0);
});

test('update: only the repointed campaign_samples key is checked', async () => {
  const { filters, log } = mount({ canUpdate: (c) => c === 'campaigns' });
  const database = fakeDb([{ id: 5, campaign_id: 'c1', sample_id: 's1' }]);
  await filters['items.update'](
    { campaign_id: 'c2', sample_id: 's1' },
    { collection: 'campaign_samples', keys: [5] },
    ctx({ database }),
  );
  assert.deepEqual(log.reads.map((r) => r.collection), ['campaigns']);
  await assert.rejects(
    filters['items.update']({ sample_id: 's2' }, { collection: 'campaign_samples', keys: [5] }, ctx({ database })),
    denied(/s2/),
  );
});

test('update: changing the person (user_id) or other columns checks nothing', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = fakeDb([{ id: 5, sample_id: 's1' }]);
  await filters['items.update']({ user_id: 'u9' }, { collection: 'sample_co_owners', keys: [5] }, ctx({ database }));
  assert.equal(log.reads.length, 0);
  assert.equal(database.calls.length, 0);
});

test('update: clearing a parent key grants nothing', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  await filters['items.update']({ sample_id: null }, { collection: 'sample_co_owners', keys: [5] }, ctx({ database: fakeDb([{ id: 5, sample_id: 's1' }]) }));
  assert.equal(log.reads.length, 0);
});

// ---- owner guard: changing the owner column needs the record's delete rule ----------------------

// db(table).whereIn(pk, keys).select(...) -> the rows of `existing` for those keys.
function ownerDb(existing) {
  const calls = [];
  const db = (table) => ({
    whereIn: (column, keys) => ({
      select: async (...columns) => {
        calls.push({ table, column, keys, columns });
        return existing.filter((row) => keys.includes(row[column]));
      },
    }),
  });
  db.calls = calls;
  return db;
}

test('the shipped rules guard the owner column where update is wider than delete', () => {
  const guards = JSON.parse(readFileSync(new URL('./rules.json', import.meta.url), 'utf8')).ownerGuards;
  assert.deepEqual(Object.keys(guards).sort(), ['manufacturing_operations', 'physical_samples', 'test_sessions']);
  for (const [collection, g] of Object.entries(guards)) {
    assert.equal(g.field, 'owner_person_id', collection);
    assert.equal(g.valueKey, 'person_id', collection);
    // the delete rule: the owner only, not the co-owners the update rule also lets in
    assert.ok(JSON.stringify(g.filter).includes('$CURRENT_USER'), collection);
    assert.ok(!JSON.stringify(g.filter).includes('co_owners'), collection);
  }
});

test('owner change: a co-owner (who cannot delete) is refused', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = ownerDb([{ sample_id: 's1', owner_person_id: 'p-owner' }]);
  await assert.rejects(
    filters['items.update']({ owner_person_id: 'p-me' }, { collection: 'physical_samples', keys: ['s1'] }, ctx({ database })),
    denied(/physical_samples s1/),
  );
  assert.deepEqual(database.calls, [
    { table: 'physical_samples', column: 'sample_id', keys: ['s1'], columns: ['sample_id', 'owner_person_id'] },
  ]);
  // the check is the delete rule (owner only), run as the caller on the sample itself
  const [{ collection, query }] = log.reads;
  assert.equal(collection, 'physical_samples');
  assert.deepEqual(query.filter._and[0], { sample_id: { _eq: 's1' } });
  const sent = JSON.stringify(query.filter._and[1]);
  assert.ok(sent.includes('user-1') && !sent.includes('$CURRENT_USER') && !sent.includes('co_owners'));
});

test('owner change: the owner handing over is allowed', async () => {
  const { filters, log } = mount({ canUpdate: () => true });
  const payload = { owner_person_id: 'p-new', notes: 'x' };
  const database = ownerDb([{ operation_id: 'o1', owner_person_id: 'p-me' }]);
  assert.equal(
    await filters['items.update'](payload, { collection: 'manufacturing_operations', keys: ['o1'] }, ctx({ database })),
    payload,
  );
  assert.equal(log.reads.length, 1);
  assert.equal(log.reads[0].collection, 'manufacturing_operations');
});

test('owner change: each guarded collection is checked against its own key', async () => {
  for (const [collection, pk] of [['physical_samples', 'sample_id'], ['manufacturing_operations', 'operation_id'], ['test_sessions', 'session_id']]) {
    const { filters, log } = mount({ canUpdate: () => false });
    const database = ownerDb([{ [pk]: 'k1', owner_person_id: 'p1' }]);
    await assert.rejects(
      filters['items.update']({ owner_person_id: 'p2' }, { collection, keys: ['k1'] }, ctx({ database })),
      denied(new RegExp(`${collection} k1`)),
    );
    assert.deepEqual(log.reads[0].query.fields, [pk]);
  }
});

test('owner change: admins and internal calls are not checked', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = ownerDb([{ sample_id: 's1', owner_person_id: 'p1' }]);
  const meta = { collection: 'physical_samples', keys: ['s1'] };
  await filters['items.update']({ owner_person_id: 'p2' }, meta, ctx({ database, accountability: { user: 'a', admin: true } }));
  await filters['items.update']({ owner_person_id: 'p2' }, meta, ctx({ database, accountability: null }));
  await filters['items.update']({ owner_person_id: 'p2' }, meta, ctx({ database, accountability: { user: null, admin: false } }));
  assert.equal(log.reads.length, 0);
  assert.equal(database.calls.length, 0);
});

test('owner change: a payload without the owner field is untouched', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = ownerDb([{ sample_id: 's1', owner_person_id: 'p1' }]);
  const payload = { sample_code: 'X-2', project_id: 'p9' };
  assert.equal(
    await filters['items.update'](payload, { collection: 'physical_samples', keys: ['s1'] }, ctx({ database })),
    payload,
  );
  assert.equal(log.reads.length, 0);
  assert.equal(database.calls.length, 0);
});

test('owner change: sending the current owner back (a form save) is not a change', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = ownerDb([{ sample_id: 's1', owner_person_id: 'p1' }]);
  const payload = { owner_person_id: 'p1', notes: 'x' };
  await filters['items.update'](payload, { collection: 'physical_samples', keys: ['s1'] }, ctx({ database }));
  await filters['items.update']({ owner_person_id: { person_id: 'p1' } }, { collection: 'physical_samples', keys: ['s1'] }, ctx({ database }));
  assert.equal(log.reads.length, 0);
});

test('owner change: clearing the owner is a change; clearing an empty owner is not', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  await assert.rejects(
    filters['items.update'](
      { owner_person_id: null },
      { collection: 'test_sessions', keys: ['t1'] },
      ctx({ database: ownerDb([{ session_id: 't1', owner_person_id: 'p1' }]) }),
    ),
    denied(/test_sessions t1/),
  );
  await filters['items.update'](
    { owner_person_id: null },
    { collection: 'test_sessions', keys: ['t2'] },
    ctx({ database: ownerDb([{ session_id: 't2', owner_person_id: null }]) }),
  );
  assert.equal(log.reads.length, 1);
});

test('owner change: setting an owner on an unowned record needs the delete rule too', async () => {
  const { filters } = mount({ canUpdate: () => false });
  await assert.rejects(
    filters['items.update'](
      { owner_person_id: 'p-me' },
      { collection: 'physical_samples', keys: ['s1'] },
      ctx({ database: ownerDb([{ sample_id: 's1', owner_person_id: null }]) }),
    ),
    denied(/s1/),
  );
});

test('owner change: a nested new person (no key) is a change', async () => {
  const { filters } = mount({ canUpdate: () => false });
  await assert.rejects(
    filters['items.update'](
      { owner_person_id: { full_name: 'New Person' } },
      { collection: 'physical_samples', keys: ['s1'] },
      ctx({ database: ownerDb([{ sample_id: 's1', owner_person_id: 'p1' }]) }),
    ),
    denied(/s1/),
  );
});

test('owner change: a batch update is checked per key, and one refused key refuses the batch', async () => {
  const { filters, log } = mount({ canUpdate: (_c, id) => id !== 's2' });
  const database = ownerDb([
    { sample_id: 's1', owner_person_id: 'p-me' },
    { sample_id: 's2', owner_person_id: 'p-other' },
    { sample_id: 's3', owner_person_id: 'p-me' },
  ]);
  await assert.rejects(
    filters['items.update']({ owner_person_id: 'p-new' }, { collection: 'physical_samples', keys: ['s1', 's2', 's3'] }, ctx({ database })),
    denied(/s2/),
  );
  assert.deepEqual(log.reads.map((r) => r.query.filter._and[0].sample_id._eq), ['s1', 's2']);
  assert.deepEqual(database.calls[0].keys, ['s1', 's2', 's3']);

  const ok = mount({ canUpdate: () => true });
  await ok.filters['items.update']({ owner_person_id: 'p-new' }, { collection: 'physical_samples', keys: ['s1', 's3'] }, ctx({ database }));
  assert.equal(ok.log.reads.length, 2);
});

test('owner change: only the keys whose owner actually changes are checked', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = ownerDb([
    { sample_id: 's1', owner_person_id: 'p-new' },
    { sample_id: 's2', owner_person_id: 'p-new' },
  ]);
  await filters['items.update']({ owner_person_id: 'p-new' }, { collection: 'physical_samples', keys: ['s1', 's2'] }, ctx({ database }));
  assert.equal(log.reads.length, 0);
});

test('owner change: a 403 from the read means "not the owner"; other errors are rethrown', async () => {
  const forbiddenRead = Object.assign(new Error('nope'), { code: 'FORBIDDEN', status: 403 });
  const database = ownerDb([{ sample_id: 's1', owner_person_id: 'p1' }]);
  await assert.rejects(
    mount({ readError: forbiddenRead }).filters['items.update']({ owner_person_id: 'p2' }, { collection: 'physical_samples', keys: ['s1'] }, ctx({ database })),
    denied(/s1/),
  );
  const boom = new Error('connection lost');
  await assert.rejects(
    mount({ readError: boom }).filters['items.update']({ owner_person_id: 'p2' }, { collection: 'physical_samples', keys: ['s1'] }, ctx({ database })),
    (err) => err === boom,
  );
});

test('owner change: collections without an owner guard, and creates, are left alone', async () => {
  const { filters, log } = mount({ canUpdate: () => false });
  const database = ownerDb([{ id: 1, owner_person_id: 'p1' }]);
  for (const collection of ['campaigns', 'projects', 'etchants', 'sample_co_owners']) {
    await filters['items.update']({ owner_person_id: 'p2' }, { collection, keys: [1] }, ctx({ database }));
  }
  await filters['items.create']({ owner_person_id: 'p2' }, { collection: 'physical_samples' }, ctx({ database }));
  assert.equal(log.reads.length, 0);
  assert.equal(database.calls.length, 0);
});
