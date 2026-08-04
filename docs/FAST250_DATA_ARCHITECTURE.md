# FAST 250 Machine Data Architecture

**Status:** Manual Export Format  
**Date:** 2026-07-22  
**Source:** FAST 250 CSV exports + Recipe files  
**Data Volume:** 331 runs (2020-2026), 100+ recipes, 175 months of timeseries data  
**Format:** CSV (timeseries) + RCP (recipe definitions)

---

## Overview

The FAST 250 sintering apparatus maintains two data sources:

1. **Run Data (CSV)** — Exported timeseries measurements (~1M rows per run)
2. **Recipe Definitions (RCP)** — Recipe parameters and segments (~100+ files)

Unlike FAST 25 (which has a database backend), FAST 250 data comes from **manual machine exports**. Each run generates:
- **One CSV file** containing all measurement columns (30+ parameters) sampled once per second
- **A recipe reference** linking to an `.rcp` file with program parameters

This document specifies the data model, file formats, and import strategy.

---

## 1. Run Data (CSV Files)

**File Location:** `FAST 250/CSV/YYYY-MM/RUN_NO_DD-MM-YYYY_HHMMSS.csv` (331 total)

**Period:** 2020-02 to 2026-07 (55+ months with gaps)

**Format:** Tab-delimited / Semicolon-delimited with comma as decimal separator (German locale)

### File Structure

**Line 1: Machine Info**
```
Plant: 8649 UOS
```

**Line 2: Recipe Reference**
```
Used Recipe: D105_IN718_Briq_1125_35MPa_30m.rcp
```

**Line 3: Start Time**
```
StartTime Charge:07.07.2026 13:38:52
```

**Line 4: Column Header**
```
Cur. Time Charge;Prozesstime 1;Prozesstime 2;Segment-No.;Technol. Step;Pyro top [°C];Pyro front [°C];
Piston TC upper ram [°C];Piston TC contact area [°C];Piston TC cooling ram [°C];Control TC 1 [°C];
SV SPS heating temp. [°C];Y SPS heating temp. [%];PWS SPS heating [%];Absolute pressure vessel [mbar(a)];...
```

**Lines 5+: Data Rows**
```
07.07.2026 13:38:52;00:00:01;0,0003;1;Standby;250,7;253,1;24,6;25,2;24,7;24,1;0,0;0,0;0,0;1.013,1;...
07.07.2026 13:38:53;00:00:02;0,0006;1;Standby;250,7;253,1;24,6;25,2;24,7;24,1;0,0;0,0;0,0;1.013,3;...
```

### Column Definitions

| Column # | Name | Unit | Description |
|----------|------|------|-------------|
| 1 | Cur. Time Charge | HH:MM:SS | Current timestamp (absolute) |
| 2 | Prozesstime 1 | s | Process elapsed time |
| 3 | Prozesstime 2 | decimal | Process time fraction (varies) |
| 4 | Segment-No. | — | Program segment number |
| 5 | Technol. Step | text | Step name (Standby, Vacuum, Heating, Pressing, etc.) |
| 6-11 | Temperature (Pyro/TC) | °C | Pyrometer top, front; Thermocouple positions |
| 12-14 | SPS Heating | °C, %, % | Setpoint, output, power |
| 15-20 | Pressure (Vessel) | mbar | Absolute, vacuum, setpoint, output |
| 21-27 | Pressure (Cooling) | mbar | Cooling vessel pressures |
| 28-31 | Pressing Force | kN, mm, mm/min | Setpoint, actual, displacement, speed |
| 32-34 | Hydraulics | °C, kW, V, kA | Oil temp, power, voltage, current |
| 35-36 | Gas Flow | l/min | Process gas, pyro flushing |
| 37-38 | Cooling Water | °C, µS/cm | Inlet temp, conductance |

**Total: ~40 columns per run**

### Data Characteristics

- **Sampling Rate:** 1 Hz (one row per second)
- **Run Duration:** 30 minutes to 5+ hours
- **Rows per Run:** 1,800 to 18,000+ (typical: 5,000-10,000)
- **File Size:** 300 KB to 5 MB per run
- **Decimal Separator:** Comma (German locale)
- **Thousand Separator:** Period (1.013,1 = 1013.1)

### Example Run Metadata (from Filename)

```
328_07-07-2026_133852.csv
│   │  │  │     │
│   │  │  │     └─ Start time: 13:38:52
│   │  │  └─ Run date: 07-07-2026
│   │  └─ Month: 07 (July)
│   └─ Day: 07
└─ Run ID: 328
```

---

## 2. Recipe Definitions (RCP Files)

**File Location:** `FAST 250/PROGS/*.rcp` (100+ total)

**Format:** ASCII text, semicolon-delimited

### File Structure

The `.rcp` file contains program segments, each defining a process step.

**Example Content:**
```
1;5;0;0;1;0;0;260;0;1;0;1;0;1;0;0;0;20;1;0;0;0;1;5;0;30;10
2;600;2;0;1;0;16777216;260;0;1;0;1;0;1;0;0;0;20;1;0;0;0;1;5;0;30;10
3;120;3;0;1;0;67108866;260;0;1;0;1;0;1;0;0;0;20;1;0;0;0;1;5;0;245;80
4;5400;4;0;1;0;1141473282;300;70;1;0;15;5;1;0;0;0;20;1;0;0;0;1;5;0;245;100
5;1920;4;0;1;0;604078082;1100;280;0,85;0;15;5;1;0;0;0;20;1;0;0;0;1;5;0;1720;140
```

### Structure

**Fields per segment:**
- Field 1: Segment number
- Field 2: Duration (seconds)
- Field 3: Type/Mode code
- Field 4-7: Control flags
- Field 8-9: Temperature setpoints (°C)
- Field 10+: Pressure, force, gas flow, etc.

**Total: 26-27 fields per segment**

### Recipe Naming Convention

Recipes follow a pattern revealing the experiment:

```
D105_IN718_Briq_1075_35MPa_40mins.rcp
│     │     │    │    │    │
│     │     │    │    │    └─ Hold time
│     │     │    │    └─ Target load/pressure
│     │     │    └─ Temperature
│     │     └─ Material form (Briq = Briquette)
│     └─ Alloy composition
└─ Device/variant

AT_D250_Ti-6-4-SWARF_1100°C_35MPa_30m_25°min.rcp
  └─ Another variant with heating rate specified
```

**Common Materials:** IN718, IN625, RR1000, Ti-64, Ni-690, etc.

---

## 3. Metadata & Exports

### Export Files (Root Level)

**Files:** `export_DD-MM-YYYY-HH-MM-SS.csv` and `export_DD-MM-YYYY-HH-MM-SS.xls`

**Purpose:** Summary exports or run lists (metadata)

**Contents:** Likely a summary of recent runs with key parameters

---

## Data Relationships

```
Recipe Files (PROGS/)
    └─ Referenced by CSV header (Line 2)
    └─ Links to specific run experiment parameters

Run Data (CSV/YYYY-MM/)
    └─ One file per run
    └─ Named: RUN_ID_DD-MM-YYYY_HHMMSS.csv
    └─ Contains: Timeseries measurements (30+ columns, 1Hz)
    └─ Duration: 30 mins to 5+ hours
    └─ ~1-5MB per file
```

**Import Strategy:**
1. Parse recipe files to extract experiment parameters
2. Parse CSV files to extract:
   - Run ID and timestamps (from filename and Line 3)
   - Measurement data (timeseries columns)
   - Recipe reference (from Line 2)
3. Link run to recipe via filename pattern

---

## Database Schema (Directus/PostgreSQL)

### Runs Table

```sql
CREATE TABLE runs (
  id UUID PRIMARY KEY,
  run_id INTEGER UNIQUE,  -- Extracted from filename (328, 329, etc.)
  machine VARCHAR(20),    -- "FAST 250"
  start_datetime TIMESTAMP,  -- From filename date/time
  end_datetime TIMESTAMP,  -- Calculated from duration
  recipe_name VARCHAR(255),  -- From CSV line 2
  plant_code VARCHAR(50),  -- "8649 UOS" from Line 1
  
  -- File reference
  csv_file_path VARCHAR(255),
  
  -- Metadata
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  
  FOREIGN KEY (recipe_name) REFERENCES recipes(name)
);
```

### Recipes Table

```sql
CREATE TABLE recipes (
  id UUID PRIMARY KEY,
  name VARCHAR(255) UNIQUE,  -- Filename without .rcp
  material VARCHAR(100),    -- Material code (IN718, Ti-64, etc.)
  temperature_c INTEGER,    -- Target temperature
  pressure_mpa INTEGER,     -- Target pressure/load
  hold_time_minutes INTEGER,  -- Hold duration
  description TEXT,         -- Extracted description
  
  -- File reference
  rcp_file_path VARCHAR(255),
  
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### Measurements Table

```sql
CREATE TABLE measurements (
  id BIGSERIAL PRIMARY KEY,
  run_id INTEGER FOREIGN KEY,
  timestamp TIMESTAMP,  -- Absolute time from CSV
  process_time_s FLOAT,  -- Elapsed process time
  segment_no INTEGER,   -- Program segment
  technol_step VARCHAR(50),  -- Step name
  
  -- Temperatures
  pyro_top_c FLOAT,
  pyro_front_c FLOAT,
  piston_tc_upper_c FLOAT,
  piston_tc_contact_c FLOAT,
  piston_tc_cooling_c FLOAT,
  control_tc1_c FLOAT,
  
  -- Heating system
  sv_sps_heating_c FLOAT,
  y_sps_heating_pct FLOAT,
  pws_sps_heating_pct FLOAT,
  
  -- Vessel pressures
  abs_pressure_vessel_mbar FLOAT,
  vacuum_vessel_mbar FLOAT,
  sv_vacuum_vessel_mbar FLOAT,
  y_vacuum_vessel_pct FLOAT,
  rel_pressure_vessel_mbar FLOAT,
  sv_rel_pressure_mbar FLOAT,
  y_rel_pressure_pct FLOAT,
  
  -- Cooling vessel
  abs_pressure_cooling_mbar FLOAT,
  rel_pressure_cooling_mbar FLOAT,
  
  -- Pressing force
  sv_pressing_force_kn FLOAT,
  av_pressing_force_kn FLOAT,
  pressing_max_way_mm FLOAT,
  pressing_relative_way_mm FLOAT,
  pressing_speed_mm_per_min FLOAT,
  
  -- Power & hydraulics
  hydraulic_oil_temp_c FLOAT,
  sps_power_kw FLOAT,
  sps_voltage_v FLOAT,
  sps_current_ka FLOAT,
  
  -- Gas flow
  mfc_process_gas_l_per_min FLOAT,
  mfc_pyro_flushing_l_per_min FLOAT,
  
  -- Cooling water
  cw_inlet_temp_c FLOAT,
  cw_inlet_conductance_us_cm FLOAT
);
```

---

## Import Strategy

### Phase 1: Core Data (Essential)

**Time:** ~1-2 hours for all 331 runs

1. **Parse Recipe Files** (`PROGS/*.rcp`)
   - Extract recipe names
   - Parse segment parameters
   - Store in Recipes table

2. **Parse CSV Files** (`CSV/YYYY-MM/*.csv`)
   - Extract run ID from filename
   - Parse header (Lines 1-3)
   - Parse measurement data (Lines 5+)
   - Convert German locale (comma → period for decimals)
   - Calculate timestamps
   - Store in Runs and Measurements tables

3. **Link Runs to Recipes**
   - Match CSV line 2 ("Used Recipe: ...") to Recipes table

### Phase 2: Validation (Recommended)

1. Cross-check run counts across months
2. Identify any corrupted or incomplete CSV files
3. Validate timestamp continuity

### Phase 3: Analytics (Optional)

1. Compute summary statistics (peak temps, pressures, duration)
2. Flag anomalous runs (outliers in temperature/pressure profiles)
3. Extract material + temperature combinations for dashboards

---

## Import Benchmarks

```
Operation                  Time        Data Volume
─────────────────────────────────────────────────
Parse 100+ recipe files    ~1s         100 KB
Parse 331 CSV files        ~5-10min    ~500 MB
Convert German locale      (included)  —
Insert into PostgreSQL     ~2-3min     (via bulk insert)
─────────────────────────────────────────────────
Total (cold import)        ~10-15 min
Incremental (1 new run)    ~2-3s
```

---

## Specifics for Directus Integration

### Collection Setup

**runs** collection:
- `run_id` (integer, unique)
- `machine` (string, filter)
- `start_datetime` (date time)
- `recipe` (many-to-one relationship → recipes)
- `csv_file_path` (string)

**recipes** collection:
- `name` (string, unique)
- `material` (string, filter)
- `temperature_c` (integer, filter)
- `pressure_mpa` (integer, filter)
- `rcp_file_path` (string)

**measurements** collection:
- `run_id` (many-to-one relationship → runs)
- `timestamp` (date time, sortable)
- `segment_no` (integer)
- `technol_step` (string)
- `[40+ measurement columns]` (float, filterable)

**Index Strategy:**
- `measurements.run_id` + `timestamp` (composite, for time-range queries)
- `runs.start_datetime` (for filtering by month)
- `recipes.material`, `.temperature_c` (for filtering)

---

## Data Quirks & Gotchas

### 1. German Locale Encoding

**Problem:** CSV files use comma as decimal separator and period as thousand separator.

**Example:**
```
1.013,1 means 1013.1 (not 1,013.1 in US format)
1.720 means 1720 (or 1,720 in US format)
```

**Solution:** Use pandas with `decimal=','` parameter or manually replace during parsing.

### 2. Timestamp Format

**In Filename:** `DD-MM-YYYY_HHMMSS`
**In CSV Line 3:** `DD.MM.YYYY HH:MM:SS`

Convert both to ISO 8601 (YYYY-MM-DD HH:MM:SS) for storage.

### 3. Segment Numbers & Technol. Steps

Some runs have 4-8 segments. Segment transitions visible in data (Standby → Vacuum → Heating → Pressing → Cooling, etc.).

### 4. Missing/Sparse Data

Some months have gaps (no runs exported). Directory structure exists but no CSV files.

### 5. Variable Column Count

Different export versions may have 35-40 columns. Parse header dynamically rather than assuming fixed column positions.

---

## Directus Dashboard Ideas

### Run Explorer

- **Filters:** Material, Temperature, Pressure, Date range
- **Columns:** Run ID, Date, Material, Max Temp, Max Force, Duration
- **Action:** Click → View timeseries plot

### Timeseries Plot

- **X-axis:** Process time (seconds)
- **Y-axis:** Temperature (selectable: Pyro top, Pyro front, TC positions)
- **Second axis:** Force (kN)
- **Highlights:** Segment transitions (colored regions)

### Recipe Catalog

- **Table:** List all recipes
- **Columns:** Name, Material, Temp, Pressure, Hold Time
- **Filter:** By material or temp range

### Material Summary

- **Dashboard:** Group runs by material
- **Metrics:** Count, avg temp, avg force, date range
- **Trends:** How many IN718 runs per month?

---

## Next Steps

1. Implement importer (Python script: `ingest_fast250.py`)
2. Create Directus collections and schema
3. Build timeseries plotting API
4. Test on 10 sample runs first, then full 331 runs
5. Set up periodic sync (if machine adds new exports)

---

## References

- [FAST250_FILE_READING_GUIDE.md](./FAST250_FILE_READING_GUIDE.md) — Code examples
- [FAST25_DATA_ARCHITECTURE.md](./FAST25_DATA_ARCHITECTURE.md) — FAST 25 reference (similar but database-backed)
- [FAST25_OVERVIEW.md](./FAST25_OVERVIEW.md) — Multi-machine overview
