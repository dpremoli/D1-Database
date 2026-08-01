// Directus endpoint: d1-ask  (mounted at /d1-ask)
//
// Server-side proxy between the "Ask the Database" module (browser) and the
// guarded text-to-SQL plugin (llm-text-to-sql on the internal d1net). It exists
// so that:
//   1. the browser never learns WORKER_WEBHOOK_SECRET (injected here, server-side),
//   2. the plugin need not be exposed to the host — only Directus calls it,
//   3. access is gated by Directus auth (and, by extension, RBAC): a request
//      with no authenticated user is rejected before any LLM/DB work happens.
//
// The plugin still applies its own SQL guard + read-only role (ADR-0009); this
// endpoint adds the authentication boundary, it does not replace the guard.

const PLUGIN_URL = (env) =>
    (env.LLM_PLUGIN_URL || 'http://llm-text-to-sql:8080').replace(/\/+$/, '');

export default {
    id: 'd1-ask',
    handler: (router, { env, logger }) => {
        // POST /d1-ask/chat  →  plugin POST /api/chat
        // Body: { messages: [{role, content}...], row_limit? }
        router.post('/chat', async (req, res) => {
            if (!req.accountability?.user) {
                return res.status(401).json({ error: 'authentication required' });
            }

            const secret = env.WORKER_WEBHOOK_SECRET || '';
            try {
                const upstream = await fetch(`${PLUGIN_URL(env)}/api/chat`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(secret ? { 'X-Worker-Secret': secret } : {}),
                    },
                    body: JSON.stringify(req.body ?? {}),
                });

                // Relay the plugin's status and JSON verbatim (including its 422
                // "generated SQL rejected" responses, so the UI can explain them).
                const text = await upstream.text();
                res.status(upstream.status);
                res.set('Content-Type', 'application/json');
                return res.send(text || '{}');
            } catch (err) {
                logger.error(`d1-ask proxy failed: ${err.message}`);
                return res
                    .status(502)
                    .json({ error: 'text-to-SQL service unavailable' });
            }
        });
    },
};
