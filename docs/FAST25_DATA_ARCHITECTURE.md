# FAST 25 Machine Data Architecture

**Status:** Discovered & Documented  
**Date:** 2026-07-22  
**Source:** Complete reverse-engineering of FAST 25 ECS2000 system  
**Data Volume:** 9,735 runs (2010-2026), 4,995 recipes, 10,193 measurement archives

---

## Overview

The FAST 25 sintering apparatus maintains three interconnected data sources:
1. **Run History Database** (ECS_Analysis.MDB) — 9,735 complete experiment records
2. **Recipe Master Database** (ECS_Prog.mdb) — 4,995 recipe definitions  
3. **Measurement Archives** (10,193 EMD/REZ ZIP files) — Binary timeseries & events
4. **QA Logs** (Excel 2022-2026) — 1,888 selective samples for compliance
5. **System Configuration** (Multiple MDB databases) — Instruments, alarms, parameters

This document specifies the complete data model, file formats, and import strategy.

---

## 1. Run History Database (ECS_Analysis.MDB)

**File Location:** `ECS2000/Data/ECS_Analysis.MDB` (6.4 MB)

**Tables:**
- `Versuch` (9,735 rows) — Primary run records
- `DataCaption` (1 row) — Column definitions (legend)
- `Refresh` (1 row) — UpdateCounter (17,262) for incremental polling
- `Filter`, `DailyFilter` (empty) — Unused

### Versuch Table Schema

| Column | Type | Example | Purpose |
|--------|------|---------|---------|
| **VersuchNr** | Integer | 4926, 8738 | Run ID (sequential) |
| **StartDate** | DateTime | 2017-06-09 | Run start date |
| **StartTime** | DateTime | 1899-12-30 13:33:42 | Run start time (epoch date, use time part only) |
| **EndDate** | DateTime | 2017-06-09 | Run end date |
| **EndTime** | DateTime | 1899-12-30 14:10:41 | Run end time (epoch date, use time part only) |
| **Operator** | String | "1200", "Nick", "UOS" | Operator code or name |
| **Finished** | Boolean | True/False | Completion flag |
| **Alarm** | Integer | 1 or 2 | 1=alarm, 2=critical alarm |
| **FileName** | String | "Batch\2017\06\V01_4926_090617" | Path to EMD archive (relative to Data/) |
| **Daten1-20** | String | Various | Parameter values (see DataCaption for meanings) |
| **Bezeichnung** | String | "Ti-64 1200°C 100/min / 1248" | Run description/title |
| **Bemerkung** | String | Comments | Notes/remarks |
| **ChargenOID** | GUID | — | Charge/batch identifier |
| **UnitOID** | GUID | — | Machine unit identifier |
| **ChargeTyp** | Integer | 0 | Charge type code |
| **ReplicationID** | Integer | 5433 | Replication/iteration ID |
| **ChargenMID** | GUID | — | Material/sample identifier |
| **DeviceLoggerNo** | Integer | 0 or 1 | Logger device number |
| **AnlagenLabel** | String | "HPD 25" | Machine name |
| **DeviceBatchID** | String | "593AA3B6.010" | Device batch identifier |

### DataCaption Table (Legend)

Defines what Daten1-20 columns mean:

```
Daten1:  Operator (or empty for this setup)
Daten2:  Temperature (°C)
Daten3:  Material
Daten4:  Force (kN)
Daten5:  Gas/Vacuum
Daten6:  Pyro/TC
Daten7:  Tool size (mm)
Daten8:  Batch No.
Daten9:  Mass (g)
Daten10-20: Custom per recipe
```

### UpdateCounter (Refresh Table)

Used for incremental sync. Current value: 17,262

**Strategy:** Poll UpdateCounter; if changed, fetch new runs since last sync.

---

## 2. Recipe Master Database (ECS_Prog.mdb)

**File Location:** `ECS2000/Recipes/1001/ECS_Prog.mdb` (13 MB)

**Tables:**
- `Rezept` (4,995 rows) — Recipe definitions
- `Kopfdaten` (55,700 rows) — Field schemas per recipe
- `DataCaption` (1 row) — Column legend (same structure as Analysis DB)

### Rezept Table Schema

| Column | Type | Example |
|--------|------|---------|
| **ProgrammNr** | Integer | 2341 |
| **ProgrammText** | String | "NSW_40mm_La2Si2O7_1600-50MPa-30m" |
| **GroupName** | String | "HPD 25" |
| **FileName** | String | "R_HPD 25_00002341" |
| **DateCreate** | DateTime | 2024-01-08 |
| **DateChange** | DateTime | 2024-01-08 |
| **Daten1-20** | String | Parameter values |
| **Locked** | Boolean | Read-only flag |
| **ConfigIsOk** | Boolean | Validation status |
| **Bemerkung** | String | Comments |

### Kopfdaten Table (Field Definitions)

Maps recipe fields to human-readable names:

```
ProgrammNr | Anlage | Nr | Bezeichnung | Format | Einheit | EingabeMin | EingabeMax
2341       | 1      | 1  | Operator    | ###0.0 |         | 0.0        | 100.0
2341       | 1      | 2  | Temperature | ###0.0 |         | 0.0        | 2500.0
2341       | 1      | 3  | Material    | ###0.0 |         | 0.0        | 100.0
...
```

---

## 3. Measurement Archives (EMD Files)

**File Location:** `ECS2000/Data/Batch/YYYY/MM/V01_XXXXX_DDMMYY.EMD` (10,193 total)

**Format:** ZIP archives containing:

### Contents Example (V01_10632_090426.EMD):
```
├── V01_10632_090426.HIS    (925 KB) - Timeseries measurements (binary)
├── V01_10632_090426.ERG    (1.9 KB) - Event/error log (text + binary)
├── V01_10632_090426.MIN    (3.4 KB) - Duration/minutes data
├── V01_10632_090426.MKD    (2.4 KB) - Marker data
├── V01_10632_090426.MPS    (606 B)  - Parameters/settings
├── V01_10632_090426.SPC    (929 B)  - Specification
├── V01_10632_090426.MMW    (6.5 KB) - Measurement windows
└── V01_10632_090426.LTR    (555 B)  - Labels/text
```

### .HIS File (Timeseries)

**Format:** IEEE 754 floating-point measurements

```
Bytes 0-3:    Header (01 00 23 00)
Bytes 4+:     Float32 values (little-endian)
```

**Structure (inferred):** Repeating records with measurement values at regular intervals

**Reading:**
```python
import numpy as np
from zipfile import ZipFile

with ZipFile("V01_10632_090426.EMD") as zf:
    his_data = np.frombuffer(zf.read("V01_10632_090426.HIS")[4:], dtype=np.float32)
```

### .ERG File (Event Log)

**Format:** Binary header + text events

**Sample content:**
```
Communication error
02/04/2026 12:14:38
System 1
Start logging
09/04/2026 11:16:20
Segment 1 - Start Vacuum
09/04/2026 11:16:20
```

**Reading:**
```python
with zipfile.ZipFile(emd_path) as zf:
    erg_text = zf.read("*.ERG").decode('latin-1', errors='ignore')
```

### Recipe Files (.REZ)

**File Location:** `ECS2000/Recipes/1001/R_HPD 25_XXXXXXXX.REZ`

**Format:** ZIP archives (16 KB each)

**Contents Example (R_HPD 25_00000001.REZ):**
```
├── R_HPD 25_00000001.CDS (8.2 KB) - Data structure
├── R_HPD 25_00000001.CIN (1.9 KB) - Config/init
├── R_HPD 25_00000001.CPF (7.5 KB) - Parameters
├── R_HPD 25_00000001.CSW (6.1 KB) - Control switches
├── R_HPD 25_00000001.CVD (4.3 KB) - Validation data
├── R_HPD 25_00000001.CMA (423 B)  - Machine metadata
└── ... 8 more files
```

**Content:** Binary configuration files with embedded metadata (RecipeNo, GroupName, ProductCode, DateStamp, User, Reason, Description, Version)

---

## 4. QA/Compliance Logs (Excel)

**Files:** 
- `FCT HP D 25 log sheet 2022.xlsx` (516 entries)
- `FCT HP D 25 log sheet 2023.xlsx` (381 entries)
- `FCT HP D 25 log sheet 2024.xlsx` (378 entries)
- `FCT HP D 25 log sheet 2025.xlsx` (392 entries)
- `FCT HP D 25 log sheet 2026.xlsx` (221 entries)

**Total:** 1,888 selective samples (~50% coverage of runs 2022-2026, 0% pre-2022)

**Purpose:** QA verification and compliance tracking (not complete run record)

**Columns:**
```
Date, Time, User, Recipe #, Material, CoSHH Ref #, Mass (g), Mould diameter (mm),
Atmosphere, TC/Pyro control, Max Force (kN), Max Temp (°C),
Voltage at Max T (V), Power at Max T (kW), PTC top (°C), PTC bot (°C),
Comments, Failures, Alarms
```

**Import Strategy:** Link via `Recipe # + Date/Time` to corresponding run in Versuch table; store as separate QA_Logs table.

---

## 5. System Configuration Databases

### ECS_CONFIG.MDB (0.8 MB)

**Tables:**
- `Alarm` (501 rows) — Alarm definitions and thresholds
- `Anlagen` (16 rows) — Facility/unit definitions
- `Messwerte` (250 rows) — Measurement point definitions (units, ranges)
- `Parameter` (400 rows) — System parameters and constants
- `Regelkreise` (50 rows) — Control loop definitions
- `RecipeGroup` (50 rows) — Recipe categorization

**Use:** Provides context for alarm codes, measurement units, and system limits

### ECS_Instruments.MDB (246 MB)

**Tables:**
- `ECS_InstrDefinition` (17 rows) — Instrument types (pyrometers, load cells, etc.)
- `ECS_TreeData` (137,948 rows) — Sensor hierarchy
- `ECS_NameSpaces` (137,948 rows) — OPC point names and addresses
- `ECS_InstrTxt` (38,537 rows) — Human-readable labels
- `ECS_ItemCrossReference` (10,265 rows) — Cross-references

**Use:** Sensor calibration, OPC namespace, instrument definitions for plotting

---

## Data Validation Example

**Cross-Source Validation (2024-01-08 10:25):**

```
Excel Log:        Recipe #2341, La2Si2O7, 63 kN, 1600°C, "30 min dwell - OK - sample cracked"
  ↓
ECS_Prog.mdb:     ProgrammNr 2341, NSW_40mm_La2Si2O7_1600-50MPa-30m
                  Daten2=1600, Daten3=La2Si2O7, Daten4=63kN, Daten5=Ar
  ↓
ECS_Analysis.mdb: VersuchNr 8738, StartDate 2024-01-08, StartTime 10:25:48
                  Daten2=1600, Daten3=La2Si2O7, Daten4=63kN
  ↓
EMD File:         V01_8738_080124.EMD → contains .HIS timeseries + .ERG event log
```

**Result:** Perfect correlation across all three sources. ✓

---

## Import Strategy

### Phase 1: Core Data (Essential)

1. **ECS_Analysis.mdb::Versuch** (9,735 runs)
   - All metadata, parameters, timestamps
   - Authoritative source of record
   
2. **ECS_Prog.mdb::Rezept** (4,995 recipes)
   - Recipe definitions and parameters
   
3. **EMD Archives** (10,193 files)
   - Extract .HIS timeseries data
   - Extract .ERG event logs
   - Link via FileName to Versuch records

4. **Excel QA Logs** (1,888 records)
   - Supplementary metadata
   - Link via Recipe # + Date/Time

### Phase 2: Context Data (Recommended)

5. **ECS_CONFIG.mdb** — Import Alarm, Messwerte, Parameter tables
   - Enables better plotting (units, ranges, thresholds)
   
6. **ECS_Instruments.mdb** — Import sensor definitions
   - Maps measurements to instruments
   - Provides calibration data

### Phase 3: Diagnostics (Optional)

7. **Monitoring logs** — Historical diagnostics
8. **Schema files** — Validation and documentation

---

## Database Schema (Directus/PostgreSQL)

### Runs Table
```sql
CREATE TABLE runs (
  id UUID PRIMARY KEY,
  versuch_nr INTEGER UNIQUE,
  recipe_id INTEGER FOREIGN KEY,
  start_datetime TIMESTAMP,
  end_datetime TIMESTAMP,
  operator VARCHAR(100),
  finished BOOLEAN,
  alarm_flag INTEGER,  -- 1=alarm, 2=critical
  material VARCHAR(255),
  force_kn NUMERIC,
  temperature_c INTEGER,
  atmosphere VARCHAR(50),
  pyro_tc VARCHAR(50),
  tool_size_mm NUMERIC,
  notes TEXT,
  
  -- File references
  emd_file_path VARCHAR(255),
  his_file_path VARCHAR(255),
  erg_file_path VARCHAR(255),
  
  -- Metadata
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### Recipes Table
```sql
CREATE TABLE recipes (
  id INTEGER PRIMARY KEY,
  programm_nr INTEGER UNIQUE,
  name VARCHAR(255),
  description TEXT,
  group_name VARCHAR(100),
  created_date TIMESTAMP,
  changed_date TIMESTAMP,
  rez_file_path VARCHAR(255),
  locked BOOLEAN,
  config_ok BOOLEAN
);
```

### QA_Logs Table
```sql
CREATE TABLE qa_logs (
  id UUID PRIMARY KEY,
  run_id INTEGER FOREIGN KEY,
  recipe_nr INTEGER,
  date DATE,
  time TIME,
  user VARCHAR(100),
  material VARCHAR(255),
  cosh_ref VARCHAR(100),
  max_force_kn NUMERIC,
  max_temp_c INTEGER,
  atmosphere VARCHAR(50),
  voltage_v NUMERIC,
  power_kw NUMERIC,
  ptc_top_c INTEGER,
  ptc_bot_c INTEGER,
  comments TEXT
);
```

### Measurements Table
```sql
CREATE TABLE measurements (
  id BIGSERIAL PRIMARY KEY,
  run_id INTEGER FOREIGN KEY,
  timestamp TIMESTAMP,
  value FLOAT,
  sensor_id INTEGER FOREIGN KEY,
  measurement_point VARCHAR(100)
);
```

### Events Table
```sql
CREATE TABLE events (
  id BIGSERIAL PRIMARY KEY,
  run_id INTEGER FOREIGN KEY,
  timestamp TIMESTAMP,
  event_type VARCHAR(100),
  description TEXT,
  source VARCHAR(50)  -- 'ERG', 'system', etc.
);
```

---

## Performance Considerations

- **MDB parsing:** access-parser: ~5-10s for 9,735 runs
- **Excel import:** pandas: <1s for all 5 years
- **ZIP extraction:** <2s per file, ~2 hours for all 10K+ files
- **Binary parsing:** NumPy fastest; struct module sufficient for memory constraint
- **Caching:** MDB reads once (schemas don't change); stream EMD files

---

## Related Documentation

- [File Reading Guide](./FAST25_FILE_READING_GUIDE.md) — Code examples for parsing each format
- [Supporting Databases](./FAST25_SUPPORTING_DATABASES.md) — Instruments, Config, Alarms
- [QA Logs Strategy](./FAST25_QA_LOGS.md) — How to handle Excel logs
