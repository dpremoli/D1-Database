-- migrate:up
-- Backfill equipment.image_url for the flagship instruments with a manufacturer /
-- product-page photo. Each URL was verified to return image content (HTTP 200,
-- Content-Type image/*). Only machines with a confident, model-correct match are set;
-- the rest stay NULL for manual fill. Idempotent (keyed on equipment_name).

UPDATE equipment SET image_url = v.url FROM (VALUES
    ('JEOL (RDC) JEM F200',       'https://www.jeol.com/products/assets/images/JEM-F200_en.png'),
    ('JEOL (RDC) JEM 7900F',      'https://www.jeol.com/products/assets/images/JSM-7900F_en.jpg'),
    ('JEOL (RDC) JXA-8530F Plus', 'https://www.jeol.com/products/assets/images/JXA-8530FPlus_en.jpg'),
    ('Aconity Mini',              'https://www.aniwaa.com/wp-content/uploads/2023/09/AconityMINI_Clear_Photo_compressed-300x200.png'),
    ('Freemelt One',              'https://freemelt.com/app/uploads/Freemelt-ONE-1.png'),
    ('Zwick Röell Z050',          'https://www.zwickroell.com/zrmedia/Images/2/CTA201541_TVM1414449.png'),
    ('Zwick with Training',       'https://www.zwickroell.com/zrmedia/Images/2/CTA201541_TVM1414449.png'),
    ('Tegramin-20 - IT',          'https://webshopcms.struers.com/media/1qxplwiw/tegramin-30-with-suspensions-from-side-frit-1024x665-px-new.png'),
    ('Tegramin-25 STAR',          'https://webshopcms.struers.com/media/1qxplwiw/tegramin-30-with-suspensions-from-side-frit-1024x665-px-new.png'),
    ('Secotom-50 IT',             'https://webshopcms.struers.com/media/0sbiqrdn/top-1024x665px-5.png'),
    ('Secotom-50 STAR',           'https://webshopcms.struers.com/media/0sbiqrdn/top-1024x665px-5.png'),
    ('Labotom-20',                'https://webshopcms.struers.com/media/bmtd5j31/top5-cutting-1024x665px.jpg')
) AS v(name, url)
WHERE equipment.equipment_name = v.name;

-- Show image_url as a URL field on the equipment form (the file `image` field is
-- for uploads).
INSERT INTO directus_fields (collection, field, interface, options, display, width, sort, note)
SELECT 'equipment','image_url','input','{"type":"url"}','raw','full',7,
       'External photo URL (manufacturer/product page). The image file field is for uploads.'
WHERE NOT EXISTS (SELECT 1 FROM directus_fields WHERE collection='equipment' AND field='image_url');

-- migrate:down
DELETE FROM directus_fields WHERE collection='equipment' AND field='image_url';
UPDATE equipment SET image_url = NULL WHERE equipment_name IN (
    'JEOL (RDC) JEM F200','JEOL (RDC) JEM 7900F','JEOL (RDC) JXA-8530F Plus','Aconity Mini',
    'Freemelt One','Zwick Röell Z050','Zwick with Training','Tegramin-20 - IT','Tegramin-25 STAR',
    'Secotom-50 IT','Secotom-50 STAR','Labotom-20'
);
