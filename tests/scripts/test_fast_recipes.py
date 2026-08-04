import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import fast_recipes as fr


def test_program_nr_from_bezeichnung():
    assert fr.program_nr_from_bezeichnung("Ti-64 1200C  100/min / 1248") == 1248
    assert fr.program_nr_from_bezeichnung("STAR_CIPFAST_0.5_1325 / 2793") == 2793
    assert fr.program_nr_from_bezeichnung("no trailing number") is None
    assert fr.program_nr_from_bezeichnung(None) is None


def test_rezept_targets_uses_offset_by_one():
    # Rezept.Daten[N+1] <-> Kopfdaten.Nr = N. Real values from recipe 1248.
    daten = [
        "",
        "Affaan",
        "1200",
        "Ti64-20V",
        "44kN",
        "vac",
        "pyro",
        "40mm",
        "42 g",
        "20 min holding",
    ] + [""] * 10
    t = fr.rezept_targets(daten)
    assert t["target_temp_c"] == 1200
    assert t["target_force_kn"] == 44
    assert t["hold_time_min"] == 20


def test_rezept_targets_omits_absent_values():
    daten = [""] * 20
    assert fr.rezept_targets(daten) == {}


def test_rcp_targets_from_name():
    t = fr.rcp_targets_from_name("D105_IN718_Briq_1125_35MPa_30mins")
    assert t["target_temp_c"] == 1125
    assert t["hold_time_min"] == 30


def test_recipe_id_is_deterministic_and_machine_scoped():
    a = fr.recipe_id("25", 1248, "Ti64")
    assert a == fr.recipe_id("25", 1248, "different name")  # 25 keyed by program_nr
    b = fr.recipe_id("250", None, "D105_IN718")
    assert b == fr.recipe_id("250", None, "d105_in718")  # 250 keyed by lower(name)
    assert a != b


def test_first_num():
    assert fr.first_num("13 kN") == 13
    assert fr.first_num("1325C") == 1325
    assert fr.first_num("") is None
    assert fr.first_num(None) is None
