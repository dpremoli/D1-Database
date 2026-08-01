-- Field value presets: turn free-text param fields into dropdowns that offer
-- common values but still accept a new one (allowOther). Run AFTER
-- configure_inline_params.sql (these are inline param fields). Only interface +
-- options are changed — conditions/labels/units are preserved.

BEGIN;

-- ── SEM ───────────────────────────────────────────────────────────────────────
UPDATE directus_fields SET interface='select-dropdown',
  options='{"allowOther":true,"choices":[{"text":"100×–1,000×","value":"100x-1000x"},{"text":"1,000×–10,000×","value":"1000x-10000x"},{"text":"10,000×–50,000×","value":"10000x-50000x"},{"text":"50,000×–100,000×","value":"50000x-100000x"},{"text":">100,000×","value":">100000x"}]}'
WHERE collection='test_sessions' AND field='sem_magnification_range';

UPDATE directus_fields SET interface='select-dropdown',
  options='{"allowOther":true,"choices":[{"text":"Gold (Au)","value":"Au"},{"text":"Platinum (Pt)","value":"Pt"},{"text":"Gold/Palladium (Au/Pd)","value":"Au/Pd"},{"text":"Carbon (C)","value":"C"},{"text":"Iridium (Ir)","value":"Ir"},{"text":"None (uncoated)","value":"none"}]}'
WHERE collection='test_sessions' AND field='sem_coating_material';

UPDATE directus_fields SET interface='select-dropdown',
  options='{"allowOther":true,"choices":[{"text":"Kalling''s No.2","value":"Kallings 2"},{"text":"Marble''s","value":"Marbles"},{"text":"Nital","value":"Nital"},{"text":"Kroll''s","value":"Krolls"},{"text":"Electrolytic","value":"electrolytic"},{"text":"None","value":"none"}]}'
WHERE collection='test_sessions' AND field='sem_etchant';

-- ── XRD ───────────────────────────────────────────────────────────────────────
UPDATE directus_fields SET interface='select-dropdown',
  options='{"allowOther":true,"choices":[{"text":"Cu Kα","value":"Cu Ka"},{"text":"Co Kα","value":"Co Ka"},{"text":"Cr Kα","value":"Cr Ka"},{"text":"Mo Kα","value":"Mo Ka"},{"text":"Fe Kα","value":"Fe Ka"}]}'
WHERE collection='test_sessions' AND field='xrd_radiation_source';

UPDATE directus_fields SET interface='select-dropdown',
  options='{"allowOther":true,"choices":[{"text":"Scintillation","value":"scintillation"},{"text":"Si strip (LynxEye)","value":"si_strip"},{"text":"CCD","value":"ccd"},{"text":"Image plate","value":"image_plate"}]}'
WHERE collection='test_sessions' AND field='xrd_detector_type';

COMMIT;
