-- migrate:up
-- Add a type-aware operations manager to the campaign form (d1-campaign-ops): the
-- add-operation search is pre-filtered by the campaign's type (Machining Trial ->
-- machining operations). The native `operations` o2m stays hidden (this replaces it).

INSERT INTO directus_fields (collection, field, interface, special, options, width, sort, hidden, readonly)
SELECT 'campaigns', 'campaign_operations', 'd1-campaign-ops', 'alias,no-data', '{}'::json, 'full', 40, false, false
WHERE NOT EXISTS (SELECT 1 FROM directus_fields f WHERE f.collection='campaigns' AND f.field='campaign_operations');

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'campaigns' AND field = 'campaign_operations';
