#!/usr/bin/env python3
"""Generate migration 62: Directus metadata for the people unification."""

owner_tables = ['physical_samples','manufacturing_operations','test_sessions','campaigns',
                'etchants','prep_recipes','tool_boxes','cutting_inserts','insert_edges']
operator_tables = ['manufacturing_operations','test_sessions']

L = []
def w(s=''): L.append(s)

w("-- migrate:up")
w("-- ① People unification, step 3 of 3: Directus metadata. Registers the people")
w("-- collection, wires the new owner/operator/PI person pickers to people, and hides")
w("-- the old backup columns (owner UUID→users, operator INT→Machine_Operators, PI).")
w("-- The researcher junctions (project_investigators, sample_co_owners) keep their")
w("-- user_id M2M for now; their backfilled person_id column is hidden.")
w("")
w("BEGIN;")
w("")
w("-- People collection ----------------------------------------------------------")
w("INSERT INTO directus_collections (collection, icon, note, display_template, hidden, sort)")
w("VALUES ('people', 'groups', 'Everyone attributed on records — operators, researchers, owners', '{{full_name}}', false, 3)")
w("ON CONFLICT (collection) DO NOTHING;")
w("")

# people own fields
people_fields = [
    # field, special, interface, options, display, width, sort, note
    ('full_name', None, 'input', None, 'raw', 'full', 1, None, True),
    ('email', None, 'input', None, 'raw', 'half', 2, None, False),
    ('user_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{first_name}} {{last_name}}","enableCreate":false}', 'related-values', 'half', 3, 'Linked app login (optional — operators need not have one)', False),
    ('is_operator', 'cast-boolean', 'boolean', None, 'boolean', 'half', 4, None, False),
    ('is_researcher', 'cast-boolean', 'boolean', None, 'boolean', 'half', 5, None, False),
    ('active', 'cast-boolean', 'boolean', None, 'boolean', 'half', 6, None, False),
    ('notes', None, 'input-multiline', None, 'raw', 'full', 7, None, False),
]
def sql_str(v):
    if v is None: return 'NULL'
    return "'" + str(v).replace("'", "''") + "'"

w("-- Idempotent: clear then insert people's own field metadata.")
w("DELETE FROM directus_fields WHERE collection='people';")
for field, special, interface, options, display, width, sort, note, required in people_fields:
    req = 'TRUE' if required else 'FALSE'
    w(f"INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, note) VALUES "
      f"('people', '{field}', {sql_str(special)}, '{interface}', {sql_str(options)}, '{display}', FALSE, FALSE, {sort}, '{width}', {req}, {sql_str(note)});")
# hide provenance columns on people
for field in ('legacy_machine_operator_id',):
    w(f"INSERT INTO directus_fields (collection, field, hidden, readonly, sort, note) VALUES ('people', '{field}', TRUE, TRUE, 90, 'Legacy Machine_Operators.id (provenance).');")

# people.user_id relation
w("")
w("-- people.user_id → directus_users relation")
w("INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)")
w("SELECT 'people','user_id','directus_users','nullify'")
w("WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='people' AND r.many_field='user_id');")
w("")

def person_m2o(collection, field, label, sort):
    opts = '{"template":"{{full_name}}","enableCreate":true}'
    disp = '{"template":"{{full_name}}"}'
    trans = '[{"language": "en-US", "translation": "%s"}]' % label
    w(f"INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES "
      f"('{collection}', '{field}', 'm2o', 'select-dropdown-m2o', '{opts}', 'related-values', '{disp}', FALSE, FALSE, {sort}, 'half', FALSE, '{trans}');")
    w(f"INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) "
      f"SELECT '{collection}','{field}','people','nullify' "
      f"WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='{collection}' AND r.many_field='{field}');")

w("-- New person pickers (owner / operator / PI) ---------------------------------")
w("DELETE FROM directus_fields WHERE field IN ('owner_person_id','operator_person_id','principal_investigator_person');")
for t in owner_tables:
    person_m2o(t, 'owner_person_id', 'Owner', 8)
for t in operator_tables:
    person_m2o(t, 'operator_person_id', 'Operator', 9)
person_m2o('projects', 'principal_investigator_person', 'Principal Investigator', 8)

w("")
w("-- Hide the old backup fields so users pick people, not users/operators --------")
# owner old fields
owner_pairs = ",".join(f"('{t}','owner')" for t in owner_tables)
w(f"UPDATE directus_fields SET hidden = TRUE WHERE (collection, field) IN ({owner_pairs});")
w("UPDATE directus_fields SET hidden = TRUE WHERE (collection, field) IN (('manufacturing_operations','operator'),('test_sessions','operator'),('projects','principal_investigator'));")
# hide junction person_id backfill columns (M2M stays on user_id for now)
w("INSERT INTO directus_fields (collection, field, hidden, readonly, note) VALUES ('project_investigators','person_id',TRUE,TRUE,'Backfilled people link; M2M UI uses user_id.') ON CONFLICT DO NOTHING;")
w("INSERT INTO directus_fields (collection, field, hidden, readonly, note) VALUES ('sample_co_owners','person_id',TRUE,TRUE,'Backfilled people link; M2M UI uses user_id.') ON CONFLICT DO NOTHING;")
w("")
w("COMMIT;")
w("")
w("-- migrate:down")
w("BEGIN;")
w("DELETE FROM directus_relations WHERE many_field IN ('owner_person_id','operator_person_id','principal_investigator_person') OR (many_collection='people' AND many_field='user_id');")
w("DELETE FROM directus_fields WHERE field IN ('owner_person_id','operator_person_id','principal_investigator_person');")
w("DELETE FROM directus_fields WHERE collection='people';")
w("DELETE FROM directus_collections WHERE collection='people';")
w(f"UPDATE directus_fields SET hidden = FALSE WHERE (collection, field) IN ({owner_pairs});")
w("UPDATE directus_fields SET hidden = FALSE WHERE (collection, field) IN (('manufacturing_operations','operator'),('test_sessions','operator'),('projects','principal_investigator'));")
w("DELETE FROM directus_fields WHERE (collection,field) IN (('project_investigators','person_id'),('sample_co_owners','person_id'));")
w("COMMIT;")

with open("db/migrations/20260703000062_people_directus_meta.sql","w",encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")
print("wrote migration 62:", len(L), "lines")
