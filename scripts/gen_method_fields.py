#!/usr/bin/env python3
"""Generate the ④b per-method test-field migrations (DB columns + Directus fields).

Emits two migration files following the existing inline-param pattern:
  * <ts>_test_method_fields.sql        -- ALTER TABLE ... ADD COLUMN
  * <ts>_test_method_fields_meta.sql   -- directus_fields inserts (conditional on test_type)

Field spec per method: (suffix, sqltype, interface, options|None, label, special|None)
Column name = "<method>_<suffix>".  Section comment marks results vs conditions.
"""

import json


# interface option helpers
def num(step, suffix=None):
    o = {"step": step}
    if suffix:
        o["suffix"] = suffix
    return o


def choices(*pairs):
    return {"choices": [{"text": t, "value": v} for t, v in pairs]}


# method -> (sort_base, [fields])
SPEC = {
    "tribology": (
        400,
        [
            (
                "test_standard",
                "TEXT",
                "input",
                None,
                "Test Standard (e.g. ASTM G99)",
                None,
            ),
            (
                "configuration",
                "TEXT",
                "select-dropdown",
                choices(
                    ("Pin-on-disc", "pin_on_disc"),
                    ("Ball-on-disc", "ball_on_disc"),
                    ("Reciprocating", "reciprocating"),
                    ("Block-on-ring", "block_on_ring"),
                    ("Other", "other"),
                ),
                "Configuration",
                None,
            ),
            (
                "counterface_material",
                "TEXT",
                "input",
                None,
                "Counterface Material",
                None,
            ),
            (
                "normal_load_n",
                "NUMERIC(10,3)",
                "input",
                num(0.1, "N"),
                "Normal Load",
                None,
            ),
            (
                "sliding_speed_m_per_s",
                "NUMERIC(10,4)",
                "input",
                num(0.001, "m/s"),
                "Sliding Speed",
                None,
            ),
            (
                "sliding_distance_m",
                "NUMERIC(12,3)",
                "input",
                num(0.1, "m"),
                "Sliding Distance",
                None,
            ),
            ("lubrication", "TEXT", "input", None, "Lubrication", None),
            (
                "test_temp_celsius",
                "NUMERIC(8,2)",
                "input",
                num(0.1, "°C"),
                "Test Temperature",
                None,
            ),
            (
                "coefficient_of_friction",
                "NUMERIC(8,4)",
                "input",
                num(0.0001),
                "Coefficient of Friction",
                None,
            ),  # result
            (
                "wear_rate_mm3_per_nm",
                "NUMERIC(14,8)",
                "input",
                num(0.00000001, "mm³/Nm"),
                "Specific Wear Rate",
                None,
            ),  # result
            (
                "wear_volume_mm3",
                "NUMERIC(12,6)",
                "input",
                num(0.000001, "mm³"),
                "Wear Volume",
                None,
            ),  # result
        ],
    ),
    "optical_microscopy": (
        420,
        [
            (
                "mode",
                "TEXT",
                "select-dropdown",
                choices(
                    ("Brightfield", "brightfield"),
                    ("Darkfield", "darkfield"),
                    ("DIC", "dic"),
                    ("Polarized", "polarized"),
                    ("Phase contrast", "phase_contrast"),
                    ("Other", "other"),
                ),
                "Illumination Mode",
                None,
            ),
            (
                "objective_magnification",
                "TEXT",
                "input",
                None,
                "Objective Magnification (e.g. 50x)",
                None,
            ),
            ("etchant", "TEXT", "input", None, "Etchant", None),
            ("etch_time_s", "NUMERIC(8,2)", "input", num(0.1, "s"), "Etch Time", None),
            (
                "image_scale_um_per_px",
                "NUMERIC(10,5)",
                "input",
                num(0.00001, "µm/px"),
                "Image Scale",
                None,
            ),
            (
                "notable_features",
                "TEXT",
                "input-multiline",
                None,
                "Notable Features",
                None,
            ),
        ],
    ),
    "tem": (
        440,
        [
            (
                "operating_voltage_kv",
                "NUMERIC(6,1)",
                "input",
                num(0.5, "kV"),
                "Operating Voltage",
                None,
            ),
            (
                "imaging_mode",
                "TEXT",
                "select-dropdown",
                choices(
                    ("Bright field", "BF"),
                    ("Dark field", "DF"),
                    ("HRTEM", "HRTEM"),
                    ("STEM", "STEM"),
                    ("Diffraction (SAD)", "SAD"),
                    ("EDS", "EDS"),
                    ("EELS", "EELS"),
                    ("Other", "other"),
                ),
                "Imaging Mode",
                None,
            ),
            (
                "camera_length_mm",
                "NUMERIC(8,2)",
                "input",
                num(0.1, "mm"),
                "Camera Length",
                None,
            ),
            (
                "specimen_prep",
                "TEXT",
                "select-dropdown",
                choices(
                    ("FIB lift-out", "fib"),
                    ("Electropolishing", "electropolish"),
                    ("Ion milling", "ion_mill"),
                    ("Ultramicrotomy", "ultramicrotome"),
                    ("Replica", "replica"),
                    ("Other", "other"),
                ),
                "Specimen Preparation",
                None,
            ),
            ("magnification_range", "TEXT", "input", None, "Magnification Range", None),
            (
                "notable_features",
                "TEXT",
                "input-multiline",
                None,
                "Notable Features",
                None,
            ),
        ],
    ),
    "alicona": (
        460,
        [
            (
                "objective_magnification",
                "TEXT",
                "input",
                None,
                "Objective Magnification",
                None,
            ),
            (
                "vertical_resolution_nm",
                "NUMERIC(10,2)",
                "input",
                num(0.1, "nm"),
                "Vertical Resolution",
                None,
            ),
            (
                "lateral_resolution_um",
                "NUMERIC(10,4)",
                "input",
                num(0.0001, "µm"),
                "Lateral Resolution",
                None,
            ),
            (
                "measured_area",
                "TEXT",
                "input",
                None,
                "Measured Area (e.g. 2×2 mm)",
                None,
            ),
            (
                "sa_um",
                "NUMERIC(10,4)",
                "input",
                num(0.0001, "µm"),
                "Sa (areal roughness)",
                None,
            ),  # result
            (
                "sz_um",
                "NUMERIC(10,4)",
                "input",
                num(0.0001, "µm"),
                "Sz (max height)",
                None,
            ),  # result
        ],
    ),
    "clemx": (
        480,
        [
            (
                "analysis_type",
                "TEXT",
                "select-dropdown",
                choices(
                    ("Grain size", "grain_size"),
                    ("Phase fraction", "phase_fraction"),
                    ("Porosity", "porosity"),
                    ("Inclusion rating", "inclusion"),
                    ("Other", "other"),
                ),
                "Analysis Type",
                None,
            ),
            (
                "objective_magnification",
                "TEXT",
                "input",
                None,
                "Objective Magnification",
                None,
            ),
            (
                "n_fields_analysed",
                "INTEGER",
                "input",
                num(1),
                "# Fields Analysed",
                None,
            ),
            ("etchant", "TEXT", "input", None, "Etchant", None),
            (
                "mean_grain_size_um",
                "NUMERIC(10,3)",
                "input",
                num(0.001, "µm"),
                "Mean Grain Size",
                None,
            ),  # result
            (
                "astm_grain_size_number",
                "NUMERIC(6,2)",
                "input",
                num(0.01),
                "ASTM Grain Size No.",
                None,
            ),  # result
            (
                "phase_fraction_pct",
                "NUMERIC(6,2)",
                "input",
                num(0.01, "%"),
                "Phase Fraction",
                None,
            ),  # result
        ],
    ),
    "dct": (
        500,
        [
            (
                "beam_energy_kev",
                "NUMERIC(8,2)",
                "input",
                num(0.1, "keV"),
                "Beam Energy",
                None,
            ),
            (
                "voxel_size_um",
                "NUMERIC(10,4)",
                "input",
                num(0.0001, "µm"),
                "Voxel Size",
                None,
            ),
            ("n_projections", "INTEGER", "input", num(1), "# Projections", None),
            (
                "scan_time_min",
                "NUMERIC(8,2)",
                "input",
                num(0.1, "min"),
                "Scan Time",
                None,
            ),
            (
                "n_grains_indexed",
                "INTEGER",
                "input",
                num(1),
                "# Grains Indexed",
                None,
            ),  # result
            (
                "notable_features",
                "TEXT",
                "input-multiline",
                None,
                "Notable Features",
                None,
            ),
        ],
    ),
    "ct_scan": (
        520,
        [
            (
                "tube_voltage_kv",
                "NUMERIC(8,2)",
                "input",
                num(0.1, "kV"),
                "Tube Voltage",
                None,
            ),
            (
                "tube_current_ua",
                "NUMERIC(10,2)",
                "input",
                num(0.1, "µA"),
                "Tube Current",
                None,
            ),
            (
                "voxel_size_um",
                "NUMERIC(10,4)",
                "input",
                num(0.0001, "µm"),
                "Voxel Size",
                None,
            ),
            ("n_projections", "INTEGER", "input", num(1), "# Projections", None),
            (
                "exposure_time_ms",
                "NUMERIC(10,2)",
                "input",
                num(0.1, "ms"),
                "Exposure Time",
                None,
            ),
            (
                "filter_material",
                "TEXT",
                "input",
                None,
                "Beam Filter (e.g. 0.5 mm Cu)",
                None,
            ),
            (
                "porosity_pct",
                "NUMERIC(8,4)",
                "input",
                num(0.0001, "%"),
                "Measured Porosity",
                None,
            ),  # result
            (
                "notable_features",
                "TEXT",
                "input-multiline",
                None,
                "Notable Features",
                None,
            ),
        ],
    ),
    "fatigue": (
        540,
        [
            (
                "loading_mode",
                "TEXT",
                "select-dropdown",
                choices(
                    ("Axial", "axial"),
                    ("Rotating bending", "rotating_bending"),
                    ("Three-point bending", "three_point_bending"),
                    ("Torsion", "torsion"),
                    ("Other", "other"),
                ),
                "Loading Mode",
                None,
            ),
            (
                "stress_ratio_r",
                "NUMERIC(6,3)",
                "input",
                num(0.001),
                "Stress Ratio (R)",
                None,
            ),
            (
                "max_stress_mpa",
                "NUMERIC(10,3)",
                "input",
                num(0.01, "MPa"),
                "Max Stress",
                None,
            ),
            (
                "stress_amplitude_mpa",
                "NUMERIC(10,3)",
                "input",
                num(0.01, "MPa"),
                "Stress Amplitude",
                None,
            ),
            (
                "frequency_hz",
                "NUMERIC(10,3)",
                "input",
                num(0.001, "Hz"),
                "Frequency",
                None,
            ),
            (
                "waveform",
                "TEXT",
                "select-dropdown",
                choices(
                    ("Sine", "sine"),
                    ("Triangle", "triangle"),
                    ("Square", "square"),
                    ("Other", "other"),
                ),
                "Waveform",
                None,
            ),
            (
                "test_temp_celsius",
                "NUMERIC(8,2)",
                "input",
                num(0.1, "°C"),
                "Test Temperature",
                None,
            ),
            (
                "cycles_to_failure",
                "BIGINT",
                "input",
                num(1),
                "Cycles to Failure",
                None,
            ),  # result
            (
                "runout",
                "BOOLEAN",
                "toggle",
                None,
                "Runout (no failure)?",
                "cast-boolean",
            ),  # result
        ],
    ),
    "creep": (
        560,
        [
            (
                "applied_stress_mpa",
                "NUMERIC(10,3)",
                "input",
                num(0.01, "MPa"),
                "Applied Stress",
                None,
            ),
            (
                "test_temp_celsius",
                "NUMERIC(8,2)",
                "input",
                num(0.1, "°C"),
                "Test Temperature",
                None,
            ),
            ("atmosphere", "TEXT", "input", None, "Atmosphere", None),
            (
                "time_to_rupture_h",
                "NUMERIC(12,3)",
                "input",
                num(0.001, "h"),
                "Time to Rupture",
                None,
            ),  # result
            (
                "steady_state_creep_rate_per_s",
                "NUMERIC(16,12)",
                "input",
                num(0.000000000001, "s⁻¹"),
                "Steady-State Creep Rate",
                None,
            ),  # result
            (
                "rupture_elongation_pct",
                "NUMERIC(8,3)",
                "input",
                num(0.001, "%"),
                "Elongation at Rupture",
                None,
            ),  # result
            (
                "reduction_of_area_pct",
                "NUMERIC(8,3)",
                "input",
                num(0.001, "%"),
                "Reduction of Area",
                None,
            ),  # result
        ],
    ),
    "dma": (
        580,
        [
            (
                "deformation_mode",
                "TEXT",
                "select-dropdown",
                choices(
                    ("Tension", "tension"),
                    ("Single cantilever", "single_cantilever"),
                    ("Dual cantilever", "dual_cantilever"),
                    ("Three-point bending", "three_point_bending"),
                    ("Shear", "shear"),
                    ("Compression", "compression"),
                    ("Other", "other"),
                ),
                "Deformation Mode",
                None,
            ),
            (
                "frequency_hz",
                "NUMERIC(10,3)",
                "input",
                num(0.001, "Hz"),
                "Frequency",
                None,
            ),
            (
                "temperature_range",
                "TEXT",
                "input",
                None,
                "Temperature Range (e.g. −50–300°C)",
                None,
            ),
            (
                "heating_rate_c_per_min",
                "NUMERIC(8,3)",
                "input",
                num(0.001, "°C/min"),
                "Heating Rate",
                None,
            ),
            (
                "amplitude_um",
                "NUMERIC(10,3)",
                "input",
                num(0.001, "µm"),
                "Displacement Amplitude",
                None,
            ),
            (
                "storage_modulus_mpa",
                "NUMERIC(12,3)",
                "input",
                num(0.001, "MPa"),
                "Storage Modulus (E')",
                None,
            ),  # result
            (
                "loss_modulus_mpa",
                "NUMERIC(12,3)",
                "input",
                num(0.001, "MPa"),
                "Loss Modulus (E'')",
                None,
            ),  # result
            (
                "tan_delta",
                "NUMERIC(10,5)",
                "input",
                num(0.00001),
                "tan δ",
                None,
            ),  # result
            (
                "glass_transition_celsius",
                "NUMERIC(8,2)",
                "input",
                num(0.01, "°C"),
                "Glass Transition (Tg)",
                None,
            ),  # result
        ],
    ),
}

TS = "20260703000058"
COLS = []
META = []
all_methods = list(SPEC.keys())

for method, (base, fields) in SPEC.items():
    COLS.append(f"\n-- {method}")
    META.append(
        f"\n-- ── {method} → test_sessions (inline, shows when test_type={method}) ──"
    )
    for i, (suffix, sqltype, interface, options, label, special) in enumerate(fields):
        col = f"{method}_{suffix}"
        COLS.append(
            f"ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS {col} {sqltype};"
        )
        opt_sql = (
            "NULL"
            if options is None
            else "'" + json.dumps(options).replace("'", "''") + "'"
        )
        spec_sql = "NULL" if special is None else f"'{special}'"
        display = "boolean" if interface == "toggle" else "raw"
        width = "full" if interface == "input-multiline" else "half"
        label_esc = label.replace("'", "''")
        trans = json.dumps([{"language": "en-US", "translation": label}])
        trans_sql = "'" + trans.replace("'", "''") + "'"
        cond = json.dumps(
            [
                {
                    "name": f"show when {method}",
                    "rule": {"_and": [{"test_type": {"_eq": method}}]},
                    "hidden": False,
                    "readonly": False,
                    "required": False,
                }
            ]
        )
        cond_sql = "'" + cond.replace("'", "''") + "'"
        sort = base + i
        META.append(
            "INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations, note, conditions) VALUES "
            f"('test_sessions', '{col}', {spec_sql}, '{interface}', {opt_sql}, '{display}', NULL, FALSE, TRUE, {sort}, '{width}', FALSE, {trans_sql}, NULL, {cond_sql});"
        )

# Write columns migration
prefixes = " OR ".join([f"field LIKE '{m}\\_%'" for m in all_methods])
cols_down = []
for method, (base, fields) in SPEC.items():
    for suffix, *_ in fields:
        cols_down.append(
            f"ALTER TABLE test_sessions DROP COLUMN IF EXISTS {method}_{suffix};"
        )

with open(
    "db/migrations/20260703000058_test_method_fields.sql", "w", encoding="utf-8"
) as f:
    f.write("-- migrate:up\n")
    f.write(
        "-- ④b Per-method inline parameter columns for the test methods that lacked them:\n"
    )
    f.write(
        "-- tribology, optical_microscopy, tem, alicona, clemx, dct, ct_scan, fatigue, creep, dma.\n"
    )
    f.write(
        "-- Setup + result fields, chosen from the standard settings each method records.\n"
    )
    f.write(
        "-- test_type already permits all of these (migration 20260624000033); no CHECK change.\n"
    )
    f.write("\n".join(COLS))
    f.write("\n\n-- migrate:down\n")
    f.write("\n".join(reversed(cols_down)))
    f.write("\n")

with open(
    "db/migrations/20260703000059_test_method_fields_meta.sql", "w", encoding="utf-8"
) as f:
    f.write("-- migrate:up\n")
    f.write(
        "-- Directus field metadata for the ④b per-method test fields. Conditional on\n"
    )
    f.write(
        "-- test_type so each method's panel appears only for that test. Idempotent: clears\n"
    )
    f.write(
        "-- any previously-inserted rows for these prefixes before re-inserting.\n\n"
    )
    f.write("BEGIN;\n\n")
    f.write(
        f"DELETE FROM directus_fields WHERE collection='test_sessions' AND ({prefixes});\n"
    )
    f.write("\n".join(META))
    f.write("\n\nCOMMIT;\n")
    f.write("\n-- migrate:down\n")
    f.write(
        f"DELETE FROM directus_fields WHERE collection='test_sessions' AND ({prefixes});\n"
    )

n_cols = sum(len(v[1]) for v in SPEC.values())
print(f"wrote 58 ({n_cols} cols) and 59 ({n_cols} fields)")
