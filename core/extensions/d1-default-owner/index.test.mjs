// Run with: node --test core/extensions/d1-default-owner/index.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';

import hook from './index.js';

function mount() {
  const filters = {};
  hook({ filter: (name, fn) => (filters[name] = fn) });
  return filters;
}

// A knex stand-in: db('people').where('user_id', id).first('person_id') -> the person row or undefined.
function fakeDb(peopleByUser) {
  const calls = [];
  const db = (table) => ({
    where: (column, value) => ({
      first: async (columns) => {
        calls.push({ table, column, value, columns });
        return peopleByUser[value];
      },
    }),
  });
  db.calls = calls;
  return db;
}

const ctx = (db, user = 'user-1') => ({ database: db, accountability: user ? { user } : null });

test('registers only an items.create filter', () => {
  assert.deepEqual(Object.keys(mount()), ['items.create']);
});

for (const collection of ['physical_samples', 'manufacturing_operations', 'test_sessions', 'campaigns']) {
  test(`${collection}: a new record defaults to the creator's person`, async () => {
    const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
    const payload = { name: 'x' };
    const out = await mount()['items.create'](payload, { collection }, ctx(db));
    assert.equal(out, payload);
    assert.equal(payload.owner_person_id, 'person-1');
    assert.deepEqual(db.calls, [{ table: 'people', column: 'user_id', value: 'user-1', columns: 'person_id' }]);
  });
}

test('projects: a new project defaults its principal investigator to the creator, not owner_person_id', async () => {
  const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
  const payload = { project_code: 'P1' };
  await mount()['items.create'](payload, { collection: 'projects' }, ctx(db));
  assert.equal(payload.principal_investigator_person, 'person-1');
  assert.equal('owner_person_id' in payload, false);
  assert.deepEqual(db.calls, [{ table: 'people', column: 'user_id', value: 'user-1', columns: 'person_id' }]);
});

test('projects: an explicit principal investigator wins and is not looked up', async () => {
  const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
  const payload = { principal_investigator_person: 'someone-else' };
  await mount()['items.create'](payload, { collection: 'projects' }, ctx(db));
  assert.equal(payload.principal_investigator_person, 'someone-else');
  assert.equal(db.calls.length, 0);
});

test('projects: an explicit null principal investigator is filled; an owner_person_id is ignored', async () => {
  const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
  const payload = { principal_investigator_person: null, owner_person_id: 'x' };
  await mount()['items.create'](payload, { collection: 'projects' }, ctx(db));
  assert.equal(payload.principal_investigator_person, 'person-1');
  assert.equal(payload.owner_person_id, 'x');
});

test('every collection fills only its own field', async () => {
  const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
  for (const [collection, field] of [
    ['physical_samples', 'owner_person_id'],
    ['manufacturing_operations', 'owner_person_id'],
    ['test_sessions', 'owner_person_id'],
    ['campaigns', 'owner_person_id'],
    ['projects', 'principal_investigator_person'],
  ]) {
    const payload = {};
    await mount()['items.create'](payload, { collection }, ctx(db));
    assert.deepEqual(payload, { [field]: 'person-1' }, collection);
  }
});

test('an explicit owner wins, and is not even looked up', async () => {
  const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
  const payload = { owner_person_id: 'someone-else' };
  await mount()['items.create'](payload, { collection: 'physical_samples' }, ctx(db));
  assert.equal(payload.owner_person_id, 'someone-else');
  assert.equal(db.calls.length, 0);
});

test('an explicit null owner is treated as blank and filled', async () => {
  const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
  const payload = { owner_person_id: null };
  await mount()['items.create'](payload, { collection: 'campaigns' }, ctx(db));
  assert.equal(payload.owner_person_id, 'person-1');
});

test('other collections are left alone', async () => {
  const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
  for (const collection of ['materials', 'equipment', 'sample_co_owners', 'people', undefined]) {
    const payload = {};
    await mount()['items.create'](payload, { collection }, ctx(db));
    assert.deepEqual(payload, {}, String(collection));
  }
  assert.equal(db.calls.length, 0);
});

test('a user without a people row, or no user at all, gets no default', async () => {
  const noPerson = {};
  await mount()['items.create'](noPerson, { collection: 'physical_samples' }, ctx(fakeDb({})));
  assert.equal('owner_person_id' in noPerson, false);

  const anonymous = {};
  const db = fakeDb({});
  await mount()['items.create'](anonymous, { collection: 'physical_samples' }, ctx(db, null));
  assert.equal('owner_person_id' in anonymous, false);
  assert.equal(db.calls.length, 0);
});

test('a missing database or payload does not throw', async () => {
  const filters = mount();
  assert.equal(await filters['items.create'](null, { collection: 'physical_samples' }, ctx(fakeDb({}))), null);
  const payload = {};
  assert.equal(await filters['items.create'](payload, { collection: 'physical_samples' }, { accountability: { user: 'u' } }), payload);
});

test('an array payload (createMany) fills every blank item with one lookup', async () => {
  const db = fakeDb({ 'user-1': { person_id: 'person-1' } });
  const payload = [{ a: 1 }, { owner_person_id: 'other' }, { owner_person_id: null }];
  await mount()['items.create'](payload, { collection: 'test_sessions' }, ctx(db));
  assert.deepEqual(
    payload.map((p) => p.owner_person_id),
    ['person-1', 'other', 'person-1'],
  );
  assert.equal(db.calls.length, 1);
});
