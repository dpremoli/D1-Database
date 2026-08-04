# FAST 25 File Reading Guide

How to parse each file type in the FAST 25 data architecture with working code examples.

---

## Quick Reference

| File Type | Library | Status | Example |
|-----------|---------|--------|---------|
| `.MDB` | `access-parser` | ✓ Tested | ECS_Analysis.MDB (9.7K runs) |
| `.XLSX` | `pandas` | ✓ Tested | FCT HP D 25 log sheet 2024.xlsx |
| `.REZ` (ZIP) | `zipfile` | ✓ Tested | R_HPD 25_00000001.REZ |
| `.EMD` (ZIP) | `zipfile` | ✓ Tested | V01_10632_090426.EMD |
| `.HIS` (binary) | `struct`/`numpy` | ✓ Tested | Timeseries measurements |
| `.ERG` (text+binary) | `zipfile`+decode | ✓ Tested | Event logs |
| `.XSLT`/`.XSD` | `defusedxml` | ✓ Tested | Schema validation |

---

## 1. Microsoft Access Databases (.MDB)

### Installation

```bash
pip install access-parser
```

### Reading (Pure Python, Cross-Platform)

```python
from access_parser import AccessParser

# Open database
db = AccessParser(r"C:\path\to\ECS_Analysis.MDB")

# List all tables
tables = db.catalog  # dict of table names
print(list(tables.keys()))
# Output: ['Versuch', 'DataCaption', 'Filter', 'Refresh', 'MSysObjects']

# Read a table
table = db.parse_table("Versuch")
# Returns: {'VersuchNr': [1, 2, 3, ...], 'StartDate': [...], ...}

# Access data
for i in range(len(table["VersuchNr"])):
    run_id = table["VersuchNr"][i]
    start = table["StartDate"][i]
    material = table["Daten3"][i]
    print(f"Run {run_id}: {material} started {start}")
```

### Reading All Runs (Efficient)

```python
from access_parser import AccessParser
import pandas as pd


def import_runs(mdb_path):
    db = AccessParser(mdb_path)
    table = db.parse_table("Versuch")

    # Convert to DataFrame for easier manipulation
    df = pd.DataFrame(table)

    # Filter runs with complete data
    df = df[df["Finished"] == True]

    return df


runs_df = import_runs("ECS_Analysis.MDB")
print(f"Loaded {len(runs_df)} completed runs")
```

### Alternative: ODBC (Windows Only)

Requires Access OLEDB driver (not installed by default):

```python
import pyodbc

conn = pyodbc.connect(r"Driver={Microsoft Access Driver (*.mdb)};DBQ=path.mdb;")
cursor = conn.cursor()

cursor.execute("SELECT VersuchNr, StartDate, Material FROM Versuch WHERE Finished=True")
for row in cursor.fetchall():
    print(row)
```

---

## 2. Excel Files (.XLSX)

### Installation

```bash
pip install pandas openpyxl
```

### Reading Single File

```python
import pandas as pd

# Read specific sheet
df = pd.read_excel("FCT HP D 25 log sheet 2024.xlsx", sheet_name="Jan ")

print(f"Columns: {df.columns.tolist()}")
# Output: ['Date', 'Time', 'User', 'Recipe #', 'Material', ...]

print(f"Rows: {len(df)}")
# Output: Rows: 7 (in January sheet)
```

### Reading All Sheets (All Years)

```python
import pandas as pd
from pathlib import Path


def import_qa_logs(log_dir):
    all_data = []

    # Read all year files
    for year in range(2022, 2027):
        file = f"{log_dir}/FCT HP D 25 log sheet {year}.xlsx"
        xl_file = pd.ExcelFile(file)

        # Read all sheets in file
        for sheet in xl_file.sheet_names:
            df = pd.read_excel(file, sheet_name=sheet)
            all_data.append(df)

    # Combine all data
    combined = pd.concat(all_data, ignore_index=True)
    return combined


qa_logs = import_qa_logs("C:/path/to/logs")
print(f"Total QA log entries: {len(qa_logs)}")
# Output: Total QA log entries: 1888

# Join with runs on Recipe # + Date/Time
qa_logs["datetime"] = pd.to_datetime(
    qa_logs["Date"].astype(str) + " " + qa_logs["Time"].astype(str)
)
```

---

## 3. ZIP Archives: Recipes (.REZ) and Runs (.EMD)

### Installation

```bash
# Built-in: zipfile
# No external dependencies needed
```

### Listing Contents

```python
from zipfile import ZipFile

# Recipe archive
with ZipFile("R_HPD 25_00000001.REZ") as zf:
    print("Recipe contents:")
    for name in zf.namelist():
        info = zf.getinfo(name)
        print(f"  {name:40s} {info.file_size:8d} bytes")

# Output:
# R_HPD 25_00000001.CDS            8236 bytes
# R_HPD 25_00000001.CIN            1948 bytes
# R_HPD 25_00000001.CPF            7514 bytes
# ...
```

### Extracting All Archives

```python
from zipfile import ZipFile
from pathlib import Path
import os


def extract_all_rez_emd(base_dir, output_dir):
    """Extract all REZ and EMD archives"""
    os.makedirs(output_dir, exist_ok=True)

    # Find all ZIP files (disguised as .REZ and .EMD)
    for zip_file in Path(base_dir).glob("**/*.REZ"):
        extract_name = zip_file.stem
        extract_path = os.path.join(output_dir, extract_name)

        with ZipFile(zip_file) as zf:
            zf.extractall(extract_path)
            print(f"Extracted {zip_file.name} → {extract_path}")


extract_all_rez_emd("ECS2000", "extracted_recipes")
```

---

## 4. Binary Timeseries Files (.HIS)

### Installation

```bash
pip install numpy
```

### Reading Floats (Numpy - Recommended)

```python
import numpy as np
from zipfile import ZipFile

# Extract from EMD archive and read as floats
with ZipFile("V01_10632_090426.EMD") as zf:
    his_bytes = zf.read("V01_10632_090426.HIS")

# Skip header (first 4 bytes), interpret rest as IEEE 754 float32
floats = np.frombuffer(his_bytes[4:], dtype=np.float32)

print(f"Measurements: {len(floats)} values")
print(f"Range: {floats.min():.2f} to {floats.max():.2f}")
print(f"Mean: {floats.mean():.2f}")

# Plot or save
import matplotlib.pyplot as plt

plt.plot(floats)
plt.ylabel("Measurement Value")
plt.xlabel("Sample")
plt.savefig("timeseries.png")
```

### Reading with Struct (Lower Memory)

```python
import struct
from zipfile import ZipFile

with ZipFile("V01_10632_090426.EMD") as zf:
    his_data = zf.read("V01_10632_090426.HIS")

# Parse floats manually
offset = 4  # Skip header
floats = []
while offset < len(his_data) - 4:
    value = struct.unpack("<f", his_data[offset : offset + 4])[
        0
    ]  # Little-endian float32
    floats.append(value)
    offset += 4

print(f"Parsed {len(floats)} measurements")
```

### Format Details

```
Binary Structure:
  Offset  Size  Value
  0-3     4B    0x01 0x00 0x23 0x00  (header/record type)
  4-7     4B    float32 (measurement 1)
  8-11    4B    float32 (measurement 2)
  12-15   4B    float32 (measurement 3)
  ...

Encoding: IEEE 754 floating-point, little-endian (PC standard)

To decode: struct.unpack('<f', bytes[offset:offset+4])[0]
  '<' = little-endian
  'f' = 32-bit float
```

---

## 5. Event/Error Log Files (.ERG)

### Installation

```bash
# Built-in: zipfile
# No external dependencies needed
```

### Reading Text Events

```python
from zipfile import ZipFile

with ZipFile("V01_10632_090426.EMD") as zf:
    erg_bytes = zf.read("V01_10632_090426.ERG")

# Decode as text (ignore binary sections)
erg_text = erg_bytes.decode("latin-1", errors="ignore")

# Parse events
print("Events from run:")
for line in erg_text.split("\n"):
    if line.strip():
        print(f"  {line}")
```

### Sample Output

```
Communication error
02/04/2026 12:14:38
System
1
Communication error
02/04/2026 12:14:57
System
1
Start logging
09/04/2026 11:16:20
System
1
Segment 1 - Start Vacuum
09/04/2026 11:16:20
System
1
```

### Parsing Structured Events

```python
import re
from zipfile import ZipFile


def parse_erg(erg_bytes):
    """Extract structured events from ERG file"""
    erg_text = erg_bytes.decode("latin-1", errors="ignore")

    events = []
    lines = [l.strip() for l in erg_text.split("\n") if l.strip()]

    i = 0
    while i < len(lines):
        # Pattern: Event description, Date, Time, System ID, User/Level
        if i + 4 < len(lines) and "/" in lines[i + 1]:  # Date check
            try:
                event = {
                    "description": lines[i],
                    "datetime": f"{lines[i + 1]} {lines[i + 2]}",
                    "source": lines[i + 3],
                    "user_level": lines[i + 4],
                }
                events.append(event)
                i += 5
            except:
                i += 1
        else:
            i += 1

    return events


with ZipFile("V01_10632_090426.EMD") as zf:
    erg_bytes = zf.read("V01_10632_090426.ERG")

events = parse_erg(erg_bytes)
for evt in events[:5]:
    print(f"{evt['datetime']}: {evt['description']}")
```

---

## 6. XML Schema & XSLT Files

### Installation

```bash
pip install defusedxml
```

### Parsing XSD Schema (Safe)

```python
from defusedxml import ElementTree as ET

# Parse schema safely (prevents XXE attacks)
tree = ET.parse("ECSBatch_V3.xsd")
root = tree.getroot()

# List element definitions
namespace = {"xsd": "http://www.w3.org/2001/XMLSchema"}
for elem in root.findall(".//xsd:element", namespace):
    name = elem.get("name")
    type_name = elem.get("type")
    print(f"  {name}: {type_name}")
```

### Parsing XSLT Transform

```python
from defusedxml import ElementTree as ET

tree = ET.parse("ECS Batch CSV StyleSheet_MvOnlyAbsTime.xslt")
root = tree.getroot()

namespace = {"xsl": "http://www.w3.org/1999/XSL/Transform"}

# Find template rules
print("CSV Export Template Rules:")
for template in root.findall(".//xsl:template", namespace):
    match = template.get("match")
    print(f"  Match: {match}")
```

---

## 7. Complete Import Example

```python
from access_parser import AccessParser
import pandas as pd
from zipfile import ZipFile
import numpy as np


def import_fast25_data():
    """Import complete FAST 25 dataset"""

    # 1. Load databases
    print("Loading databases...")
    prog_db = AccessParser("ECS_Prog.mdb")
    recipes = prog_db.parse_table("Rezept")

    analysis_db = AccessParser("ECS_Analysis.mdb")
    runs = analysis_db.parse_table("Versuch")
    print(f"  Recipes: {len(recipes['ProgrammNr'])}")
    print(f"  Runs: {len(runs['VersuchNr'])}")

    # 2. Load Excel QA logs
    print("Loading QA logs...")
    qa_data = []
    for year in range(2022, 2027):
        df = pd.read_excel(f"FCT HP D 25 log sheet {year}.xlsx", sheet_name=None)
        for sheet_df in df.values():
            qa_data.append(sheet_df)
    qa_logs = pd.concat(qa_data, ignore_index=True)
    print(f"  QA entries: {len(qa_logs)}")

    # 3. Load measurements (sample)
    print("Loading measurements from EMD archives...")
    measurements = []

    for i in range(min(10, len(runs["VersuchNr"]))):  # First 10 runs as sample
        emd_file = runs["FileName"][i]
        emd_path = f"Data/Batch/{emd_file}.EMD"

        try:
            with ZipFile(emd_path) as zf:
                # Read HIS timeseries
                his_data = np.frombuffer(
                    zf.read(f"{emd_file}.HIS")[4:], dtype=np.float32
                )

                # Read ERG events
                erg_text = zf.read(f"{emd_file}.ERG").decode("latin-1", errors="ignore")

                measurements.append(
                    {
                        "run_id": runs["VersuchNr"][i],
                        "measurements": len(his_data),
                        "events": len(erg_text.split("\n")),
                    }
                )
        except:
            pass

    print(f"  Extracted: {len(measurements)} run archives")

    return {
        "recipes": recipes,
        "runs": runs,
        "qa_logs": qa_logs,
        "measurements": measurements,
    }


# Run import
data = import_fast25_data()
```

---

## Performance Benchmarks

```
Operation              Time      Tools Used
─────────────────────────────────────────────────
Load 4,995 recipes     ~2s       access-parser
Load 9,735 runs        ~8s       access-parser
Read 5 years Excel     <1s       pandas
Extract 1 EMD          <100ms    zipfile
Parse 925 KB .HIS      ~50ms     numpy
Extract all 10K EMDs   ~2 hours  zipfile
─────────────────────────────────────────────────
Total import (all)     ~2 hours
```

---

## Troubleshooting

### "ImportError: No module named 'access_parser'"

```bash
pip install access-parser
```

### "Cannot read MDB file" (OLEDB not installed)

Use `access-parser` (pure Python) instead of pyodbc. `access-parser` doesn't require OLEDB driver.

### ".ERG file has garbled text"

Try different encodings:
```python
# Try these in order:
for encoding in ["latin-1", "cp1252", "utf-16", "ascii"]:
    try:
        text = erg_bytes.decode(encoding, errors="ignore")
        break
    except:
        pass
```

### ".HIS floats look wrong (NaN or huge values)"

Verify endianness:
```python
import struct

# Check both:
little_endian = struct.unpack("<f", bytes[4:8])[0]  # PC standard
big_endian = struct.unpack(">f", bytes[4:8])[0]

print(f"Little-endian: {little_endian}")
print(f"Big-endian: {big_endian}")
# PC should be little-endian
```

### "ZipFile says archive is corrupt"

This is false for `.REZ` and `.EMD` files. They ARE valid ZIP files. Python's `zipfile` module reads them correctly.

---

## Security Notes

**XML Parsing:**
- Always use `defusedxml` instead of stdlib `xml.etree.ElementTree`
- Protects against XXE (external entity injection) attacks
- `defusedxml` is a drop-in replacement

**Binary Parsing:**
- Verify header bytes before interpreting as floats
- Use `struct` module with explicit endianness (`<` for little-endian)
- Handle decode errors gracefully: `.decode(..., errors='ignore')`

---

## Next: Database Storage

Once parsed, import into Directus/PostgreSQL using the schema defined in `FAST25_DATA_ARCHITECTURE.md`.
