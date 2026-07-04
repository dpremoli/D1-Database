-- migrate:up
-- Persist the STARbase UI theme (warm card-based item forms + sleeker collection
-- tables) as config. Restyles Directus via custom_css; no structural change.
UPDATE directus_settings SET custom_css = '/* ── STARbase theme: warm card-based forms + sleeker tables ─────────────── */

/* Item forms: each field as a soft card with a bold label */
.v-form { --theme--form--row-gap: 22px; --theme--form--column-gap: 20px; }
.v-form .field {
	background: #fff;
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 12px;
	padding: 14px 16px 16px;
	box-shadow: 0 1px 3px rgba(15, 23, 42, .04);
}
.v-form .field > .field-label .type-label,
.v-form .field .type-label { font-size: 13.5px; font-weight: 700; letter-spacing: .005em; }
.v-form .field .v-input,
.v-form .field .v-select,
.v-form .field .v-textarea { --theme--border-radius: 10px; }
/* headings/dividers should not look like input cards */
.v-form .field.full > .v-divider { margin-top: 4px; }

/* Sleeker tabular collection view */
.layout-tabular .v-table .table-header { background: var(--theme--background-subdued, #f7f9fb); }
.layout-tabular .v-table .table-header .cell {
	text-transform: uppercase; letter-spacing: .05em; font-size: 10.5px; font-weight: 700;
	color: var(--theme--foreground-subdued, #7a8699);
}
.layout-tabular .v-table .table-row { transition: background .12s ease; }
.layout-tabular .v-table .table-row:hover { background: var(--theme--primary-background, #f0f4ff) !important; }
.layout-tabular .v-table .cell { border-bottom: 1px solid var(--theme--border-color-subdued, #eef1f5); }
.layout-tabular .v-table .table-row > .cell:first-child { font-weight: 600; }
';

-- migrate:down
UPDATE directus_settings SET custom_css = NULL;
