# FAST Data Integration into Directus: Schema & Plotting Changes

**Context:** The D1-Database currently has a Force Dashboard plugin designed for **machining operations** (binary `.mat` files with Fx/Fy/Fz force axes). FAST 25 and FAST 250 are **sintering operations** with fundamentally different data structure.

**Challenge:** Make Directus and the Force Dashboard plugin support both types of operations.

---

## 1. Current System Architecture (Force Dashboard)

### Current Design (Machining Operations)

**Assumptions:**
- One operation = one `.mat` file (binary, MATLAB format)
- Data: Three force axes (Fx, Fy, Fz) sampled at 25.6 kHz
- Relationship: `machining_force_analysis` ← (operates on) ← `manufacturing_operations`
- Timeseries storage: Binary `.mat` cached as `live_cache_file` (preprocessed binary)
- Plotting: Three charts (Fx, Fy, Fz) with shared x-axis (time in seconds)

**Collections:**
- `manufacturing_operations` — Defines the operation (material, feed, diameter, etc.)
- `machining_force_analysis` — Analysis metadata (sample_rate, cut_start_idx, cut_end_idx, live_cache_file)
- Plot data: Fetched from `/filter/run` API (processes binary cache)

### Current Column Model

```
ForceChart props:
  - data: { t: [seconds], env: [force_values] }
  - color: string (axis color)
  - xUnit: 'seconds'
  - yUnit: 'kN' or similar
  - hoverIndex: shared across 3 charts
```

---

## 2. FAST 25 Data Structure

### Data Type: ECS Database Backend

**Scale:**
- 9,735 runs (2010-2026)
- 4,995 recipes
- 10,193 measurement archives (.EMD files)

**Timeseries Format:**
- Source: `.HIS` files (binary IEEE 754 floats, 1-5 MB each)
- Duration: 30 mins to 5+ hours per run
- Sampling: Variable (depends on machine logic, not fixed rate)
- Columns: 30+ measurements per sample
  - Temperatures (Pyro top/front, Thermocouple positions) [6-8 values]
  - Pressures (Vessel, vacuum, cooling) [8-10 values]
  - Force/Pressing (setpoint, actual, displacement, speed) [4-5 values]
  - Hydraulic/Power (oil temp, power, voltage, current) [3-4 values]
  - Gas flows (process, flushing) [2 values]
  - Cooling water (temp, conductance) [2 values]

**Example Run:**
```
Run 8738 (2024-01-08 10:25):
  Material: La2Si2O7
  Temperature: 1600°C
  Force: 63 kN
  Duration: 2.5 hours
  Samples: 9,000+
  Measurements: 40 columns × 9,000 rows = 360,000 data points
```

**Directus Collection Structure Needed:**
- `fast_25_runs` — Run metadata (date, material, recipe, duration)
- `fast_25_recipes` — Recipe definitions (temperature, pressure, hold time)
- `fast_25_measurements` — Timeseries data (one row per sample per column)

### Data Challenges for Current Plotting

1. **No fixed sample rate:** Machine logs at variable intervals (can't assume 1 Hz)
   - Solution: Store absolute timestamps, not just array indices

2. **40+ columns:** Current charts assume 3 (Fx/Fy/Fz)
   - Solution: Make column selection dynamic; chart one measurement at a time

3. **Long duration:** Single run might be 5 hours at variable rate
   - Solution: Decimate/resample for web display (store full resolution in DB)

4. **Different units:** Force in kN, temperature in °C, pressure in mbar, etc.
   - Solution: Store unit metadata with each measurement column; charts apply it

---

## 3. FAST 250 Data Structure

### Data Type: CSV Manual Exports

**Scale:**
- 331 runs (2020-2026, sparse)
- 100+ recipes
- 175 months of exports

**Timeseries Format:**
- Source: CSV files (German locale, semicolon-delimited)
- Columns: Same as FAST 25 (40+ measurements)
- Sampling: **Fixed 1 Hz** (one row per second)
- Duration: 30 mins to 5+ hours
- Rows per run: 1,800 to 18,000

**Example Run:**
```
328_07-07-2026_133852.csv
  Machine: 8649 UOS
  Recipe: D105_IN718_Briq_1125_35MPa_30m
  Duration: ~1.5 hours
  Samples: 5,400 rows (1 Hz for 90 minutes)
  Measurements: 40 columns
```

**Directus Collection Structure Needed:**
- `fast_250_runs` — Run metadata (run_id, date, recipe)
- `fast_250_recipes` — Recipe definitions (material, temp, pressure)
- `fast_250_measurements` — Timeseries data (same schema as FAST 25)

### Data Challenges for Current Plotting

1. **CSV import format:** Current system expects binary `.mat` files
   - Solution: Pre-convert CSV to normalized database schema during import

2. **German locale:** Decimal separators (1,013.1 written as 1.013,1)
   - Solution: Handle during import; store as IEEE 754 floats in DB

3. **Same as FAST 25:** 40+ columns, long duration, variable units
   - Solution: Reuse FAST 25 approach

---

## 4. Proposed Directus Schema Changes

### New Collections (All Machines)

#### `sintering_operations` (parent)
```sql
CREATE TABLE sintering_operations (
  id UUID PRIMARY KEY,
  machine VARCHAR(20),          -- "FAST 25" or "FAST 250"
  machine_id VARCHAR(50),       -- "8649 UOS" (FAST 250) or device code (FAST 25)
  run_number INTEGER,           -- Run ID / sequence number
  
  -- Timestamps (absolute, not relative to run start)
  start_datetime TIMESTAMP,
  end_datetime TIMESTAMP,
  
  -- Recipe reference (foreign key, shared across machines)
  recipe_id UUID FOREIGN KEY → sintering_recipes(id),
  
  -- Metadata
  material VARCHAR(100),
  atmosphere VARCHAR(50),       -- e.g., Ar, vacuum
  operator VARCHAR(100),
  notes TEXT,
  
  -- File references
  source_file_path VARCHAR(255),  -- Original .HIS, .EMD, or CSV path
  source_file_type VARCHAR(20),   -- "HIS", "EMD", "CSV"
  
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Indices for fast filtering
CREATE INDEX idx_sintering_ops_machine_date ON sintering_operations(machine, start_datetime);
CREATE INDEX idx_sintering_ops_recipe ON sintering_operations(recipe_id);
```

#### `sintering_recipes` (shared)
```sql
CREATE TABLE sintering_recipes (
  id UUID PRIMARY KEY,
  name VARCHAR(255) UNIQUE,
  machine VARCHAR(20),          -- "FAST 25" or "FAST 250" or NULL for shared
  
  -- Recipe parameters (all optional, may come from CSV name or database)
  material VARCHAR(100),
  temperature_c INTEGER,
  pressure_mpa INTEGER,
  hold_time_minutes INTEGER,
  heating_rate_per_minute FLOAT,
  
  -- File reference
  file_path VARCHAR(255),       -- .RCP file path for FAST 250, or DB reference for FAST 25
  
  description TEXT,
  
  created_at TIMESTAMP DEFAULT NOW()
);
```

#### `sintering_measurements` (timeseries - HUGE table)
```sql
CREATE TABLE sintering_measurements (
  id BIGSERIAL PRIMARY KEY,
  operation_id UUID FOREIGN KEY,   -- → sintering_operations(id)
  
  -- Timestamp (absolute, not relative)
  timestamp TIMESTAMP,
  time_offset_seconds FLOAT,       -- Seconds since operation start (for plotting)
  
  -- Measurement point reference
  measurement_id UUID FOREIGN KEY, -- → sintering_measurement_definitions(id)
  
  -- Actual value
  value FLOAT,
  
  -- Create index for fast time-range queries within an operation
  -- Don't index value itself (too many unique values)
  
  FOREIGN KEY (operation_id) REFERENCES sintering_operations(id),
  FOREIGN KEY (measurement_id) REFERENCES sintering_measurement_definitions(id)
);

CREATE INDEX idx_measurements_op_time ON sintering_measurements(operation_id, timestamp);
```

**Alternative (Denormalized) Schema:** Store 40+ columns in a single "wide" row:

```sql
CREATE TABLE sintering_measurements_wide (
  id BIGSERIAL PRIMARY KEY,
  operation_id UUID FOREIGN KEY,
  timestamp TIMESTAMP,
  time_offset_seconds FLOAT,
  
  -- 40+ measurement columns
  pyro_top_c FLOAT,
  pyro_front_c FLOAT,
  piston_tc_upper_c FLOAT,
  piston_tc_contact_c FLOAT,
  piston_tc_cooling_c FLOAT,
  control_tc1_c FLOAT,
  sv_sps_heating_c FLOAT,
  y_sps_heating_pct FLOAT,
  pws_sps_heating_pct FLOAT,
  abs_pressure_vessel_mbar FLOAT,
  vacuum_vessel_mbar FLOAT,
  sv_vacuum_vessel_mbar FLOAT,
  y_vacuum_vessel_pct FLOAT,
  rel_pressure_vessel_mbar FLOAT,
  sv_rel_pressure_mbar FLOAT,
  y_rel_pressure_pct FLOAT,
  abs_pressure_cooling_mbar FLOAT,
  rel_pressure_cooling_mbar FLOAT,
  sv_pressing_force_kn FLOAT,
  av_pressing_force_kn FLOAT,
  pressing_max_way_mm FLOAT,
  pressing_relative_way_mm FLOAT,
  pressing_speed_mm_per_min FLOAT,
  hydraulic_oil_temp_c FLOAT,
  sps_power_kw FLOAT,
  sps_voltage_v FLOAT,
  sps_current_ka FLOAT,
  mfc_process_gas_l_per_min FLOAT,
  mfc_pyro_flushing_l_per_min FLOAT,
  cw_inlet_temp_c FLOAT,
  cw_inlet_conductance_us_cm FLOAT
  -- ... 10 more columns
  
  FOREIGN KEY (operation_id) REFERENCES sintering_operations(id)
);

CREATE INDEX idx_measurements_wide_op_time ON sintering_measurements_wide(operation_id, timestamp);
```

#### `sintering_measurement_definitions` (Metadata)
```sql
CREATE TABLE sintering_measurement_definitions (
  id UUID PRIMARY KEY,
  column_name VARCHAR(100),     -- "Pyro top [°C]", "Pressing force [kN]", etc.
  display_name VARCHAR(100),    -- "Pyro (top)" for UI
  unit VARCHAR(50),             -- "°C", "kN", "mbar", "%"
  
  -- Validation/plotting context
  min_value FLOAT,              -- Typical minimum for this sensor
  max_value FLOAT,              -- Typical maximum for this sensor
  alarm_low FLOAT,              -- Low alarm threshold (optional)
  alarm_high FLOAT,             -- High alarm threshold (optional)
  
  description TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Relationship Diagram

```
sintering_operations (parent)
  ↓ recipe_id
sintering_recipes (recipe definitions)

sintering_operations (parent)
  ← 1:many ← sintering_measurements (timeseries)
                ↓ measurement_id
                sintering_measurement_definitions (metadata)
```

---

## 5. Directus Collections Setup

### Directus Configuration

Create these collections in Directus:

1. **sintering_operations**
   - Type: Database table
   - Primary key: `id` (UUID)
   - Fields: [all fields above]
   - Relationships: 
     - `recipe_id` → sintering_recipes (many-to-one)
   - Permissions: Read-only for non-admin (queries only, no edits to raw data)

2. **sintering_recipes**
   - Type: Database table
   - Fields: [all above]
   - Relationships:
     - Reverse: ← sintering_operations (one-to-many)

3. **sintering_measurements** or **sintering_measurements_wide**
   - Type: Database table
   - Fields: [all above]
   - Relationships:
     - `operation_id` → sintering_operations
     - `measurement_id` → sintering_measurement_definitions
   - **CRITICAL:** Mark as "No Create/Update/Delete" (immutable once imported)
   - Pagination: 500 items (large result sets will be slow)

4. **sintering_measurement_definitions**
   - Type: Database table
   - Fields: [all above]
   - Seed with 40+ pre-defined measurement columns

---

## 6. Changes to Force Dashboard Plugin

### Current Plugin Assumptions

```typescript
// ForceChart.vue expects:
props: {
  data: { t: [seconds], env: [force_values] },  // 1D timeseries
  xUnit: 'seconds',
  yUnit: 'kN'
}

// ForceDashboard.vue assumes:
- detail.live_cache_file (binary preprocessed data)
- /filter/run API endpoint (custom binary format)
- Axes: Fx, Fy, Fz only
```

### Required Changes

#### 1. Abstract Data Loading

**Before:** Hardcoded to `/filter/run` + binary cache

**After:** Support multiple data sources:

```typescript
// New plugin config
type OperationType = 'machining' | 'sintering_fast25' | 'sintering_fast250';

interface OperationDataSource {
  type: OperationType;
  id: string;  // operation_id or analysis_id
}

async function loadOperationData(source: OperationDataSource) {
  switch (source.type) {
    case 'machining':
      return fetchMachiningData(source.id);  // Current /filter/run
    case 'sintering_fast25':
    case 'sintering_fast250':
      return fetchSinteringData(source.id);  // New API
    default:
      throw new Error(`Unknown operation type: ${source.type}`);
  }
}
```

#### 2. New API Endpoint: `/filter/sinter`

Analogous to `/filter/run`, but for FAST data:

```typescript
// GET /filter/sinter?operation_id=UUID&measurement=Pyro+top+[C]&start=0&end=3600
async function fetchSinteringData(operationId: string, measurement: string, startSec?: number, endSec?: number) {
  const params = new URLSearchParams({
    operation_id: operationId,
    measurement: measurement,
  });
  if (startSec != null) params.set('start_s', String(startSec));
  if (endSec != null) params.set('end_s', String(endSec));
  
  const res = await fetch(`/filter/sinter?${params}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch sinter data: ${res.statusText}`);
  
  const json = await res.json();
  return {
    t: json.timestamps,        // [sec, sec, ...]
    v: json.values,            // [val, val, ...]
    unit: json.unit,           // "°C", "kN", etc.
    measurement: json.measurement
  };
}
```

#### 3. Measurement Selector

**Current:** 3 hardcoded axes (Fx, Fy, Fz) with buttons

**New:** Dropdown to pick from 40+ measurements:

```typescript
const availableMeasurements = computed(() => {
  if (operationType.value !== 'sintering') return [];
  
  return [
    { name: 'Pyro top [°C]', unit: '°C' },
    { name: 'Pyro front [°C]', unit: '°C' },
    { name: 'Pressing force [kN]', unit: 'kN' },
    { name: 'Absolute pressure [mbar]', unit: 'mbar' },
    // ... 36 more
  ];
});

const selectedMeasurement = ref('Pyro top [°C]');
```

#### 4. Update ForceChart for Multiple Measurements

**Before:** Three charts hardcoded (Fx, Fy, Fz)

**After:** One chart per selected measurement:

```vue
<!-- Dynamic measurement selector -->
<select v-model="selectedMeasurement">
  <option v-for="m in availableMeasurements" :key="m.name" :value="m.name">
    {{ m.name }}
  </option>
</select>

<!-- Single chart, dynamic data -->
<ForceChart
  :title="selectedMeasurement"
  :data="chartData"
  :yUnit="measurementUnit"
  kind="env"
/>
```

#### 5. Backward Compatibility

Keep existing machining operations working unchanged:

```typescript
// Auto-detect operation type from URL/context
function detectOperationType(operationId: string): OperationType {
  // Try sintering_operations first
  const sinteOp = await api.get(`/items/sintering_operations?filter[id]=${operationId}`);
  if (sinteOp.data?.data?.length) return 'sintering_fast25';  // or 'fast250' based on machine field
  
  // Fall back to machining_force_analysis
  const machOp = await api.get(`/items/machining_force_analysis?filter[id]=${operationId}`);
  if (machOp.data?.data?.length) return 'machining';
  
  throw new Error('Unknown operation');
}
```

---

## 7. Backend API Implementation

### New Endpoint: POST /filter/sinter

```python
# Backend (e.g., Python FastAPI)
from fastapi import FastAPI, Query
import pandas as pd

app = FastAPI()

@app.get("/filter/sinter")
async def filter_sinter(
    operation_id: str,
    measurement: str,
    start_s: Optional[float] = None,
    end_s: Optional[float] = None,
    target_points: int = 1_500_000
):
    """Fetch and decimat FAST sintering timeseries data"""
    
    # 1. Load from database
    operation = db.query(SinteringOperation).filter_by(id=operation_id).first()
    if not operation:
        raise HTTPException(404, "Operation not found")
    
    # 2. Query measurements
    query = (db.query(SinteringMeasurement)
             .filter_by(operation_id=operation_id)
             .join(SinteringMeasurementDef)
             .filter_by(column_name=measurement)
             .order_by(SinteringMeasurement.timestamp))
    
    # 3. Apply time filter
    if start_s is not None:
        query = query.filter(SinteringMeasurement.time_offset_seconds >= start_s)
    if end_s is not None:
        query = query.filter(SinteringMeasurement.time_offset_seconds <= end_s)
    
    measurements = query.all()
    
    # 4. Decimate to target point count
    if len(measurements) > target_points:
        stride = len(measurements) // target_points
        measurements = measurements[::stride]
    
    # 5. Return as JSON
    return {
        'timestamps': [m.time_offset_seconds for m in measurements],
        'values': [m.value for m in measurements],
        'unit': measurements[0].definition.unit if measurements else 'unknown',
        'measurement': measurement,
        'point_count': len(measurements)
    }
```

---

## 8. Import & Schema Validation Checklist

### Pre-Import

- [ ] Create all sintering_* collections in Directus
- [ ] Populate `sintering_measurement_definitions` with 40+ columns
- [ ] Verify column names match exactly (case-sensitive!)
- [ ] Create database indices on `sintering_measurements(operation_id, timestamp)`

### During Import (ETL)

- [ ] Parse FAST 25 .HIS files → load into `sintering_operations` + `sintering_measurements`
- [ ] Parse FAST 250 CSV → normalize German locale → load
- [ ] For each run, create one `sintering_operations` row
- [ ] For each sample×column, create one `sintering_measurements` row
- [ ] Validate: All timestamps in order, no gaps > 10 seconds

### Post-Import

- [ ] Spot-check 10 random operations (verify timestamps, value ranges)
- [ ] Count total measurements (should be: sum of samples × 40 columns)
- [ ] Test `/filter/sinter` endpoint with sample queries
- [ ] Verify web UI can load and plot a sintering operation

---

## 9. Performance & Optimization

### Table Sizes (Estimate)

**For 331 FAST 250 runs @ 1 Hz × 40 columns:**
```
sintering_operations: 331 rows × 100 bytes = 33 KB
sintering_measurements: 331 runs × 5,000 samples × 40 cols = 66.4M rows
  → 66.4M × 50 bytes/row ≈ 3.3 GB (PostgreSQL)
```

**For 9,735 FAST 25 runs (variable rate, assume 5,000 samples avg):**
```
sintering_operations: 9,735 rows
sintering_measurements: 9,735 × 5,000 × 40 = 1.947B rows ≈ 100 GB
```

### Mitigation

1. **Partition measurements table by operation_id** (PostgreSQL)
   ```sql
   ALTER TABLE sintering_measurements PARTITION BY LIST (operation_id);
   ```

2. **Archive old data** (keep only 2022-2026 hot, archive 2010-2021)

3. **Decimate on display** (web always requests decimated data via `/filter/sinter`)

4. **Denormalize columns** (wide schema) instead of normalized (saves 50% storage, trades flexibility)

---

## 10. Migration Path

### Phase 1: Schema & Import (Week 1-2)
- [x] Create Directus collections
- [ ] Implement FAST 25 importer (Python script)
- [ ] Implement FAST 250 importer (Python script)
- [ ] Validate 10 sample operations

### Phase 2: Backend API (Week 3)
- [ ] Implement `/filter/sinter` endpoint
- [ ] Add measurement_id join logic
- [ ] Add decimation/downsampling

### Phase 3: Frontend Updates (Week 4)
- [ ] Refactor ForceChart for dynamic measurements
- [ ] Add measurement selector dropdown
- [ ] Implement operation type detection
- [ ] Test backward-compatibility with machining ops

### Phase 4: Polish (Week 5)
- [ ] Performance tuning (indices, partitioning)
- [ ] Comprehensive test plan
- [ ] Documentation for users

---

## 11. Open Questions

1. **Should sintering_measurements be normalized or denormalized?**
   - Normalized (current proposal): Easier to add new measurements, but slower queries + bigger storage
   - Denormalized (wide): Faster queries, smaller storage, but schema changes hard
   - **Recommendation:** Start denormalized, migrate to normalized if need arises

2. **Archive old FAST 25 data (2010-2015)?**
   - These runs are 10+ years old; likely not used for analysis
   - **Recommendation:** Archive to separate table or file storage

3. **Should we link sintering_operations to existing samples/materials DB?**
   - FAST 250 uses material names (IN718, Ti-64, etc.); could link to materials table
   - **Recommendation:** Add optional `material_id` foreign key, but don't require it

4. **Real-time FAST 250 exports?**
   - Currently manual; user said "maybe networked in future"
   - **Recommendation:** Design schema for polling, but don't implement polling yet

---

## References

- [FAST25_DATA_ARCHITECTURE.md](./FAST25_DATA_ARCHITECTURE.md) — FAST 25 data spec
- [FAST250_DATA_ARCHITECTURE.md](./FAST250_DATA_ARCHITECTURE.md) — FAST 250 data spec
- [Force Dashboard backlog](./docs/force-dashboard-backlog.md) — Related plotting work

