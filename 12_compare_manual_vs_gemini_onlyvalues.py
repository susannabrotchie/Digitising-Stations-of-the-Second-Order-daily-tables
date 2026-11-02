import pandas as pd
import re
from pathlib import Path
import random
import numpy as np
import csv
from difflib import SequenceMatcher
import math

'''
===================================================
For SSO daily tables for select periods in 1899-1875:
compares manual transcription .xlsx files with Gemini transcription csv files.

Does not compare whole table, only existing values in CSVs get compared to their manually transcribed (XLSX) counterparts
i.e.: empty cells in the composite record are not penalised
Measures accuracy rather than completeness

Outputs:
1. Summary Report (Overview of all files, % agreement - Sorted by Station & Date)
2. Differences Report (Cell-by-cell mismatches)
3. Column Summary (Accuracy per column across all files)
4. Difference Count Report (Sorted by Station & Date)
5. Perfect Columns Report (Sorted by Station & Date)
===================================================
'''

# ---------------- CONFIG ---------------- #

input_dir = Path("")
XLSX_FOLDER = Path("/SSO_manually_transcribed")

# Outputs
OUTPUT_DIR = Path("")
OUTPUT_SUMMARY = OUTPUT_DIR / "manualgemini_comparison_summary_valuesonly.csv"
OUTPUT_DIFFS = OUTPUT_DIR / "manualgemini_comparison_differences_valuesonly.csv"
OUTPUT_COL_SUMMARY = OUTPUT_DIR / "manualgemini_comparison_column_summary_valuesonly.csv"
OUTPUT_DIFF_COUNTS = OUTPUT_DIR / "manualgemini_comparison_file_difference_counts_valuesonly.csv"
OUTPUT_PERFECT_COLS = OUTPUT_DIR / "manualgemini_comparison_perfect_columns_valuesonly.csv" 
OUTPUT_DECIMAL_ERRORS = OUTPUT_DIR / "manualgemini_comparison_numeric_decimal_errors_valuesonly.csv"

# Offsets (0-based)
CSV_ROW_START = 12   
CSV_COL_START = 0
# Dynamic XLSX Row Starts
XLSX_ROW_START_DEFAULT = 4   # 1883 and later
XLSX_ROW_START_PRE_1883 = 3  # Before 1883

XLSX_COL_START = 3

# Standard Headers
TARGET_HEADERS = [
    "Day",
    "Barometer 9am", "Barometer 9pm",
    "Air Temp 9am", "Air Temp 9pm", "Temp Min", "Temp Max",
    "Wet Bulb 9am", "Wet Bulb 9pm",
    "Vapour 9am", "Vapour 9pm",
    "Humidity 9am", "Humidity 9pm",
    "Wind Dir 9am", "Wind Force 9am", "Wind Dir 9pm", "Wind Force 9pm",
    "Cloud 9am", "Cloud 9pm",
    "Rain"
]

# ---------------- HELPERS ---------------- #

def coerce_numeric(df):
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass
    return df

"""works for individual record filename structure"""
"""sso_armagh_october_1890.csv"""
# def extract_from_csv(filename):
#     name = filename.lower().replace(".csv", "")
#     if name.startswith("sso_"):
#         name = name[4:]
#     parts = name.split("_")

#     month_map = {
#         "jan":"01","january":"01","feb":"02","february":"02",
#         "mar":"03","march":"03","apr":"04","april":"04","may":"05",
#         "jun":"06","june":"06","jul":"07","july":"07","aug":"08","august":"08",
#         "sep":"09","september":"09","oct":"10","october":"10",
#         "nov":"11","november":"11","dec":"12","december":"12"
#     }

#     month = None
#     year = None
#     month_index = None

#     for i, p in enumerate(parts):
#         if p in month_map:
#             month = month_map[p]
#             month_index = i
#         elif re.fullmatch(r"(18\d{2}|19\d{2})", p):
#             year = p

#     if month_index is not None:
#         station_parts = parts[:month_index]
#         station = " ".join(station_parts).strip()
#     else:
#         station = None

#     return station, month, year

"""works for composite record filename structure"""
"""SSO_armagh_1890_10_COMPOSITE.csv"""
def extract_from_csv(filename):
    name = filename.lower().replace(".csv", "")
    
    # Remove leading sso_
    if name.startswith("sso_"):
        name = name[4:]
        
    # Replace hyphens and spaces with underscores to normalize
    name = name.replace("-", "_").replace(" ", "_")
    parts = name.split("_")

    month_map = {
        "jan":"01","january":"01","01":"01","1":"01",
        "feb":"02","february":"02","02":"02","2":"02",
        "mar":"03","march":"03","03":"03","3":"03",
        "apr":"04","april":"04","04":"04","4":"04",
        "may":"05","05":"05","5":"05",
        "jun":"06","june":"06","06":"06","6":"06",
        "jul":"07","july":"07","07":"07","7":"07",
        "aug":"08","august":"08","08":"08","8":"08",
        "sep":"09","september":"09","09":"09","9":"09",
        "oct":"10","october":"10","10":"10",
        "nov":"11","november":"11","11":"11",
        "dec":"12","december":"12","12":"12"
    }

    month = None
    year = None
    first_date_idx = None # Tracks where the station name ends

    for i, p in enumerate(parts):
        # 1. Check if the part is a Year
        if re.fullmatch(r"(18\d{2}|19\d{2})", p):
            year = p
            if first_date_idx is None:
                first_date_idx = i
                
        # 2. Check if the part is a Month (only grab the first one to avoid confusing numbers)
        elif p in month_map and month is None:
            month = month_map[p]
            if first_date_idx is None:
                first_date_idx = i

    # 3. Everything before the first date element is the Station name
    if first_date_idx is not None:
        station_parts = parts[:first_date_idx]
        station = " ".join(station_parts).strip()
    else:
        station = None

    return station, month, year

def extract_month_year_from_xlsx(filename):
    name = filename.lower()
    month_match = re.search(r"(jan(?:uary)?|feb(?:ruary)?|march|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)", name)
    year_match = re.search(r"(18\d{2}|19\d{2})", name)
    
    month_map = {"jan":"01", "january":"01", "feb":"02", "february":"02", "march":"03", "apr":"04", "april":"04", "may":"05", "jun":"06", "june":"06", "jul":"07", "july":"07", "aug":"08", "august":"08", "sep":"09", "september":"09", "oct":"10", "october":"10", "nov":"11", "november":"11", "dec":"12", "december":"12"}
    
    month = month_map.get(month_match.group(0), None) if month_match else None
    year = year_match.group(0) if year_match else None
    return month, year

def find_header_index(rows):
    for i, r in enumerate(rows):
        if not r: continue
        joined = " ".join(cell.strip().lower() for cell in r if cell)
        if "barometer" in joined and ("temperature" in joined or "temp" in joined):
            return i
            
    for i, r in enumerate(rows):
        if not r: continue
        joined = " ".join(cell.strip().lower() for cell in r if cell)
        if "day" in joined and "remarks" in joined and "wind" in joined:
             return i
    raise ValueError("Header row not found")

def load_csv_data(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        all_rows = list(reader)
    if not all_rows:
        return pd.DataFrame()
    try:
        header_idx = find_header_index(all_rows)
    except ValueError:
        header_idx = CSV_ROW_START
        if header_idx >= len(all_rows):
            return pd.DataFrame()
        
    header_row = all_rows[header_idx]
    data_rows = all_rows[header_idx + 1:]
    df = pd.DataFrame(data_rows, columns=header_row)
    if CSV_COL_START > 0 and CSV_COL_START < len(df.columns):
        df = df.iloc[:, CSV_COL_START:]
    df = df.reset_index(drop=True)
    return coerce_numeric(df)

def load_xlsx_station_sheet(path, station, data_year):
    if station is None: return None
    try:
        xls = pd.ExcelFile(path)
    except Exception: return None

    if data_year is not None and int(data_year) < 1883:
        current_row_start = XLSX_ROW_START_PRE_1883
    else:
        current_row_start = XLSX_ROW_START_DEFAULT

    # Strip ALL punctuation and spaces for a highly aggressive match
    station_key = re.sub(r'[^a-z0-9]', '', station.lower())
    
    # ---------------------------------------------------------
    # STATION ALIASES 
    # Mapped in multiple directions using lists.
    # ---------------------------------------------------------
    aliases = {
        "birrcastle": ["parsonstown"],
        "parsonstown": ["birrcastle"],
        "douglas": ["cronkbourne", "cronkbournedouglas"],
        "cronkbourne": ["douglas", "cronkbournedouglas"],
        "cronkbournedouglas": ["cronkbourne", "douglas"]
    }

    # Create a list of acceptable names to search for
    search_keys = [station_key]
    if station_key in aliases:
        # CRITICAL FIX: Must be .extend() so it adds the items, not the whole list!
        search_keys.extend(aliases[station_key]) 

    best_sheet = None
    best_ratio = 0.0

    for sheet in xls.sheet_names:
        sheet_key = re.sub(r'[^a-z0-9]', '', sheet.lower())
        
        exact_match_found = False
        
        for skey in search_keys:
            # Check Exact or Substring
            if skey == sheet_key or (skey in sheet_key) or (sheet_key in skey):
                best_sheet = sheet
                exact_match_found = True
                break
                
            # Check Fuzzy Match
            ratio = SequenceMatcher(None, skey, sheet_key).ratio()
            if ratio > 0.85 and ratio > best_ratio:
                best_ratio = ratio
                best_sheet = sheet
                
        # If we found an exact/substring match, stop checking other sheets
        if exact_match_found:
            break
            
    if best_sheet:
        try:
            df = pd.read_excel(path, sheet_name=best_sheet, header=None)
            df = df.iloc[current_row_start:, XLSX_COL_START:].reset_index(drop=True)
            return coerce_numeric(df)
        except Exception: return None
    return None

def get_decimal_place_name(mag):
    """ converts mathematical magnitude to human readable decimal place """
    if mag is None: return ""
    mapping = {
        3: "Thousands (1,000s)",
        2: "Hundreds (100s)",
        1: "Tens (10s)",
        0: "Ones (1s)",
        -1: "Tenths (0.1s)",
        -2: "Hundredths (0.01s)",
        -3: "Thousandths (0.001s)",
        -4: "Ten-Thousandths (0.0001s)"
    }
    return mapping.get(mag, f"10^{mag} place")

def compare_data(df1, df2):
    """
    Compares two dataframes cell by cell.
    If the CSV cell is empty, this is not counted in the total number of cells by which accuracy is measured
    Only compare CSV cells that have values with XLSX manual transcriptions
    Returns: total_cells, match_count, diff_list, column_stats_dict
    """
    rows = min(df1.shape[0], df2.shape[0])
    cols = min(df1.shape[1], df2.shape[1])
    total = 0 # initialise total
    matches = 0
    non_wind_total = 0
    non_wind_matches = 0
    total_char_pct_sum = 0.0
    diffs = []
    decimal_diffs = []
    
    col_stats = {c: {'total': 0, 'matches': 0} for c in range(cols)}

    for r in range(rows):
        for c in range(cols):
            
            col_stats[c]['total'] += 1

            # check if this column is a wind column
            col_name = TARGET_HEADERS[c] if c < len(TARGET_HEADERS) else f"Column_{c}"
            is_wind_col = "wind" in col_name.lower()

            if not is_wind_col:
                non_wind_total += 1

            v1 = df1.iat[r, c]
            v2 = df2.iat[r, c]
            
            s1 = str(v1).strip() if not pd.isna(v1) else ""
            s2 = str(v2).strip() if not pd.isna(v2) else ""

            # If the CSV cell is completely empty (or a hidden Pandas null),
            # skip evaluating it entirely so it doesn't inflate the total.
            # Don't include NA as empty as NA is deliberately inserted into the CSVs in the formatting script
            s1_empty_check = s1.upper().replace('\u200b', '').replace('\xa0', '').strip()
            if s1_empty_check == "" or s1_empty_check in ['NAN', 'NONE', 'NULL', '<NA>', '#N/A']:
                continue 
            
            # The CSV cell has a value, proceed with scoring
            total += 1
            col_stats[c]['total'] += 1

            # different dash characters will match
            s1 = s1.replace("–", "-").replace("—", "-")
            s2 = s2.replace("–", "-").replace("—", "-")

            is_match = False
            char_match_pct = 0.0
            numeric_diff = None
            error_place_name = ""
            
            s1_clean = re.sub(r'[^A-Za-z0-9\-\.]', '', s1.upper())
            s2_clean = re.sub(r'[^A-Za-z0-9\-\.]', '', s2.upper())
            
            # Master list of all things that mean "Empty Cell"
            null_equivalents = ["", "NA", "ND", "NAN", "NONE", "NULL", "-"]

            # Check if text is a null equivalent
            is_s1_null = s1_clean in null_equivalents
            is_s2_null = s2_clean in null_equivalents
            
            # Check if value mathematically equals 0
            is_s1_zero = False
            try:
                if float(s1.replace("(", "").replace(")", "")) == 0.0: is_s1_zero = True
            except ValueError: pass
            
            is_s2_zero = False
            try:
                if float(s2.replace("(", "").replace(")", "")) == 0.0: is_s2_zero = True
            except ValueError: pass

            # check exact string and mapped matches
            if s1 == s2:
                is_match = True
            elif s1.replace("(", "").replace(")", "").upper() == s2.replace("(", "").replace(")", "").upper():
                is_match = True
            # Explicitly treat blank, NA, and ND interchangeably
            # elif s1.upper() in ["", "NA", "ND", "-", "NULL", "---"] and s2.upper() in ["", "NA", "ND"]:
            # "", "NA", "ND", "NULL", "?"
            elif is_s1_null and is_s2_null:
                is_match = True
            elif s1.upper() in ["NA", "?"] and s2.upper() in ["", "NA", "ND", "*ND", "ND*"]:
                is_match = True
            elif s1.lower() in ["calm"] and s2.lower() in ["calml"]:
                is_match = True
            elif s2.upper() == "ND" and s1 in ["0", "0.0"]:
                is_match = True
            elif s2.lower() == "means" and s1.lower() == "mean":
                is_match = True
            
            # check numeric match and numeric difference magnitude
            if not is_match:
                try:
                    f1 = float(s1)
                    f2 = float(s2)
                    numeric_diff = abs(f1-f2)
                    if numeric_diff < 0.000001:
                        is_match = True
                    else:
                        # find where the error is (e.g., -1 is Tenths place)
                        error_magnitude = math.floor(math.log10(numeric_diff))
                        error_place_name = get_decimal_place_name(error_magnitude)
                except ValueError:
                    pass # Not both numeric, so it stays a string mismatch

            # finalise and record stats
            if is_match:
                matches += 1
                col_stats[c]['matches'] += 1
                char_match_pct = 100.0

                # count match towrads non-wind metric
                if not is_wind_col:
                    non_wind_matches += 1
            else:
                # Calculate character-by-character string similarity ratio
                char_match_pct = SequenceMatcher(None, s1, s2).ratio() * 100
                
                # Append standard diff
                diffs.append((r, c, v1, v2, round(char_match_pct, 2), numeric_diff))
                
                # Append numeric decimal diff
                if numeric_diff is not None:
                    decimal_diffs.append((r, c, v1, v2, numeric_diff, error_place_name))

            total_char_pct_sum += char_match_pct
    
    # calculates average character match across whole df
    avg_char_match = (total_char_pct_sum / total) if total > 0 else 0

    return total, matches, non_wind_total, non_wind_matches, diffs, decimal_diffs, col_stats, avg_char_match

# -------------------- MAIN LOOP --------------------

summary_rows = []
diff_rows = []
decimal_errors_rows = [] 
diff_counts_rows = [] 
perfect_cols_rows = [] 

global_col_stats = {}

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

xlsx_files = list(XLSX_FOLDER.glob("*.xlsx"))
print(f"Found {len(xlsx_files)} manual transcription files.")

csv_files = list(input_dir.rglob("*.csv"))
print(f"Found {len(csv_files)} CSV files to check.")

for csv_file in csv_files:
    station, csv_month, csv_year = extract_from_csv(csv_file.name)
    if not all([station, csv_month, csv_year]):
        continue

    for xlsx in xlsx_files:
        xlsx_month, xlsx_year = extract_month_year_from_xlsx(xlsx.name)

        if (csv_month == xlsx_month and csv_year == xlsx_year):
            
            print(f"Comparing {csv_file.name} -> {xlsx.name} [{station}]")

            try:
                df_csv = load_csv_data(csv_file)
                df_xlsx = load_xlsx_station_sheet(xlsx, station, csv_year)
            except Exception as e:
                print(f"ERROR: {e}")
                continue

            if df_xlsx is None:
                print(f"No matching sheet for station '{station}' in {xlsx.name}")
                continue

            # Perform comparison
            total, matches, nw_tot, nw_match, diffs, decimal_diffs, file_col_stats, avg_char_match = compare_data(df_csv, df_xlsx)
            
            diff_count = len(diffs)
            percent = round((matches / total) * 100, 2) if total else 0
            # percentage agreement if wind columns not considered:
            nw_percent = round((nw_match / nw_tot) * 100, 2) if nw_tot > 0 else 0

            # 1. Add to Summary Report (Added Station, Year, Month for sorting)
            summary_rows.append({
                "station": station.title(), # Looks cleaner in reports
                "year": csv_year,
                "month": csv_month,
                "csv_file": csv_file.name,
                "xlsx_file": xlsx.name,
                "total_cells": total,
                "matching_cells": matches,
                "percent_agreement_cell_level": percent,
                "percent_agreement_cell_level_nowind": nw_percent,
                "avg_character_match_percent": round(avg_char_match, 2)
            })

            # 2. Add to Difference Counts Report
            diff_counts_rows.append({
                "station": station.title(),
                "year": csv_year,
                "month": csv_month,
                "csv_file": csv_file.name,
                "xlsx_file": xlsx.name,
                "number_of_differences": diff_count
            })

            # 3. Add to Differences Report
            for r, c, v1, v2, char_pct, num_diff in diffs:
                diff_rows.append({
                    "csv_file": csv_file.name,
                    "xlsx_file": xlsx.name,
                    "row": r + 1,
                    "column": c,
                    "csv_value": v1,
                    "xlsx_value": v2,
                    "character_match_percent": char_pct,
                    "numeric_difference": num_diff
                })
            
            # 4. Add to Decimal Errors Report
            for r, c, v1, v2, num_diff, err_place in decimal_diffs:
                decimal_errors_rows.append({
                    "station": station.title(),
                    "year": csv_year,
                    "month": csv_month,
                    "csv_file": csv_file.name,
                    "xlsx_file": xlsx.name,
                    "row": r + 1,
                    "column": c,
                    "csv_value": v1,
                    "xlsx_value": v2,
                    "numeric_difference": num_diff,
                    "error_place": err_place
                })
            
            # 5. Handle Column Statistics
            for col_idx, stats in file_col_stats.items():
                if col_idx not in global_col_stats:
                    global_col_stats[col_idx] = {'total': 0, 'matches': 0}
                
                if stats['total'] > 0:
                    global_col_stats[col_idx]['total'] += stats['total']
                    global_col_stats[col_idx]['matches'] += stats['matches']
                    
                    if stats['matches'] == stats['total']:
                        col_name = TARGET_HEADERS[col_idx] if col_idx < len(TARGET_HEADERS) else f"Column_{col_idx}"
                        perfect_cols_rows.append({
                            "station": station.title(),
                            "year": csv_year,
                            "month": csv_month,
                            "csv_file": csv_file.name,
                            "xlsx_file": xlsx.name,
                            "column_index": col_idx,
                            "column_name": col_name
                        })

# ---------------- SAVING REPORTS ---------------- #

# 1. Summary Report (Sorted)
df_summary = pd.DataFrame(summary_rows)
if not df_summary.empty:
    df_summary = df_summary.sort_values(by=['station', 'year', 'month'])
df_summary.to_csv(OUTPUT_SUMMARY, index=False)

# 2. Differences Report
pd.DataFrame(diff_rows).to_csv(OUTPUT_DIFFS, index=False)

# 3. Difference Count Report (Sorted)
df_counts = pd.DataFrame(diff_counts_rows)
if not df_counts.empty:
    df_counts = df_counts.sort_values(by=['station', 'year', 'month'])
df_counts.to_csv(OUTPUT_DIFF_COUNTS, index=False)

# 4. Perfect Columns Report (Sorted)
df_perfect = pd.DataFrame(perfect_cols_rows)
if not df_perfect.empty:
    df_perfect = df_perfect.sort_values(by=['station', 'year', 'month', 'column_index'])
df_perfect.to_csv(OUTPUT_PERFECT_COLS, index=False)

# 5. Decimal Errors Report (NEW)
df_decimal = pd.DataFrame(decimal_errors_rows)
if not df_decimal.empty:
    df_decimal = df_decimal.sort_values(by=['station', 'year', 'month', 'row', 'column'])
df_decimal.to_csv(OUTPUT_DECIMAL_ERRORS, index=False)

# 6. Column Accuracy Report (Global)
col_summary_rows = []
for col_idx in sorted(global_col_stats.keys()):
    stats = global_col_stats[col_idx]
    
    if col_idx < len(TARGET_HEADERS):
        col_name = TARGET_HEADERS[col_idx]
    else:
        col_name = f"Column_{col_idx}"
    
    tot = stats['total']
    match = stats['matches']
    pct = round((match / tot) * 100, 2) if tot > 0 else 0
    
    col_summary_rows.append({
        "column_index": col_idx,
        "column_name": col_name,
        "total_cells_checked": tot,
        "matching_cells": match,
        "percent_agreement": pct
    })

pd.DataFrame(col_summary_rows).to_csv(OUTPUT_COL_SUMMARY, index=False)

print(f"\nProcessing complete.")
print(f"Summary saved to: {OUTPUT_SUMMARY}")
print(f"Differences saved to: {OUTPUT_DIFFS}")
print(f"Column stats saved to: {OUTPUT_COL_SUMMARY}")
print(f"Diff Counts saved to: {OUTPUT_DIFF_COUNTS}")
print(f"Decimal Errors saved to: {OUTPUT_DECIMAL_ERRORS}")
print(f"Perfect Columns saved to: {OUTPUT_PERFECT_COLS}")

# ---------------- CONSOLE OUTPUT ---------------- #

print("\n" + "="*50)
print("FILES WITH LESS THAN 50% AGREEMENT:")
print("="*50)

if not df_summary.empty:
    low_agreement_df = df_summary[df_summary['percent_agreement_cell_level'] < 50]

    if not low_agreement_df.empty:
        for index, row in low_agreement_df.iterrows():
            print(f"File: {row['csv_file']} | Agreement: {row['percent_agreement_cell_level']}% | Char Agreement: {row['avg_character_match_percent']}%")
    else:
        print("No files found with agreement below 50%.")
else:
    print("No comparisons were performed (Dataframes empty).")