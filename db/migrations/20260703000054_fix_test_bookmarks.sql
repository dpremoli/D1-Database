-- migrate:up
-- Fix the two broken test_sessions bookmarks. They filtered on
-- `test_category _contains 'Imaging'/'Dynamic'`, but the test_category taxonomy is
-- lowercase nde/destructive/dynamic and is a nullable, auto-inferred column — so the
-- filters matched nothing. Refile them against `test_type` (the real discriminator,
-- always populated) via `_in` over each family's full method set, so the bookmarks
-- keep working as new methods get used.

UPDATE directus_presets
SET filter = '{"_and":[{"test_type":{"_in":["optical_microscopy","sem","tem","xrd","alicona","clemx","dct","ct_scan"]}}]}'
WHERE collection = 'test_sessions' AND bookmark = 'Imaging';

UPDATE directus_presets
SET filter = '{"_and":[{"test_type":{"_in":["tensile","hardness","charpy","compression","tribology","fatigue","creep","dma"]}}]}'
WHERE collection = 'test_sessions' AND bookmark = 'Physical';

-- migrate:down
UPDATE directus_presets
SET filter = '{"_and":[{"test_category":{"_contains":"Imaging"}}]}'
WHERE collection = 'test_sessions' AND bookmark = 'Imaging';

UPDATE directus_presets
SET filter = '{"_and":[{"test_category":{"_contains":"Dynamic"}}]}'
WHERE collection = 'test_sessions' AND bookmark = 'Physical';
