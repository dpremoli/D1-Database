-- migrate:up
-- Import the master lab equipment list (~50 instruments across the 5 facilities)
-- into the equipment catalogue. Idempotent: keyed on equipment_name, so re-running
-- inserts only machines that aren't already present (the pre-existing CNC/FAST rows
-- are untouched). equipment_code is a stable 6-char code derived from the name.
--
-- capabilities is a CSV of the process/test categories a machine can perform, which
-- is what the Machine picker filters on (equipment.capabilities _contains category).
-- Pure sample-prep tools (coaters, polishers, cutters, mixers) get NULL capabilities
-- so they don't appear in the operation/test pickers.

WITH incoming (name, fac_code, etype, caps) AS (
    VALUES
        -- Sorby Centre — electron microscopy / FIB / EPMA + prep
        ('Coater: Carbon (Quorum)',            'SORBY',   'Sample_Prep',            NULL),
        ('Coater: Gold (Quorum)',              'SORBY',   'Sample_Prep',            NULL),
        ('FEI Helios NanoLab G3 UC',           'SORBY',   'SEM_FIB',                'nde'),
        ('FEI Inspect F',                      'SORBY',   'SEM',                    'nde'),
        ('FEI Inspect F50',                    'SORBY',   'SEM',                    'nde'),
        ('FEI Nova NanoSEM 450',               'SORBY',   'SEM',                    'nde'),
        ('Gatan PECS II',                      'SORBY',   'Sample_Prep',            NULL),
        ('Gatan PIPS II',                      'SORBY',   'Sample_Prep',            NULL),
        ('JEOL (RDC) JEM 7900F',               'SORBY',   'SEM',                    'nde'),
        ('JEOL (RDC) JEM F200',                'SORBY',   'TEM',                    'nde'),
        ('JEOL (RDC) JXA-8530F Plus',          'SORBY',   'EPMA',                   'nde'),
        ('Leica Ultramicrotome (Inkson)',      'SORBY',   'Sample_Prep',            NULL),
        ('TenuPol Electropolisher (Rainforth)','SORBY',   'Sample_Prep',            NULL),
        ('Zeiss EVO10',                        'SORBY',   'SEM',                    'nde'),
        ('Zepto Plasma Cleaner (Rodenburg)',   'SORBY',   'Sample_Prep',            NULL),
        ('Vibromet Polisher',                  'SORBY',   'Sample_Prep',            NULL),
        -- Royce Discovery Centre — additive + powder handling
        ('Aconity Lab',                        'RDC',     'LPBF_Printer',           'additive'),
        ('Aconity Mini',                       'RDC',     'LPBF_Printer',           'additive'),
        ('Aconity Mini PC',                    'RDC',     'Workstation',            NULL),
        ('BeAM',                               'RDC',     'DED_Printer',            'additive'),
        ('Desktop Metal Printer',              'RDC',     'Binder_Jet_Printer',     'additive'),
        ('Freemelt One',                       'RDC',     'EBM_Printer',            'additive'),
        ('RDC Sieving/Powder Handling Zone',   'RDC',     'Powder_Handling',        NULL),
        ('RDC Workshop Modelling/Netfabb PC',  'RDC',     'Workstation',            NULL),
        ('Resodyn Acoustic Mixer',             'RDC',     'Powder_Mixer',           NULL),
        -- Royce Translational Centre — powder production / HIP / VIM / TMP
        ('Arcam Q10',                          'RTC',     'EBM_Printer',            'additive'),
        ('Atomiser',                           'RTC',     'Atomiser',               'additive'),
        ('Attrition Mill',                     'RTC',     'Mill',                   NULL),
        ('Conform',                            'RTC',     'Extrusion',              'deformation'),
        ('Consarc VIM 25kg/ISM',               'RTC',     'Melting_Furnace',        NULL),
        ('HIP AIP8-45H',                       'RTC',     'HIP',                    'sintering'),
        ('Tekna Tek-15 Spheroidiser',          'RTC',     'Spheroidiser',           'additive'),
        -- Metallography Lab — sectioning / mounting / polishing / optical
        ('Clemex microscope',                  'METLAB',  'Optical_Microscope',     'nde'),
        ('Ecopress - IT',                      'METLAB',  'Mounting_Press',         NULL),
        ('Labotom-20',                         'METLAB',  'Cutter',                 NULL),
        ('Linkam TS1200',                      'METLAB',  'Heating_Stage',          'nde'),
        ('Plastometrex PIP/ Hot PIP',          'METLAB',  'Indentation_Plastometer','destructive'),
        ('Secotom-50 IT',                      'METLAB',  'Cutter',                 NULL),
        ('Secotom-50 STAR',                    'METLAB',  'Cutter',                 NULL),
        ('Struers Citovac',                    'METLAB',  'Impregnation_Unit',      NULL),
        ('Struers LaboForce-100',              'METLAB',  'Grinder_Polisher',       NULL),
        ('Struers Minitom',                    'METLAB',  'Cutter',                 NULL),
        ('Tegramin-20 - IT',                   'METLAB',  'Grinder_Polisher',       NULL),
        ('Tegramin-25 STAR',                   'METLAB',  'Grinder_Polisher',       NULL),
        -- Mechanical Testing Lab — tensile / compression / dilatometry / TMP
        ('Arc Welder TMC',                     'MECHLAB', 'Welder',                 'additive'),
        ('Dilatometer',                        'MECHLAB', 'Dilatometer',            'nde'),
        ('Hounsfield',                         'MECHLAB', 'Universal_Tester',       'destructive'),
        ('TMC',                                'MECHLAB', 'Thermomechanical_Sim',   'destructive,deformation'),
        ('Zwick Röell Z050',                   'MECHLAB', 'Universal_Tester',       'destructive'),
        ('Zwick with Training',                'MECHLAB', 'Universal_Tester',       'destructive')
)
INSERT INTO equipment (equipment_code, equipment_name, equipment_type, facility_id, capabilities)
SELECT upper(substr(md5(i.name), 1, 6)), i.name, i.etype, f.facility_id, i.caps
FROM incoming i
JOIN facilities f ON f.code = i.fac_code
WHERE NOT EXISTS (SELECT 1 FROM equipment e WHERE e.equipment_name = i.name);

-- Correct the stray 'nde' capability on the CNC lathe: a turning centre is not an
-- imaging instrument, and before the real microscopes were imported it was the only
-- machine offered for imaging tests (the "NLX-only" bug). Now real SEMs carry 'nde'.
UPDATE equipment
SET capabilities = 'machining'
WHERE equipment_name = 'NLX-2500 | 700' AND capabilities = 'machining,nde';

-- migrate:down
DELETE FROM equipment
WHERE equipment_name IN (
    'Coater: Carbon (Quorum)','Coater: Gold (Quorum)','FEI Helios NanoLab G3 UC','FEI Inspect F',
    'FEI Inspect F50','FEI Nova NanoSEM 450','Gatan PECS II','Gatan PIPS II','JEOL (RDC) JEM 7900F',
    'JEOL (RDC) JEM F200','JEOL (RDC) JXA-8530F Plus','Leica Ultramicrotome (Inkson)',
    'TenuPol Electropolisher (Rainforth)','Zeiss EVO10','Zepto Plasma Cleaner (Rodenburg)',
    'Vibromet Polisher','Aconity Lab','Aconity Mini','Aconity Mini PC','BeAM','Desktop Metal Printer',
    'Freemelt One','RDC Sieving/Powder Handling Zone','RDC Workshop Modelling/Netfabb PC',
    'Resodyn Acoustic Mixer','Arcam Q10','Atomiser','Attrition Mill','Conform','Consarc VIM 25kg/ISM',
    'HIP AIP8-45H','Tekna Tek-15 Spheroidiser','Clemex microscope','Ecopress - IT','Labotom-20',
    'Linkam TS1200','Plastometrex PIP/ Hot PIP','Secotom-50 IT','Secotom-50 STAR','Struers Citovac',
    'Struers LaboForce-100','Struers Minitom','Tegramin-20 - IT','Tegramin-25 STAR','Arc Welder TMC',
    'Dilatometer','Hounsfield','TMC','Zwick Röell Z050','Zwick with Training'
);
