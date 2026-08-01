-- migrate:up
-- Refine the persisted UI theme: sleeker collection tables (clearer header rule,
-- bold first cell, calmer hover) alongside the card-based forms. Full custom_css replace.
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

/* Sleeker tabular collection view — matches the card theme */
.layout-tabular .v-table table { border-collapse: separate; border-spacing: 0; }
.layout-tabular .v-table .table-header {
	background: var(--theme--background-subdued, #f7f9fb);
	border-bottom: 2px solid var(--theme--border-color, #e2e8f0);
}
.layout-tabular .v-table .table-header .cell {
	text-transform: uppercase; letter-spacing: .06em; font-size: 10.5px; font-weight: 700;
	color: var(--theme--foreground-subdued, #7a8699);
}
.layout-tabular .v-table .table-row { transition: background-color .12s ease; }
.layout-tabular .v-table .table-row:hover { background: var(--theme--primary-background, #f0f4ff) !important; }
.layout-tabular .v-table .table-row > .cell { border-bottom: 1px solid var(--theme--border-color-subdued, #eef1f5); }
.layout-tabular .v-table .table-row > .cell:first-of-type { font-weight: 600; color: var(--theme--foreground, #1e293b); }
/* selection + hover checkboxes a touch calmer */
.layout-tabular .v-table .table-row.subdued { opacity: .6; }
';

-- migrate:down
-- (previous theme is restored by re-running migration 20260704000070)
