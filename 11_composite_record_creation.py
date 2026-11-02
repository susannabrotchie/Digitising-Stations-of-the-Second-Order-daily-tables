import pandas as pd
import numpy as np
import csv
import re
import calendar
from pathlib import Path
from collections import Counter

# ---------------- CONFIG ---------------- #
input_dirs = [
    Path(""),
    Path(""),
    Path(""),
    Path("")
]


RECORD_LABELS = [d.parent.name for d in input_dirs]

OUTPUT_DIR = Path("")
COMPOSITE_RECORDS_DIR = Path("")

# Report Paths
OUTPUT_SUMMARY = OUTPUT_DIR / "composite_comparison_summary.csv"
OUTPUT_DIFFS = OUTPUT_DIR / "composite_comparison_differences.csv"
OUTPUT_PERFECT_COLS = OUTPUT_DIR / "composite_comparison_perfect_columns.csv"
OUTPUT_META_SUMMARY = OUTPUT_DIR / "composite_metadata_comparison_summary.csv"
OUTPUT_META_DIFFS = OUTPUT_DIR / "composite_metadata_differences.csv"
OUTPUT_INCOMPLETE = OUTPUT_DIR / "files_with_less_than_4_versions.csv" # helps identify any missing files or discrepancies in filenames
OUTPUT_UNPARSEABLE = OUTPUT_DIR / "diagnostic_unparseable_files.csv"

# ---------------- HELPERS ---------------- #

def normalise_table(val, col_name=""):
    """
    - Unifies all 'Missing' labels (NA, No record, ., nil, N.A.) into ""
    - Matches n273/x273 with 273
    - Fixes Excel date corruption (5-Jun -> 5-6)
    - Strips OCR symbols and cloud-specific noise
    """
    # Get raw string and lowercase
    s = str(val).strip().lower() if not pd.isna(val) else ""
    s = s.lstrip("'") # Excel escape fix

    # Null check
    s_null_test = re.sub(r'[^a-z0-9]', '', s)
    if s_null_test in ['na', 'norecord', 'nan', 'none', 'nil', 'missing', 'nd', 'null', ''] or not s_null_test:
        return ""

    # Reverse Excel '5-Jun' -> '5-6'
    month_map = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    date_match = re.search(r"(\d{1,2})-(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", s, re.I)
    if date_match:
        day, mon_str = date_match.groups()
        s = f"{day}-{month_map[mon_str.lower()]}"

    # Remove all whitespace ('x 290' becomes 'x290')
    s = re.sub(r'\s+', '', s)

    # Strip cloud specific noise
    if "cloud" in col_name.lower():
        if s == 'o':
            s = '0' # If cloud value is exactly 'o', turn to '0'
        word_noise = r'asterisk|equiv|triangle|circle|delta|bullet|o' # define word noise, include 'o' so '10o' or 9o' is treated as the same as symbol noise
        symbols = r'[()\*\\●⬤☻≡=三Ξ≣∞∠☞⁰ºᴷ∝•∼~∿✳✴\^©◉◈◆∧▲◤◣◢△▽∇▼◮▵‣◃▴◄∗⚠¹█΁⚡⩗☀☽²³☃※❉❃✽ρ₧™⌓◦⚬∪⊕☼∘d❄❅☊◠◒◓✱⊔␣⌴⅃□■◍∩○〇Ⓛ╳∑☈◌✓↙←√┴┣⌣\|│∣~☉⊙◎♡<≤☔☂└─└∟¯‾━▂▁_—─∂─◡⏝⌢-☁Φ✠◕◔◐◑⊖₀◖+✪@#:]' # define symbol noise (escape regex * using \*, \ using \\, and ^ using \^)
        single_letter_noise = r'[bdawepcufntrsx]' # strip specific letter noise
        combined_pattern = f"({symbols}|{word_noise}|{single_letter_noise})" # combine symbol, word and letter noise to keep only the part of the value that comes before the noise. letters must come after words so the 'c' doesn't interrupt the 'circle' logic, for example
        s = re.split(combined_pattern, s)[0] # '10*', '10asterisk', '10●' and '10c' all get treated the same way

    # Remove numeric prefixes, units, and noise (n273, h_r=, m., in.)
    s = re.sub(r'^([nx])(\d)', r'\2', s)
    s = re.sub(r'^[a-z]+(_[a-z]+)?=', '', s)
    s = re.sub(r'(in\.|m\.|ft\.|feet|inches)$', '', s)
    s = s.lstrip('=+· ')
    s = re.sub(r'\s+', '', s)

    # Turns, e.g., .45, 0.450, and 0.45 into the exact same string "0.45"
    try:
        f = float(s)
        if f == int(f): s = str(int(f))
        else: s = str(f)
    except ValueError:
        pass # Not a number (e.g. 'WSW' or '5-6'), keep as is
    
    return s

def fix_1908_headers(header_row, year):
    """
    Swaps Min and Max Temperature headers for the year 1908
    Correct order for 1908: Min, Max
    If columns are already in correct order, skip
    If columns are Max, Min swap to correct order of Min, Max
    Exempts Min. Temp. on Grass column
    """
    if str(year) != "1908":
        return header_row

    max_idx = None
    min_idx = None

    # Find the positions of the two labels (ignore grass)
    for i, col in enumerate(header_row):
        c_low = col.lower()
        if "grass" in c_low: 
            continue
        if "temp" in c_low:
            if "max" in c_low: max_idx = i
            if "min" in c_low: min_idx = i

    # If Max left of Min, swap the labels (positions)
    if max_idx is not None and min_idx is not None and max_idx < min_idx:
        header_row[max_idx], header_row[min_idx] = header_row[min_idx], header_row[max_idx]
        
    return header_row

def format_table_output(val):
    """
    Final formatting for composite files.
    - Converts alphabetical wind direction codes (WSW, NE, CALM) to uppercase.
    """
    if not val: 
        return ""
    
    # Uppercase purely alphabetical strings (e.g., 'wsw' -> 'WSW', 'calm' -> 'CALM')
    if val.isalpha():
        val = val.upper()
        
    return val

def normalise_metadata(val, is_key=False, current_key=""):
    """
    Normalises metadata for voting.
    is_key=True: For the first column (Labels/Keys). Preserve these (e.g.: # SOURCE_FILENAME)
    is_key=False: For the second column (Values). Clean coordinates.
    - Converts fractions (½ -> .5, 1/2 -> .5)
    - Standardises units (ft, in, m)
    - Strips descriptive labels (Therms., h_t=, Station H=)
    - Handles historical interpuncts (12·5 -> 12.5)
    - Matches '+ .016' with '+ °016' with '+.016'
    """
    s = str(val).strip().lower() if not pd.isna(val) else ""
    if s in ['nan', 'none', 'nd', 'na', 'null', '']: return ""
    if is_key: return s

    k_low = current_key.lower()

    # Replace degree/minute symbols with a space to preserve the split point
    # e.g., "0° 7' W." -> "0 7 w"
    if any(x in k_low for x in ["lat", "long"]):
        s_coord = re.sub(r"[°'·´\"“”]", " ", s) # Replace symbols with space
        s_coord = re.sub(r'^(lat|long|latitude|longitude|alt|height)[\.:\s]*', '', s_coord)
        s_coord = re.sub(r'[^0-9nsew\s]', '', s_coord) # Keep digits, directions, and spaces
        return " ".join(s_coord.split()) # Standardize to single spaces "0 7 w"
    
    s = s.replace('·', '.').replace('°', '.') # Interpunct and degree symbol to decimal
    # fractions to decimals
    s = s.replace('½', '.5').replace('1/2', '.5')
    s = s.replace('¼', '.25').replace('1/4', '.25')
    s = s.replace('¾', '.75').replace('3/4', '.75')

    # Preserve leading sign
    prefix = "+" if "+" in s else ("-" if "-" in s else "")

    # Strip OCR and formatting noise
    # Removes §, *, {}, underscores, and trailing dots
    s = re.sub(r'[§\*\{\}_]', '', s)
    s = s.rstrip('.')

    # Strip labels (h_b=) and units (in, m, ft)
    s = re.sub(r'^[a-z\s\.-]+[=:]+', '', s)
    s = re.sub(r'^[hms][\_ \.]*[brt][\= ]*', '', s)
    s = re.sub(r'(feet|foot|meters|metres|m|ft|in|inches|inch|in|§|\*)$', '', s)

    # Keep only numbers and decimals for the Meaning Match
    s_num = re.sub(r'[^0-9\.]', '', s)
    
    try:
        if s_num.startswith('.'): s_num = '0' + s_num
        f = float(s_num)
        # 0.0250 becomes 0.025
        clean_num = str(int(f)) if f == int(f) else str(f)
        return prefix + clean_num
    except:
        # 3. TEXT LOGIC (Titles, Notes)
        return " ".join(s.split())

def harvest_metadata(meta_rows):
    """
    Converts list of metadata rows into a dictionary of {Key: Value}.
    Also harvests h_b, h_t, h_r from anywhere (like # note) into standard keys.
    """
    data = {}
    
    # Standard height keys to be populated
    msl_key = "# height_above_msl"
    h_b_key = "# height_above_ground_barometer"
    h_t_key = "# height_above_ground_thermometers"
    h_r_key = "# rain_gauge_height"

    for row in meta_rows:
        if not row: continue
        key = str(row[0]).strip()
        val = str(row[1]).strip() if len(row) > 1 else ""
        
        # Check if the row is an explicit height key
        k_low = key.lower()
        if "height_above_ground_barometer" in k_low: data[h_b_key] = val
        elif "height_above_ground_thermometers" in k_low: data[h_t_key] = val
        elif "rain_gauge_height" in k_low: data[h_r_key] = val
        else:
            # Check for aliases inside ANY key (like # note or # height_above_msl)
            # Looks for "h_b = 202" or similar
            v_low = val.lower()
            if 'h_b' in v_low: data[h_b_key] = val
            elif 'h_t' in v_low: data[h_t_key] = val
            elif 'h_r' in v_low: data[h_r_key] = val
            
            # Save the original key-value pair as well
            data[key] = val
            
    return data

def pick_consensus_raw_meta(raw_list, norm_list, winning_norm):
    """
    Among metadata files that agreed on meaning, pick the most common visual string to preserve units (ft, in, m, +).
    so 12.5 m. 12·5 m.	12·5 m.	12.5 m. will match 4/4
    """
    eligible_raws = [raw_list[i] for i, norm in enumerate(norm_list) if norm == winning_norm]
    return Counter(eligible_raws).most_common(1)[0][0] if eligible_raws else ""

def metadata_format(norm_val, raw_winner, current_key=""):
    """
    Determines what gets written to the composite file.
    Formats the winning meaning for the composite file
    E.g.: Lat 52˚43' N from records 1 and 4 and 52˚43'N from records 2 and 3 all get normalised to 52 43 N
    52 43 N is the winning value and is then correctly formatted by this function
    """
    k_low = current_key.lower()

    # Case A: Coordinates (Lat/Long only)
    if any(x in k_low for x in ["lat", "long"]):
        parts = norm_val.split()
        if len(parts) == 3 and parts[-1] in ['n','s','e','w']:
            deg, mins, dir_char = parts
            return f"{deg}° {mins}' {dir_char.upper()}."
        if len(parts) == 2 and parts[-1] in ['n','s','e','w']:
            deg, dir_char = parts
            return f"{deg}° {dir_char.upper()}."

    # Case B: Gravity / Heights / Notes
    # We return the RAW winner to keep original units like '+0.025 in' or '12.5 m.'
    return raw_winner
    
def find_header_index(rows):
    """
    Uses simple 'in' check instead of splitting. 
    This allows 'barometer_32F_9am' to match 'barometer'.
    """
    for i, r in enumerate(rows):
        if not r: continue
        joined = " ".join(str(cell).strip().lower() for cell in r if cell)
        
        # All formats contain 'temp'
        if ("barometer" in joined or "air pressure" in joined) and "temp" in joined and len(r) > 3: # require multiple columns, not just a stray keyword match
            return i
             
    raise ValueError("Header row not found")

def get_file_metadata(file_path):
    """Finds JPG, first barometer reading, and column name for remapping."""
    try:
        with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            rows = [next(csv.reader(f)) for _ in range(80)]
        
        # 1. Get Source JPG
        jpg = "Unknown"
        for r in rows[:10]:
            if r and len(r) > 1 and "SOURCE_FILENAME" in str(r[0]).upper():
                jpg = str(r[1]).strip(); break
            
        # 2. Get Weather Data Table
        h_idx = find_header_index(rows)
        header_row = rows[h_idx]
        
        # 3. Find Pressure/Barometer Column
        col_idx, col_name = None, "None"
        search_rows = [rows[h_idx]]
        if h_idx > 0: search_rows.append(rows[h_idx-1])
        
        keywords = ["pressure", "barometer", "baro", "press"]
        for r_to_search in search_rows:
            for c_idx, cell in enumerate(r_to_search):
                if any(k in str(cell).lower() for k in keywords):
                    col_idx, col_name = c_idx, cell; break
            if col_idx is not None: break
        
        # Fallback to first numeric column
        if col_idx is None:
            for c_idx in range(1, len(rows[h_idx + 1])):
                if any(char.isdigit() for char in normalise_table(rows[h_idx + 1][c_idx])):
                    col_idx, col_name = c_idx, "Auto-Detected"; break

        # 4. Extract first numeric value (scanning down up to 10 rows)
        baro_val = ""
        if col_idx is not None:
            for scan_idx in range(h_idx + 1, h_idx + 11):
                val = normalise_table(rows[scan_idx][col_idx])
                if val:
                    baro_val = rows[scan_idx][col_idx]; break
                    
        return jpg, baro_val, col_name
    except:
        return "Unknown", "", "Error"

def load_csv_full(path):
    """Loads full CSV for processing."""
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
        rows = list(csv.reader(f))
    idx = find_header_index(rows)
    meta = rows[:idx]
    jpg = "Unknown"
    for r in meta[:10]:
        if r and len(r) > 1 and "SOURCE_FILENAME" in str(r[0]).upper():
            jpg = str(r[1]).strip(); break
    return meta, rows[idx], rows[idx+1:], jpg

def extract_from_csv(filename):
    name = filename.lower().replace(".csv", "")
    if name.startswith("sso_"): name = name[4:]
    parts = name.split("_")
    m_map = {"jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
             "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12"}
    month, year, m_idx = None, None, None
    for i, p in enumerate(parts):
        if p[:3] in m_map: month, m_idx = m_map[p[:3]], i
        elif re.fullmatch(r"(18\d{2}|19\d{2})", p): year = p
    if m_idx is not None and year is not None:
        station_segments = parts[:m_idx]
        clean = [seg for seg in station_segments if not re.fullmatch(r"[abcde]+", seg)]
        station = " ".join(clean).strip()
        if station: return station, month, year
    return None

# ---------------- MAIN PROCESS ---------------- #

def process_all():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    COMPOSITE_RECORDS_DIR.mkdir(parents=True, exist_ok=True)

    file_maps, unparseable_files = {}, []
    total_files_discovered = 0

    # 1. DISCOVERY & IDENTITY RESOLUTION
    for i, d in enumerate(input_dirs):
        full_label = RECORD_LABELS[i]
        # Identify folder index (0, 1, 2, or 3)
        
        for f in d.rglob("*.csv"):
            total_files_discovered += 1
            
            # Parse identity (Station, Month, Year) from the filename
            res = extract_from_csv(f.name)
            if not res:
                unparseable_files.append({"folder": full_label, "file": f.name, "reason": "Regex Failed"})
                continue
            
            st_slug, mo, yr = res
            
            # Assign to comparison map
            if res not in file_maps:
                file_maps[res] = [None] * 4
            
            # Check if this station/date already has a file assigned in this specific folder
            if file_maps[res][i] is not None:
                unparseable_files.append({
                    "folder": full_label, 
                    "file": f.name, 
                    "reason": "Duplicate Key Clash (Multiple files for same month)"
                })
            else:
                file_maps[res][i] = f

    stats = {"success": 0, "incomplete": 0, "zero_data": 0, "total_cols": 0, "total_perfect_cols": 0}
    table_summary, table_diffs, meta_diffs, perfect_cols, incomplete_sets = [], [], [], [], []

    for (station, month, year), paths in file_maps.items():
        found_paths = [p for p in paths if p is not None]
        if len(found_paths) < 4:
            stats["incomplete"] += 1
            incomplete_sets.append({
                "station": station.title(), "year": year, "month": month, "found_count": len(found_paths),
                "source_jpgs": ", ".join([get_file_metadata(p)[0] for p in found_paths]),
                "missing": ", ".join([RECORD_LABELS[i] for i, p in enumerate(paths) if p is None])
            })
            continue 

        all_meta, all_headers, all_data, all_jpgs = [], [], [], []
        for p in paths:
            m, h, d, j = load_csv_full(p)
            # apply 1908 header swap
            h = fix_1908_headers(h, year)
            all_meta.append(m); all_headers.append(h); all_data.append(d); all_jpgs.append(j)

        max_rows = max(len(d) for d in all_data)
        max_cols = max(len(h) for h in all_headers)
        max_meta_rows = max(len(m) for m in all_meta)
        consensus_jpg = Counter(all_jpgs).most_common(1)[0][0]

        # --- METADATA VOTING (key based) ---
        # Harvest dictionaries from all 4 files
        meta_dicts = [harvest_metadata(m) for m in all_meta]
        
        # Get a master list of all keys found in any of the 4 files
        all_unique_keys = []
        for d in meta_dicts:
            for k in d.keys():
                if k not in all_unique_keys: all_unique_keys.append(k)

        voted_meta = []
        for key in all_unique_keys:
            raw_vals = [d.get(key, "") for d in meta_dicts]
            
            # Normalise for voting
            norm_vals = [normalise_metadata(v, current_key=key) for v in raw_vals]
            win_norm, freq = Counter(norm_vals).most_common(1)[0]
            
            if freq >= 3:
                # Retrieve the best raw visual from the files that provided the winning meaning
                best_raw = pick_consensus_raw_meta(raw_vals, norm_vals, win_norm)
                voted_meta.append([key, metadata_format(win_norm, best_raw, key)])
                
            else:
                # Log to difference report
                meta_diffs.append({
                    "station": station.title(), "date": f"{year}-{month}", "source_jpg": consensus_jpg, "meta_key": key,
                    "agreement": f"{freq}/4",
                    RECORD_LABELS[0]: raw_vals[0], RECORD_LABELS[1]: raw_vals[1],
                    RECORD_LABELS[2]: raw_vals[2], RECORD_LABELS[3]: raw_vals[3]
                })
                # Add to file as mismatch
                voted_meta.append([key, "MISMATCH"])

        # --- TABLE VOTING ---
        comp_table, t_counts = [], {4:0, 3:0, 2:0, 1:0}
        perf_track = {c: True for c in range(max_cols)}
        header_to_use = all_headers[np.argmax([len(h) for h in all_headers])]
        stats["total_cols"] += max_cols

        for r in range(max_rows):
            comp_row = []
            for c in range(max_cols):
                cur_col = header_to_use[c] if c < len(header_to_use) else ""

                # Collect raw values (Untouched strings exactly as they appear in the CSVs)
                raw_v = [all_data[i][r][c] if r < len(all_data[i]) and c < len(all_data[i][r]) else "" for i in range(4)]

                # Normalise (standardise meaning: handle n273, fix 5-Jun -> 5-6, strip cloud symbols)
                norm_v = [normalise_table(v, col_name=cur_col) for v in raw_v]

                # Vote based on normalised value
                winner_norm, freq = Counter(norm_v).most_common(1)[0]
                t_counts[freq] += 1

                # Handle differences (If not a perfect 4/4 match)
                if freq < 4:
                    perf_track[c] = False
                    col_name = header_to_use[c] if c < len(header_to_use) else f"Col_{c}"
                    diff_entry = {
                        "station": station.title(), 
                        "date": f"{year}-{month}", 
                        "source_jpg": consensus_jpg, 
                        "row": r+1, 
                        "column": col_name, 
                        "agreement": f"{freq}/4"
                    }
                    # Log raw values: This shows 10● vs 10, or 5-Jun vs 5-6 in the report
                    for i in range(4): 
                        diff_entry[RECORD_LABELS[i]] = raw_v[i] # Shows the original strings
                    table_diffs.append(diff_entry)

                # Build composite row (rule: 3-of-4)
                if freq >= 3:
                    # Apply format_table_output to capitalise wind direction letters
                    comp_row.append(format_table_output(winner_norm))
                else:
                    comp_row.append("")
            comp_table.append(comp_row)
        
        # if the "mean" label didn't make it through voting, it is reinserted here
        try:
            # Calculate how many days are in this specific month/year
            days_in_mo = calendar.monthrange(int(year), int(month))[1]
            
            # Mean row index is equal to the number of days due to zero-indexing
            # (e.g., if 31 days, indices 0-30 are days, index 31 is the 32nd row)
            mean_row_idx = days_in_mo 
            
            # If the table is long enough to have a Mean row, force the label
            if len(comp_table) > mean_row_idx:
                comp_table[mean_row_idx][0] = "Mean"
                
        except Exception as e:
            # Log error if year/month are non-integers, but don't stop the script
            print(f"[DEBUG] Could not calculate Mean row for {station} {year}-{month}: {e}")

        for c, is_perf in perf_track.items():
            if is_perf:
                stats["total_perfect_cols"] += 1
                perfect_cols.append({"station": station.title(), "year": year, "month": month, "column": header_to_use[c] if c < len(header_to_use) else c})

        # --- save composite file ---
        st_slug = station.replace(" ", "_")
        town_folder = COMPOSITE_RECORDS_DIR / st_slug.title()
        town_folder.mkdir(parents=True, exist_ok=True)
        out_name = f"SSO_{st_slug}_{year}_{month}_COMPOSITE.csv"
        with open(town_folder / out_name, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerows(voted_meta); writer.writerow(header_to_use); writer.writerows(comp_table)

        stats["success"] += 1
        total_cells = max_rows * max_cols
        table_pct = round((t_counts[4] + t_counts[3]) / total_cells * 100, 2) if total_cells > 0 else 0
        
        # ADD DETAILED COUNTS TO SUMMARY
        table_summary.append({
            "station": station.title(), "year": year, "month": month, "source_jpg": consensus_jpg, 
            "total_cells": total_cells, "pct_agree_3_4": table_pct, 
            "instances_4_of_4": t_counts[4], "instances_3_of_4": t_counts[3],
            "instances_2_of_4": t_counts[2], "instances_1_of_4": t_counts[1]
        })

    # --- save reports ---
    def save_df(data, p):
        df = pd.DataFrame(data)
        if not df.empty:
            sort_cols = []
            if 'year' in df.columns: sort_cols.append('year')
            if 'month' in df.columns: sort_cols.append('month')
            if 'station' in df.columns: sort_cols.append('station')
            if 'date' in df.columns and 'year' not in df.columns: sort_cols.append('date')
            if 'row' in df.columns: sort_cols.append('row')
            df.sort_values(by=sort_cols).to_csv(p, index=False, encoding='utf-8-sig')

    save_df(table_summary, OUTPUT_SUMMARY)
    save_df(incomplete_sets, OUTPUT_INCOMPLETE)
    save_df(unparseable_files, OUTPUT_UNPARSEABLE)
    save_df(table_diffs, OUTPUT_DIFFS)
    save_df(meta_diffs, OUTPUT_META_DIFFS)
    save_df(perfect_cols, OUTPUT_PERFECT_COLS)

    # --- print ---
    acc = (stats["success"] * 4) + sum(i['found_count'] for i in incomplete_sets) + len(unparseable_files)
    print("\n" + "="*60)
    print(f"Total CSVs discovered:             {total_files_discovered}")
    print(f"Files accounted for:               {acc}")
    print(f"   - Successful composite sets:    {stats['success']} ({stats['success']*4} files)")
    print(f"   - Incomplete sets:              {stats['incomplete']} sets")
    print(f"   - Discrepancy:                  {total_files_discovered - acc}")
    print(f"Total Columns Processed:           {stats['total_cols']}")
    print(f"Total Perfect Columns Found:       {stats['total_perfect_cols']}")
    print("="*60 + "\n")

if __name__ == "__main__":
    process_all()