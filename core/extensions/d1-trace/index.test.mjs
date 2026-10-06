// Run with: node --test core/extensions/d1-trace/index.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';

import ext from './index.js';

const ROOT = '11111111-1111-1111-1111-111111111111';
const PARENT = '22222222-2222-2222-2222-222222222222';
const GRAND = '33333333-3333-3333-3333-333333333333';
const CHILD = '44444444-4444-4444-4444-444444444444';
const OP1 = 'aaaaaaaa-0000-0000-0000-000000000001';
const OP2 = 'aaaaaaaa-0000-0000-0000-000000000002';
const TS1 = 'bbbbbbbb-0000-0000-0000-000000000001';
const LOT1 = 'cccccccc-0000-0000-0000-000000000001';

const PK = {
    physical_samples: 'sample_id',
    manufacturing_operations: 'operation_id',
    test_sessions: 'session_id',
    raw_stock_lots: 'lot_id',
};

// What the (permission-ignoring) SQL functions return.
const fnRows = {
    f_trace_ancestors: [
        { depth: 0, sample_id: ROOT, sample_code: '9-AA-1', form: 'bar', relationship_type: null, fraction: null, path: [ROOT] },
        { depth: 1, sample_id: PARENT, sample_code: '9-AA-0', form: 'bar', relationship_type: 'cut_from', fraction: '0.5', path: [ROOT, PARENT] },
        { depth: 2, sample_id: GRAND, sample_code: '9-A-0', form: 'rod', relationship_type: 'cut_from', fraction: null, path: [ROOT, PARENT, GRAND] },
    ],
    f_trace_descendants: [
        { depth: 0, sample_id: ROOT, sample_code: '9-AA-1', form: 'bar', relationship_type: null, fraction: null, path: [ROOT] },
        { depth: 1, sample_id: CHILD, sample_code: '9-AA-2', form: 'coupon', relationship_type: 'cut_from', fraction: null, path: [ROOT, CHILD] },
    ],
    f_trace_stock_origins: [
        { via_sample_id: GRAND, via_sample_code: '9-A-0', depth: 2, lot_id: LOT1, lot_code: 'LOT-1', stock_type: 'rod', supplier_name: 'Acme', mass_used_grams: '120.5' },
    ],
    f_sample_timeline: [
        { event_date: new Date('2026-01-02T00:00:00Z'), event_type: 'manufacturing_operation', event_id: OP1, label: 'P1', detail: { sequence: 1, operator: 'Secret Name' } },
        { event_date: new Date('2026-01-03T00:00:00Z'), event_type: 'test_session', event_id: TS1, label: 'tensile', detail: { status: 'complete', file_storage_pointer: 's3://x' } },
        { event_date: null, event_type: 'manufacturing_operation', event_id: OP2, label: 'P2', detail: { sequence: 2 } },
    ],
};

// `readable` = ids the caller may read; everything else is invisible to the fake ItemsService.
function mount({ readable, denyCollections = [], rows = fnRows, dbError = false } = {}) {
    const reads = [];
    class ItemsService {
        constructor(collection, opts) {
            this.collection = collection;
            this.opts = opts;
        }
        async readByQuery(query) {
            reads.push({ collection: this.collection, opts: this.opts, query });
            if (denyCollections.includes(this.collection)) {
                const e = new Error('no');
                e.code = 'FORBIDDEN';
                throw e;
            }
            const pk = PK[this.collection];
            return query.filter[pk]._in.filter((id) => readable.has(id)).map((id) => ({ [pk]: id }));
        }
    }
    const database = {
        raw: async (sql) => {
            if (dbError) throw new Error('boom');
            const fn = /FROM (\w+)\(/.exec(sql)[1];
            return { rows: rows[fn] };
        },
    };
    let handler;
    const router = { get: (_p, fn) => (handler = fn) };
    ext.handler(router, {
        database,
        logger: { error: () => {} },
        services: { ItemsService },
        getSchema: async () => ({ fake: true }),
    });
    return { handler, reads };
}

function call(handler, accountability, id = ROOT) {
    return new Promise((resolve) => {
        const out = { status: 200, body: undefined };
        const res = {
            status(code) {
                out.status = code;
                return res;
            },
            json(b) {
                out.body = b;
                resolve(out);
                return res;
            },
        };
        handler({ accountability, params: { id } }, res);
    });
}

const user = { user: 'u', app: true, role: 'r' };
const all = new Set([ROOT, PARENT, GRAND, CHILD, OP1, OP2, TS1, LOT1]);

test('refuses anonymous callers (401) and users without app access (403)', async () => {
    const { handler } = mount({ readable: all });
    assert.equal((await call(handler, null)).status, 401);
    assert.equal((await call(handler, {})).status, 401);
    assert.equal((await call(handler, { user: 'u', app: false, admin: false })).status, 403);
});

test('rejects an id that is not a uuid before touching the database', async () => {
    const { handler, reads } = mount({ readable: all });
    assert.equal((await call(handler, user, "x'; drop table physical_samples")).status, 400);
    assert.equal((await call(handler, user, null)).status, 400);
    assert.equal(reads.length, 0);
});

test('a sample the caller cannot read is 404, same as a missing one, and nothing else is read', async () => {
    const { handler, reads } = mount({ readable: new Set([PARENT]) });
    const r = await call(handler, user);
    assert.equal(r.status, 404);
    assert.equal(reads.length, 1);
    assert.equal(reads[0].collection, 'physical_samples');
});

test('a fully readable sample returns the whole story, in order, and reads with the caller accountability', async () => {
    const { handler, reads } = mount({ readable: all });
    const r = await call(handler, user);
    assert.equal(r.status, 200);
    const b = r.body;
    assert.deepEqual(b.sample, { sample_id: ROOT, sample_code: '9-AA-1', form: 'bar' });
    assert.deepEqual(b.ancestors.map((a) => [a.sample_code, a.depth, a.through_hidden]), [
        ['9-AA-0', 1, false],
        ['9-A-0', 2, false],
    ]);
    assert.equal(b.ancestors[0].fraction, 0.5);
    assert.deepEqual(b.descendants.map((d) => d.sample_code), ['9-AA-2']);
    assert.deepEqual(b.stock_origins, [
        { lot_id: LOT1, lot_code: 'LOT-1', stock_type: 'rod', supplier_name: 'Acme', mass_used_grams: 120.5, via_sample_id: GRAND, via_sample_code: '9-A-0', depth: 2 },
    ]);
    assert.deepEqual(b.events.map((e) => [e.collection, e.id, e.label]), [
        ['manufacturing_operations', OP1, 'P1'],
        ['test_sessions', TS1, 'tensile'],
        ['manufacturing_operations', OP2, 'P2'],
    ]);
    assert.equal(b.events[0].date, '2026-01-02T00:00:00.000Z');
    assert.equal(b.events[2].date, null);
    assert.equal(b.events[1].status, 'complete');
    assert.deepEqual(b.hidden, { stock_origins: 0, ancestors: 0, events: 0, descendants: 0 });
    for (const rd of reads) assert.equal(rd.opts.accountability, user);
});

test('never passes on operator names, file pointers or paths', async () => {
    const { handler } = mount({ readable: all });
    const text = JSON.stringify((await call(handler, user)).body);
    assert.ok(!text.includes('Secret Name'));
    assert.ok(!text.includes('s3://x'));
    assert.ok(!text.includes('"path"'));
});

test('unreadable records are dropped and only counted; their codes do not appear', async () => {
    // Role cannot read the parent, the child, one operation, the test session and the lot.
    const { handler } = mount({ readable: new Set([ROOT, GRAND, OP1, OP2]) });
    const r = await call(handler, user);
    assert.equal(r.status, 200);
    const b = r.body;
    assert.deepEqual(b.ancestors.map((a) => a.sample_id), [GRAND]);
    assert.equal(b.ancestors[0].through_hidden, true); // reached through the unreadable parent
    assert.deepEqual(b.descendants, []);
    assert.deepEqual(b.stock_origins, []);
    assert.deepEqual(b.events.map((e) => e.id), [OP1, OP2]);
    assert.deepEqual(b.hidden, { stock_origins: 1, ancestors: 1, events: 1, descendants: 1 });
    const text = JSON.stringify(b);
    for (const secret of ['9-AA-0', '9-AA-2', 'LOT-1', 'tensile', PARENT, CHILD, TS1, LOT1]) {
        assert.ok(!text.includes(secret), `${secret} leaked`);
    }
});

test('a stock origin that came via an unreadable sample hides that sample code', async () => {
    const { handler } = mount({ readable: new Set([ROOT, LOT1]) });
    const b = (await call(handler, user)).body;
    assert.equal(b.stock_origins.length, 1);
    assert.equal(b.stock_origins[0].via_sample_code, null);
});

test('a collection the role has no access to at all reads as all hidden, not an error', async () => {
    const { handler } = mount({ readable: all, denyCollections: ['test_sessions', 'raw_stock_lots'] });
    const r = await call(handler, user);
    assert.equal(r.status, 200);
    assert.deepEqual(r.body.events.map((e) => e.id), [OP1, OP2]);
    assert.equal(r.body.hidden.events, 1);
    assert.equal(r.body.hidden.stock_origins, 1);
});

test('a sample with no genealogy or events returns empty lists', async () => {
    const rows = {
        f_trace_ancestors: [fnRows.f_trace_ancestors[0]],
        f_trace_descendants: [fnRows.f_trace_descendants[0]],
        f_trace_stock_origins: [],
        f_sample_timeline: [],
    };
    const { handler } = mount({ readable: all, rows });
    const b = (await call(handler, user)).body;
    assert.deepEqual([b.ancestors, b.descendants, b.stock_origins, b.events], [[], [], [], []]);
});

test('a database failure is a 500 with no partial data', async () => {
    const { handler } = mount({ readable: all, dbError: true });
    const r = await call(handler, user);
    assert.equal(r.status, 500);
    assert.equal(r.body.ancestors, undefined);
});

test('admins are allowed even without the app flag', async () => {
    const { handler } = mount({ readable: all });
    assert.equal((await call(handler, { user: 'u', admin: true })).status, 200);
});
