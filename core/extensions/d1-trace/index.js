// Directus endpoint: d1-trace  (mounted at /d1-trace)
//
// GET /d1-trace/sample/:id  ->  the sample's cradle-to-grave story:
//   { sample, stock_origins[], ancestors[], events[], descendants[], hidden{}, truncated{} }
//
// The four traceability functions (db/migrations/20260619000014_traceability.sql) are plain SQL run
// as the database owner, so they ignore Directus permissions. This endpoint runs them and then
// keeps only the records the CALLER may read: every referenced id is re-read through Directus's
// ItemsService with req.accountability, and anything not returned is dropped and only counted.
// A sample the caller cannot read is a 404 (the same as a missing one). Design:
// docs/superpowers/specs/2026-10-06-sample-timeline-and-campaign-overview-design.md

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Per-section cap so a pathological genealogy cannot produce an unbounded response.
const MAX_ROWS = 500;
// ids per readByQuery `_in`, to keep the SQL parameter list small.
const CHUNK = 200;

const isDenied = (err) => err?.code === 'FORBIDDEN' || err?.status === 403;

// The set of ids (of `collection`) the caller may read. Directus applies the role's collection,
// item and field rules; a forbidden collection reads as "none readable". '*' = every field the
// caller may see (an explicit field list is refused outright if any listed field is restricted).
async function readableIds({ ItemsService, accountability, schema }, collection, pk, ids) {
    const unique = [...new Set(ids.filter(Boolean))];
    const ok = new Set();
    for (let i = 0; i < unique.length; i += CHUNK) {
        const chunk = unique.slice(i, i + CHUNK);
        try {
            const rows = await new ItemsService(collection, { accountability, schema }).readByQuery({
                filter: { [pk]: { _in: chunk } },
                fields: ['*'],
                limit: -1,
            });
            for (const r of rows ?? []) if (r?.[pk]) ok.add(r[pk]);
        } catch (err) {
            if (isDenied(err)) return new Set();
            throw err;
        }
    }
    return ok;
}

const num = (v) => (v === null || v === undefined ? null : Number(v));
const iso = (d) => (d instanceof Date ? d.toISOString() : (d ?? null));

export default {
    id: 'd1-trace',
    handler: (router, { database, logger, services, getSchema }) => {
        router.get('/sample/:id', async (req, res) => {
            const acc = req.accountability;
            if (!acc?.user) {
                return res.status(401).json({ error: 'authentication required' });
            }
            if (!(acc.admin || acc.app)) {
                return res.status(403).json({ error: 'forbidden' });
            }
            const id = req.params?.id;
            if (typeof id !== 'string' || !UUID.test(id)) {
                return res.status(400).json({ error: 'id must be a sample_id (uuid)' });
            }
            try {
                const ctx = {
                    ItemsService: services.ItemsService,
                    accountability: acc,
                    schema: req.schema ?? (await getSchema()),
                };
                const readable = (collection, pk, ids) => readableIds(ctx, collection, pk, ids);

                // Root first: unreadable and missing look the same, and nothing else is queried.
                const root = await readable('physical_samples', 'sample_id', [id]);
                if (!root.has(id)) return res.status(404).json({ error: 'sample not found' });

                const q = async (fn) => (await database.raw(`SELECT * FROM ${fn}(?::uuid)`, [id]))?.rows ?? [];
                const [anc, desc, stock, events] = await Promise.all([
                    q('f_trace_ancestors'),
                    q('f_trace_descendants'),
                    q('f_trace_stock_origins'),
                    q('f_sample_timeline'),
                ]);

                const truncated = {};
                const cap = (name, rows) => {
                    if (rows.length > MAX_ROWS) {
                        truncated[name] = true;
                        return rows.slice(0, MAX_ROWS);
                    }
                    return rows;
                };
                const byDepth = (a, b) => a.depth - b.depth;
                const ancestors = cap('ancestors', anc.filter((r) => r.sample_id !== id).sort(byDepth));
                const descendants = cap('descendants', desc.filter((r) => r.sample_id !== id).sort(byDepth));
                const stockRows = cap('stock_origins', stock);
                const eventRows = cap('events', events);
                const self = anc.find((r) => r.sample_id === id) ?? desc.find((r) => r.sample_id === id);

                // Ids to check, per collection. Sample ids also include every id on a path, so a
                // node reached through an unreadable one can be marked.
                const sampleIds = new Set([id]);
                for (const r of [...ancestors, ...descendants]) {
                    sampleIds.add(r.sample_id);
                    for (const p of r.path ?? []) sampleIds.add(p);
                }
                for (const r of stockRows) sampleIds.add(r.via_sample_id);
                const [okSamples, okOps, okTests, okLots] = await Promise.all([
                    readable('physical_samples', 'sample_id', [...sampleIds]),
                    readable(
                        'manufacturing_operations',
                        'operation_id',
                        eventRows.filter((e) => e.event_type === 'manufacturing_operation').map((e) => e.event_id),
                    ),
                    readable(
                        'test_sessions',
                        'session_id',
                        eventRows.filter((e) => e.event_type === 'test_session').map((e) => e.event_id),
                    ),
                    readable('raw_stock_lots', 'lot_id', stockRows.map((r) => r.lot_id)),
                ]);

                const hidden = { stock_origins: 0, ancestors: 0, events: 0, descendants: 0 };

                const lineage = (name, rows) => {
                    const out = [];
                    for (const r of rows) {
                        if (!okSamples.has(r.sample_id)) {
                            hidden[name]++;
                            continue;
                        }
                        out.push({
                            depth: r.depth,
                            sample_id: r.sample_id,
                            sample_code: r.sample_code,
                            form: r.form,
                            relationship_type: r.relationship_type,
                            fraction: num(r.fraction),
                            // true when the walk from the root passes an unreadable sample
                            through_hidden: (r.path ?? []).some((p) => p !== id && !okSamples.has(p)),
                        });
                    }
                    return out;
                };

                const stock_origins = [];
                for (const r of stockRows) {
                    if (!okLots.has(r.lot_id)) {
                        hidden.stock_origins++;
                        continue;
                    }
                    stock_origins.push({
                        lot_id: r.lot_id,
                        lot_code: r.lot_code,
                        stock_type: r.stock_type,
                        supplier_name: r.supplier_name,
                        mass_used_grams: num(r.mass_used_grams),
                        via_sample_id: r.via_sample_id,
                        via_sample_code: okSamples.has(r.via_sample_id) ? r.via_sample_code : null,
                        depth: r.depth,
                    });
                }

                const out = [];
                for (const e of eventRows) {
                    const isOp = e.event_type === 'manufacturing_operation';
                    const ok = isOp ? okOps.has(e.event_id) : e.event_type === 'test_session' && okTests.has(e.event_id);
                    if (!ok) {
                        hidden.events++;
                        continue;
                    }
                    // Only identifying fields are passed on; operator names and file pointers in
                    // `detail` are deliberately left out.
                    out.push({
                        type: e.event_type,
                        collection: isOp ? 'manufacturing_operations' : 'test_sessions',
                        id: e.event_id,
                        date: iso(e.event_date),
                        label: e.label,
                        sequence: isOp ? (e.detail?.sequence ?? null) : null,
                        status: isOp ? null : (e.detail?.status ?? null),
                    });
                }

                return res.json({
                    sample: { sample_id: id, sample_code: self?.sample_code ?? null, form: self?.form ?? null },
                    stock_origins,
                    ancestors: lineage('ancestors', ancestors),
                    events: out,
                    descendants: lineage('descendants', descendants),
                    hidden,
                    truncated,
                });
            } catch (e) {
                logger.error(`d1-trace: ${e?.message || e}`);
                return res.status(500).json({ error: 'could not read the sample timeline' });
            }
        });
    },
};
