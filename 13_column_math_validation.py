import pandas as pd
import numpy as np
import re
import os
import csv
import calendar
from pathlib import Path
import configparser
from difflib import SequenceMatcher

''''
all columns except day have either average or sum in final row
rain and sunshine (sunshine only for 1906-1911 inclusive, from 1912-1921 sunshine is averaged in final row): 
all other columns, except wind dir (NA): average (confirmed in SSO books to be arithmetic mean)
'''
def clean_column_name(col):
    """Must exactly match script 2's clean_column_name for QC key matching to work."""
    c = str(col)
    c = re.sub(r'[^\x20-\x7E]', '', c)
    c = re.sub(r'\s+', ' ', c)
    return c.strip()
input_dir = Path("")
output_dir = Path("")
output_dir.mkdir(parents=True, exist_ok=True)


# summary
output_summary = output_dir / "column_math_summary.csv"

# lists file and column names with source JPG
all_errors_detailed_report = output_dir / "all_errors_report.csv"
columns_rounding_errors_report = output_dir / "columns_rounding_errors.csv" # columns that don't perfectly match but are within the set tolerance for rounding errors
columns_math_mismatch_report = output_dir / "columns_math_mismatch.csv" # columns that don't match and are beyond the set tolerance for rounding errors
columns_qc_pass_report = output_dir / "columns_qc_pass.csv" # columns that pass QC: no math errors + rounding errors = QC pass. This is passed into the SEF conversion script.

# counts how many columns
column_count_no_math_errors = output_dir / "column_count_no_math_errors.csv" # count of perfect columns
column_count_rounding_errors = output_dir / "column_count_rounding_errors.csv" # count of columns that don't perfectly match but are within the set tolerance for rounding errors
column_count_mismatch_errors = output_dir / "column_count_mismatch_errors.csv" # count of columns that don't match and are beyond the set tolerance for rounding errors
column_count_qc_pass = output_dir / "column_count_qc_pass.csv" # count of columns that pass QC (count of no math errors + count of rounding errors)

# safety reports
columns_skipped_no_mean_report = output_dir / "columns_skipped_no_mean.csv" # columns that had no mean
columns_skipped_no_data_report = output_dir / "columns_skipped_no_data.csv" # columns that had no data
skipped_no_mean_no_data_report = output_dir / "columns_skipped_no_mean_no_data.csv" # columns that had no mean and no data
duplicate_columns_report = output_dir / "duplicate_columns.csv" # columns with exact header duplicates
skipped_files_report = output_dir / "skipped_files.csv" # skipped files
excluded_wind_direction_report = output_dir / "excluded_wind_direction.csv" # count wind direction columns that were purposely excluded from column math

def clean_column_name(col):
    # remove non-ASCII characters for clean column grouping in reports
    # COMMENT THIS BACK OUT ONCE YOU HAVE FIXED ENCODING WHEN SAVING CSVS IN FORMATTING SCRIPT TO CHECK IT WORKS
    c = str(col)
    c = re.sub(r'[^\x20-\x7E]', '', c)
    c = re.sub(r'\s+', ' ', c)
    return c.strip()

def extract_year(filename):
    """ Extract the year from the filename using regex. """
    match = re.search(r"(18\d{2}|19\d{2})", str(filename))
    if match:
        return int(match.group(1))
    return 1890  # Default to middle period if unknown

def extract_month(filename):
    """ Extracts the month as an integer (1-12) from the filename. """
    name = str(filename).lower()
    
    # 1. Check for numeric month immediately following the year (e.g., "_1884_01")
    # This looks for a 4-digit year, an underscore, and grabs the 2 digits after it.
    match_num = re.search(r"(?:18|19|20)\d{2}_(\d{2})", name)
    if match_num:
        month_int = int(match_num.group(1))
        if 1 <= month_int <= 12:
            return month_int

    # 2. Fallback to text names (January, Jan, etc.) for older filenames
    months = {
        'january': 1, 'jan': 1, 'february': 2, 'feb': 2,
        'march': 3, 'mar': 3, 'april': 4, 'apr': 4,
        'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7,
        'august': 8, 'aug': 8, 'september': 9, 'sep': 9,
        'october': 10, 'oct': 10, 'november': 11, 'nov': 11,
        'december': 12, 'dec': 12
    }
    for m, val in months.items():
        if re.search(fr'\b{m}\b', name):
            return val
            
    return None

#
excluded_columns = ['direction', 'veer', 'north']

def is_summed_column(col_str, target_year):
    """
    returns True if column should be summed, False if column should be averaged (mean)
    """
    col_clean = col_str.lower().strip()

    # summed columns
    if "rain" in col_clean:
        return True

    # sunshine is summed 1906-1911 inclusive, averaged from 1912-1921
    if "sunshine" in col_clean:
        if 1906 <= target_year <= 1911:
            return True
        else:
            return False
    
    # default all other columns to average
    return False

# --- decimal place and tolerance switchboard ---
def get_variable_decimal_place_tolerance(col_str, target_year):
    """
    Returns decimal place and tolerance for rounding errors based on column name and year
    """

    col_clean = col_str.lower().strip()

    # air pressure
    if "barometer" in col_clean:
        if target_year <= 1911:
            # return 3, 0.002
            return 3, 0.01
        else:
            # return 1, 0.2
            return 1, 0.1

    if "air pressure" in col_clean:
        # return 1, 0.2
        return 1, 0.1

    # temperature
    elif "temp" in col_clean:
        # return 1, 0.2
        # return 1, 0.05
        if target_year <= 1911:
            return 1, 0.1
        else:
            return 1, 0.1
    
    # depression of wetbulb temperature
    elif "dep" in col_clean or "wet" in col_clean:
        # return 1, 0.2
        return 1, 0.05

    # vapour pressure
    elif "vapour" in col_clean or "tension" in col_clean:
        if target_year <= 1911:
            # return 3, 0.002
            return 3, 0.01
        else:
            # return 1, 0.2
            return 1, 0.1
    
    # relative humidity (humidity percentage)
    elif "percent" in col_clean or "relative" in col_clean:
        if (target_year <= 1874 or target_year >= 1908): 
            # return 0, 1
            return 0, 0
        else:
            # return 1, 0.2
            return 1, 0
    
    # wind force/velocity/speed
    elif "wind" in col_clean or "force" in col_clean or "velocity" in col_clean or "speed" in col_clean:
        if (target_year <= 1911 or 1912 <= target_year): 
            # return 1, 0.2
            return 1, 0.05

    # cloud
    elif "cloud" in col_clean:
        return 1, 0.1
    
    # rain
    elif "rain" in col_clean:
        # no tolerance as final row value is a sum
        if target_year <= 1911: 
            return 3, 0
        if target_year >= 1912:
            return 1, 0       

    # sunshine
    elif "sunshine" in col_clean:
        if 1906 <= target_year <= 1911:
            # for these years, final row value is a sum, so no tolerance
            return 0, 0
        else:
            # for these years, final row value is an average
            return 2, 0.02
    
    # min temp on grass
    elif "grass" in col_clean:
        # return 1, 0.2
        return 1, 0.1
    
    # fallback
    # return 3, 0.002
    return 3, 0.01


def find_header_index(rows):
    for i, r in enumerate(rows):
        if not r: continue
        joined = " ".join(cell.strip().lower() for cell in r if pd.notna(cell) and str(cell).strip())
        if ("barometer" in joined or "pressure" in joined) and ("temperature" in joined or "temp" in joined): 
            return i
    for i, r in enumerate(rows):
        if not r: continue
        joined = " ".join(cell.strip().lower() for cell in r if pd.notna(cell) and str(cell).strip())
        if "day" in joined and ("barometer" in joined or "pressure" in joined) and "temperature" in joined and "wind" in joined: 
            return i
    raise ValueError("Header row not found")


def load_csv(file_path):
    """ Loads CSV, finds the header, and extracts the source JPG from metadata. """
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        all_rows = list(reader)
        
        source_jpg = None
        if not all_rows:
            return pd.DataFrame(), source_jpg, "empty_file"   # reason
        
        for row in all_rows[:5]:
            row_str = ",".join(str(c) for c in row)
            match = re.search(r'# SOURCE_FILENAME\s*,\s*([^,]+)', row_str, re.IGNORECASE)
            if match:
                source_jpg = match.group(1).strip()
                break

        try:
            header_idx = find_header_index(all_rows)
        except ValueError:
            return pd.DataFrame(), source_jpg, "header_not_found"   # reason
        
        header_row = all_rows[header_idx]
        data_rows = all_rows[header_idx + 1:]
        
        return pd.DataFrame(data_rows, columns=header_row), source_jpg, None   # if successful, reason=None

def standardize_column_name(raw_name):
    c = str(raw_name).lower()
    
    if "barom" in c: base = "Barometer"
    elif "air pressure" in c: base = "Air Pressure"
    elif "grass" in c: base = "Temp. on Grass"
    elif "wet" in c or "dep" in c: base = "Wetbulb Depression"
    elif "temp" in c: base = "Temperature"
    elif "vapour" in c or "tension" in c: base = "Vapour pressure"
    elif "per-cent" in c or "percent" in c or "relative" in c: base = "Relative Humidity"
    elif "cloud" in c: base = "Cloud"
    elif "force" in c or "velocity" in c or "speed" in c: base = "Wind"
    elif "sun" in c: base = "Sunshine"
    elif "rain" in c: base = "Rain"
    else: base = str(raw_name).strip() 
    
    mod = ""
    if "min" in c: mod = " Min"
    elif "max" in c: mod = " Max"
    elif re.search(r"(8|9)\s*a\.?m\.?", c) or " a.m" in c or " am" in c.split() or "9 h" in c: 
        mod = " 9am"
    elif re.search(r"(4|9|21)\s*p\.?m\.?", c) or " p.m" in c or " pm" in c.split() or "21 h" in c: 
        mod = " 9pm"
    elif "mid" in c: 
        mod = " Midnight"
        
    return f"{base}{mod}"

def analyse_spreadsheet(file_path, logs):
    try: 
        file_year = extract_year(os.path.basename(file_path))
        file_month = extract_month(os.path.basename(file_path))

        df, source_jpg, skip_reason = load_csv(file_path)
        if df.empty:
            print(f"  [!] Skipping file — {skip_reason}: {os.path.basename(file_path)}")
            logs['skipped_files'].append({                                                  
                "File": os.path.basename(file_path),
                "Reason": skip_reason
            })
            logs['error_count'] += 1   # CHANGED: now counted, was silent before
            return
            
        df.columns = [clean_column_name(c) for c in df.columns]

        # Safety: detect and handle duplicate headers
        dup_mask = pd.Index(df.columns).duplicated(keep=False)
        if dup_mask.any():
            dup_names = sorted(set(c for c, is_dup in zip(df.columns, dup_mask) if is_dup))
            print(f"  [!] Duplicate column headers in {os.path.basename(file_path)}: {dup_names}")
            logs['duplicate_columns'].append({
                "File": os.path.basename(file_path),
                "Source JPG": source_jpg,
                "Duplicate Columns": ", ".join(dup_names)
            })
            # Rename duplicates with positional suffixes so every column is evaluated separately
            # e.g. "Temperature", "Temperature" -> "Temperature", "Temperature__dup2"
            seen = {}
            new_cols = []
            for c in df.columns:
                if c in seen:
                    seen[c] += 1
                    new_cols.append(f"{c}__dup{seen[c]}")
                else:
                    seen[c] = 1
                    new_cols.append(c)
            df.columns = new_cols

        # day column is the first column, left to right
        day_col_name = df.columns[0]
        
        # locate mean row
        def is_mean_row(x):
            s = str(x).strip().lower()
            if "mean pressure" in s: return False
            exact_targets = ['m', 'm.', 'mean', 'means', 'total', 'totals']
            if s in exact_targets: return True
            fuzzy_targets = ['mean', 'means', 'total', 'totals']
            return any(SequenceMatcher(None, s, t).ratio() >= 0.7 for t in fuzzy_targets)

        mask = df[day_col_name].apply(is_mean_row)
        
        if mask.any():
            mean_row_index = df.index[mask][0]
            row_label = str(df.iloc[mean_row_index][day_col_name]).strip()
        else:
            # FALLBACK LOGIC
            if file_month:
                # Calculate exactly how many days are in this specific month/year
                days_in_month = calendar.monthrange(file_year, file_month)[1]
                mean_row_index = days_in_month
                
                # Check if dataframe actually extends this far
                if mean_row_index < len(df):
                    raw_val = str(df.iloc[mean_row_index][day_col_name]).strip()
                    row_label = f"{raw_val} (Fallback Index {mean_row_index})"
                else:
                    print(f"  [!] 'Mean' row missing & DataFrame too short: {os.path.basename(file_path)}")
                    logs['error_count'] += 1
                    return
            else:
                print(f"  [!] 'Mean' row missing & Month unknown: {os.path.basename(file_path)}")
                logs['error_count'] += 1
                return
        
        df_data = df.iloc[:mean_row_index].copy()
        series_verification = df.iloc[mean_row_index]

        count_total_cols = 0
        count_rounding_errors = 0
        count_failures = 0

        for col in df.columns:
            if col == day_col_name:
                continue
            col_str = str(col).lower().strip()
            if any(keyword in col_str for keyword in excluded_columns):
                logs['excluded_wind_direction'].append({
                    "File": os.path.basename(file_path),
                    "Source JPG": source_jpg,
                    "Year": file_year,
                    "Column": col,
                    "Row Label": row_label
                })
                continue
            
            # --- get transcribed average/sum from mean row index ---
            val_spreadsheet = series_verification[col]
            if isinstance(val_spreadsheet, pd.Series):
                val_spreadsheet = val_spreadsheet.iloc[0]

            # remove everything that is not a digit, decimal or negative sign from the transcribed value
            val_spreadsheet_clean = re.sub(r'[^\d\.-]', '', str(val_spreadsheet))
            val_spreadsheet_numeric = pd.to_numeric(val_spreadsheet_clean, errors='coerce')
            mean_missing = pd.isna(val_spreadsheet_numeric)   # store as a flag, don't continue yet
            
            # --- get data and count columns ---
            col_data = df_data[col]
            if isinstance(col_data, pd.DataFrame):
                col_data = col_data.iloc[:, 0]
                
            # remove everything that is not a digit, decimal or negative sign from the data
            # eg letters (n's and x's for mins and maxs) and symbols (cloud and weather cols)
            col_data_cleaned = col_data.astype(str).str.replace(r'[^\d\.-]', '', regex=True)
            col_data_numeric = pd.to_numeric(col_data_cleaned, errors='coerce')
            data_missing = col_data_numeric.count() == 0   # store as a flag, don't continue yet

            # --- now decide, with both facts known ---
            if mean_missing and data_missing:
                logs.setdefault('skipped_no_mean_no_data', []).append({
                    "File": os.path.basename(file_path),
                    "Source JPG": source_jpg,
                    "Year": file_year,
                    "Column": col,
                    "Row Label": row_label,
                    "Reason": "no mean/total value AND no daily data"
                })
                continue
            elif mean_missing:
                logs['skipped_no_mean'].append({
                    "File": os.path.basename(file_path),
                    "Source JPG": source_jpg,
                    "Year": file_year,
                    "Column": col,
                    "Row Label": row_label,
                    "Raw Mean Cell Value": val_spreadsheet,
                    "Daily Data Present": True
                })
                continue
            elif data_missing:
                logs['skipped_no_data'].append({
                    "File": os.path.basename(file_path),
                    "Source JPG": source_jpg,
                    "Year": file_year,
                    "Column": col,
                    "Row Label": row_label,
                    "Reason": "no numeric daily values found",
                    "Mean Cell Value": val_spreadsheet
                })
                continue


            count_total_cols += 1

            # --- calculate either mean or sum based on column and year ---
            if is_summed_column(col_str, file_year):
                val_calculated = col_data_numeric.sum()
            else:
                val_calculated = col_data_numeric.mean()
            
            # --- switchboard decimal places and tolerance ---
            required_decimals, allowed_tolerance = get_variable_decimal_place_tolerance(col_str, file_year)

            # --- apply rounding ---
            val_calculated = round(val_calculated, required_decimals)

            # --- compare calculated average/sum with transcribed average/sum, calculate difference ---
            val_spreadsheet = float(val_spreadsheet_numeric)
            diff = round(abs(val_calculated - val_spreadsheet), 5) # eliminates Python float artifacts

            if pd.isna(diff):
                continue

            if diff == 0:
                logs['exact_matches'].append({
                    "File": os.path.basename(file_path),
                    "Source JPG": source_jpg,
                    "Year": file_year,
                    "Column": col,
                    "Row Label": row_label,
                    "Row Index": mean_row_index,
                    "Calculated Value": val_calculated,
                    "Transcribed Value": val_spreadsheet,
                    "Difference": diff,
                    "Tolerance Applied": allowed_tolerance
                })
            elif diff > allowed_tolerance:
                count_failures += 1
                logs['failures'].append({
                    "File": os.path.basename(file_path),
                    "Source JPG": source_jpg,
                    "Year": file_year,
                    "Column": col,
                    "Row Label": row_label,
                    "Row Index": mean_row_index,
                    "Calculated Value": val_calculated,
                    "Transcribed Value": val_spreadsheet,
                    "Difference": diff,
                    "Tolerance Applied": allowed_tolerance
                })
            else:
                count_rounding_errors += 1
                logs['rounding'].append({
                    "File": os.path.basename(file_path),
                    "Source JPG": source_jpg,
                    "Year": file_year,
                    "Column": col,
                    "Row Label": row_label,
                    "Row Index": mean_row_index,
                    "Calculated Value": val_calculated,
                    "Transcribed Value": val_spreadsheet,
                    "Difference": diff,
                    "Tolerance Applied": allowed_tolerance
                })

        if count_total_cols > 0:
            pct_rounding = (count_rounding_errors / count_total_cols) * 100
            pct_failure = (count_failures / count_total_cols) * 100
            
            logs['summary'].append({
                "File": os.path.basename(file_path),
                "Source JPG": source_jpg,
                "Year": file_year,
                "Total Columns Checked": count_total_cols,
                "Rounding errors": count_rounding_errors,
                "Rounding error %": round(pct_rounding, 2),
                "Mismatch errors": count_failures,
                "Mismatch error %": round(pct_failure, 2)
            })

    except Exception as e:
        print(f"Error processing {os.path.basename(file_path)}: {e}")
        logs['error_count'] += 1
        
def save_exact_matches_report(logs, output_path):
    """ Special report for Exact Matches that calculates Totals and Percentages """
    # 1. Combine all logs to get the GRAND TOTAL of every column checked
    all_evaluated = logs['exact_matches'] + logs['rounding'] + logs['failures']
    
    if not all_evaluated:
        print(f"No data to save for {output_path.name}")
        return
        
    # Get total counts
    df_all = pd.DataFrame(all_evaluated)
    df_all['Grouped Column'] = df_all['Column'].apply(standardize_column_name)
    total_counts = df_all['Grouped Column'].value_counts().reset_index()
    total_counts.columns = ['Grouped Column Category', 'Total Evaluated']
    
    # 2. Get the Exact Matches counts
    if logs['exact_matches']:
        df_exact = pd.DataFrame(logs['exact_matches'])
        df_exact['Grouped Column'] = df_exact['Column'].apply(standardize_column_name)
        exact_counts = df_exact['Grouped Column'].value_counts().reset_index()
        exact_counts.columns = ['Grouped Column Category', 'Perfect Matches']
    else:
        # Empty dataframe if no perfect matches exist
        exact_counts = pd.DataFrame(columns=['Grouped Column Category', 'Perfect Matches'])
        
    # 3. Merge them together side-by-side
    merged = pd.merge(total_counts, exact_counts, on='Grouped Column Category', how='left')
    
    # Fill N/A with 0 for columns that had 0 perfect matches
    merged['Perfect Matches'] = merged['Perfect Matches'].fillna(0).astype(int)
    
    # Calculate Percentage
    merged['Perfect Match %'] = ((merged['Perfect Matches'] / merged['Total Evaluated']) * 100).round(2)
    
    # Sort nicely: Most evaluated columns at the top
    merged = merged.sort_values(by=['Total Evaluated', 'Perfect Match %'], ascending=[False, False])
    
    merged.to_csv(output_path, index=False)
    print(f"Saved perfect matches list (with totals) to: {output_path.name}")

def generate_column_stats_report(target_log, all_logs, output_path, metric_name):
    """ Universal function to generate standardized grouped count reports with totals & percentages """
    if not all_logs:
        print(f"No data to save for {output_path.name}")
        return
        
    # 1. Total Evaluated (Baseline across all files)
    df_all = pd.DataFrame(all_logs)
    df_all['Grouped Column'] = df_all['Column'].apply(standardize_column_name)
    total_counts = df_all['Grouped Column'].value_counts().reset_index()
    total_counts.columns = ['Grouped Column Category', 'Total Evaluated']
    
    # 2. Target Counts (e.g. mismatches, rounding errors, exact matches, QC passes)
    if target_log:
        df_target = pd.DataFrame(target_log)
        df_target['Grouped Column'] = df_target['Column'].apply(standardize_column_name)
        target_counts = df_target['Grouped Column'].value_counts().reset_index()
        target_counts.columns = ['Grouped Column Category', f'Frequency of {metric_name}']
    else:
        target_counts = pd.DataFrame(columns=['Grouped Column Category', f'Frequency of {metric_name}'])
        
    # 3. Merge and calculate percentages
    merged = pd.merge(total_counts, target_counts, on='Grouped Column Category', how='left')
    merged[f'Frequency of {metric_name}'] = merged[f'Frequency of {metric_name}'].fillna(0).astype(int)
    merged[f'{metric_name} %'] = ((merged[f'Frequency of {metric_name}'] / merged['Total Evaluated']) * 100).round(2)
    
    # 4. Sort (most evaluated first, highest % second)
    merged = merged.sort_values(by=['Total Evaluated', f'{metric_name} %'], ascending=[False, False])
    
    # 5. For preference, save based on extension
    if output_path.suffix.lower() == '.csv':
        merged.to_csv(output_path, index=False)
    else:
        merged.to_excel(output_path, index=False, engine='openpyxl')
    
    print(f"Saved {metric_name} stats to: {output_path.name}")

def main():
    logs = {
        'summary': [],
        'rounding': [],
        'failures': [],
        'exact_matches': [],
        'skipped_no_mean': [],      # column had no parseable mean/total value
        'skipped_no_data': [],      # column had no parseable daily data
        'duplicate_columns': [],    # exact header appeared more than once in file
        'skipped_files': [],        # whole file skipped, with a reason
        'skipped_no_mean_no_data': [], # skipped column that had no mean and no data
        'excluded_wind_direction': [],
        'error_count': 0 
    }
    
    print(f"Scanning {input_dir}")
    file_count = 0
    for root, dirs, files in os.walk(input_dir):
        for file in files:
            if file.lower().endswith('.csv'):
                full_path = os.path.join(root, file)
                analyse_spreadsheet(full_path, logs)
                file_count += 1
                
    print(f"\n--- PROCESSING COMPLETE ---")
    print(f"Total files checked: {file_count}")
    
    if logs['error_count'] > 0:
        print(f"⚠️ Files that encountered a processing error: {logs['error_count']}")
    else:
        print("✅ No processing errors encountered!")
    
    # Print skip counts so they can't be missed
    total_skipped_cols = len(logs['skipped_no_mean']) + len(logs['skipped_no_data'])
    if total_skipped_cols > 0:
        print(f"⚠️ Columns skipped (no mean value: {len(logs['skipped_no_mean'])}, "
              f"no daily data: {len(logs['skipped_no_data'])})")
    if logs['duplicate_columns']:
        print(f"⚠️ Files with duplicate column headers: {len(logs['duplicate_columns'])}")
    
    print("\n--- SAVING REPORTS ---")
    
    if logs['summary']:
        pd.DataFrame(logs['summary']).to_csv(output_summary, index=False)
        print(f"Saved summary report to: {output_summary.name}")
        
    if logs['rounding']:
        pd.DataFrame(logs['rounding']).to_csv(columns_rounding_errors_report, index=False)
        print(f"Saved rounding report to: {columns_rounding_errors_report.name}")
    
    if logs['failures']:
        pd.DataFrame(logs['failures']).to_csv(columns_math_mismatch_report, index=False)
        print(f"Saved mismatch report to: {columns_math_mismatch_report.name}")
    
    if logs['skipped_no_mean']:
        pd.DataFrame(logs['skipped_no_mean']).to_csv(columns_skipped_no_mean_report, index=False)
        print(f"Saved skipped-no-mean report to: {columns_skipped_no_mean_report.name}")

    if logs['skipped_no_data']:
        pd.DataFrame(logs['skipped_no_data']).to_csv(columns_skipped_no_data_report, index=False)
        print(f"Saved skipped-no-data report to: {columns_skipped_no_data_report.name}")

    if logs['duplicate_columns']:
        pd.DataFrame(logs['duplicate_columns']).to_csv(duplicate_columns_report, index=False)
        print(f"Saved duplicate-columns report to: {duplicate_columns_report.name}")

    if logs['skipped_files']:
        pd.DataFrame(logs['skipped_files']).to_csv(skipped_files_report, index=False)
        print(f"Saved skipped-files report to: {skipped_files_report.name}")
    
    if logs.get('skipped_no_mean_no_data'):
        pd.DataFrame(logs['skipped_no_mean_no_data']).to_csv(skipped_no_mean_no_data_report, index=False)
        print(f"Saved skipped-no-mean-no-data report to: {skipped_no_mean_no_data_report.name}")
    
    if logs['excluded_wind_direction']:
        pd.DataFrame(logs['excluded_wind_direction']).to_csv(excluded_wind_direction_report, index=False)
        print(f"Saved excluded wind-direction report to: {excluded_wind_direction_report.name}")

    all_errors = []
    for r in logs['rounding']:
        r_copy = r.copy()
        r_copy['Error Type'] = 'Rounding Error'
        all_errors.append(r_copy)
    for f in logs['failures']:
        f_copy = f.copy()
        f_copy['Error Type'] = 'Mismatch Error'
        all_errors.append(f_copy)

    if all_errors:
        df_all_errors = pd.DataFrame(all_errors)
        cols = ["File", "Source JPG", "Year", "Error Type", "Column", "Row Label", "Row Index", "Calculated Value", "Transcribed Value", "Difference", "Tolerance Applied"]
        df_all_errors = df_all_errors[cols]
        df_all_errors.to_csv(all_errors_detailed_report, index=False)
        print(f"Saved combined detailed errors to: {all_errors_detailed_report.name}")
    
    # QC = pass reports (exact matches + rounding errors) ---
    qc_pass_list = []
    for em in logs['exact_matches']:
        em_copy = em.copy()
        em_copy['QC Status'] = 'Exact Match'
        qc_pass_list.append(em_copy)
    for r in logs['rounding']:
        r_copy = r.copy()
        r_copy['QC Status'] = 'Rounding Error'
        qc_pass_list.append(r_copy)
        
    if qc_pass_list:
        # Save detailed QC pass log (filename, column name, etc)
        df_qc_pass = pd.DataFrame(qc_pass_list)
        cols = ["File", "Source JPG", "Year", "QC Status", "Column", "Row Label", "Row Index", "Calculated Value", "Transcribed Value", "Difference", "Tolerance Applied"]
        df_qc_pass = df_qc_pass[cols]
        df_qc_pass.to_csv(columns_qc_pass_report, index=False)
        print(f"Saved detailed QC Pass report to: {columns_qc_pass_report.name}")

    if logs['excluded_wind_direction']:
        print(f"Wind-direction columns excluded from math QC: {len(logs['excluded_wind_direction'])}")
    
    all_evaluated = logs['exact_matches'] + logs['rounding'] + logs['failures']

    print("\n--- Generating Column Count Lists ---")
    generate_column_stats_report(logs['failures'], all_evaluated, column_count_mismatch_errors, "Mismatch Errors")
    generate_column_stats_report(logs['rounding'], all_evaluated, column_count_rounding_errors, "Rounding Errors")
    generate_column_stats_report(logs['exact_matches'], all_evaluated, column_count_no_math_errors, "Exact Matches")
    generate_column_stats_report(qc_pass_list, all_evaluated, column_count_qc_pass, "QC Pass")

if __name__ == "__main__":
    main()
