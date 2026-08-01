-- migrate:up
-- Add the FAST Analysis module to the Directus module bar (the icon rail down the
-- left side column), right after Force Analysis — mirroring how Force Analysis
-- itself is registered there. The module already exists (d1-fast-dashboard); this
-- just surfaces it as a top-level nav icon instead of only being reachable via
-- deep-links (home button, "View FAST Analysis" jump button).

WITH items AS (
    SELECT ord, elem FROM directus_settings, jsonb_array_elements(module_bar::jsonb) WITH ORDINALITY AS t(elem, ord)
),
expanded AS (
    SELECT ord * 10 AS pos, elem FROM items
    UNION ALL
    SELECT ord * 10 + 1, '{"type":"module","id":"d1-fast-dashboard","enabled":true}'::jsonb
    FROM items WHERE elem->>'id' = 'd1-force-dashboard'
)
UPDATE directus_settings
   SET module_bar = (SELECT jsonb_agg(elem ORDER BY pos) FROM expanded)::json
 WHERE NOT (module_bar::text LIKE '%d1-fast-dashboard%');

-- migrate:down
UPDATE directus_settings
   SET module_bar = (
       SELECT jsonb_agg(elem) FROM jsonb_array_elements(module_bar::jsonb) AS elem
        WHERE elem->>'id' != 'd1-fast-dashboard'
   )::json;
