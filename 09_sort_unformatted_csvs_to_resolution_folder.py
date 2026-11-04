import re
from pathlib import Path
import shutil
import unicodedata
from difflib import SequenceMatcher
import configparser
import csv
import io
from datetime import datetime

config_path = Path("") # config with paths
config = configparser.ConfigParser()
config.read(config_path)

raw_input_paths = config["Paths"]["input_folders_sorting"]
input_dirs = [Path(p.strip()) for p in raw_input_paths.split('\n') if p.strip()]

parent_output_dir = Path(config["Paths"]["parent_output_dir_sorting"])

# --- Define all output roots ---
daily_root = parent_output_dir / "Daily"
monthly_root = parent_output_dir / "Monthly"
anemometer_root = parent_output_dir / "Anemometer"
annual_root = parent_output_dir / "Annual"
sunshine_root = parent_output_dir / "Sunshine"

daily_root.mkdir(parents=True, exist_ok=True)
monthly_root.mkdir(parents=True, exist_ok=True)
anemometer_root.mkdir(parents=True, exist_ok=True)
annual_root.mkdir(parents=True, exist_ok=True)
sunshine_root.mkdir(parents=True, exist_ok=True)


# --- Set up the reports (Append Mode) ---
run_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

report_file_path = parent_output_dir / "sparse_files_report.txt"
with open(report_file_path, "a", encoding="utf-8") as f:
    f.write(f"\n\n{'='*50}\n")
    f.write(f"RUN STARTED: {run_time}\n")
    f.write(f"Files with > 60 empty or null cells:\n")
    f.write(f"{'='*50}\n")

collision_report_path = parent_output_dir / "collision_report.txt"
with open(collision_report_path, "a", encoding="utf-8") as f:
    f.write(f"\n\n{'='*90}\n")
    f.write(f"RUN STARTED: {run_time}\n")
    f.write("Files that were at risk of being overwritten (renamed with their source year):\n")
    f.write(f"{'='*90}\n")

rename_report_path = parent_output_dir / "rename_report.txt"
with open(rename_report_path, "a", encoding="utf-8") as f:
    f.write(f"\n\n{'='*90}\n")
    f.write(f"RUN STARTED: {run_time}\n")
    f.write("Files whose # TITLE was rescued from the # note row (RENAME):\n")
    f.write(f"{'='*90}\n")

redate_report_path = parent_output_dir / "redate_report.txt"
with open(redate_report_path, "a", encoding="utf-8") as f:
    f.write(f"\n\n{'='*90}\n")
    f.write(f"RUN STARTED: {run_time}\n")
    f.write("Files whose # TITLE was appended with date from the # note row (REDATE):\n")
    f.write(f"{'='*90}\n")

# -------------------- LOGIC 1: PRECISE MONTH DETECTION --------------------

def get_month_substring(filename):
    name = filename.lower()
    
    safe_months = [
        "january", "february", "april", "june", "july", "september", "sept",
        "october", "november", "december"
    ]
    for m in safe_months:
        if m in name: return m

    risky_months = [
        "march", "mar", "apr", "may", "june", "jun",
        "july", "jul", "august","aug", "jan", "feb", "sep", "oct", "nov", "dec"
    ]
    for m in risky_months:
        pattern = r"(?:^|[^a-z])(" + m + r")(?:$|[^a-z])"
        match = re.search(pattern, name)
        if match:
            return match.group(1)
            
    return None

# -------------------- LOGIC 2: CLEAN STATION NAMES --------------------

def normalize_string(text):
    text = text.lower()
    text = text.replace('œ', 'oe').replace('æ', 'ae')
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    text = re.sub(r'[_\-]+', ' ', text)
    return text.strip()

def extract_station_name(filename):
    name = filename.lower()
    
    name = name.replace('œ', 'oe').replace('æ', 'ae')
    
    name = re.sub(r'^\d+_', '', name)
    name = re.sub(r'_table_\d+.*$', '', name)
    name = name.replace('.csv', '')
    
    # Chop off LLM metadata leakage & standard junk titles
    garbage_keywords = [
        "height_above", "heights_above", "mean_sea_level", "barometer", 
        "thermometer", "station_h", "latitude", "longitude", "rain_gauge", "ft_",
        "observations_at_stations_of_the_second_order",
        "quarterly_weather_report"
    ]
    for g in garbage_keywords:
        if g in name:
            name = name.split(g)[0]
            
    name = re.sub(r'_(18|19)\d{2}', '', name)
    
    strip_safe = ["january", "february", "april", "june",
                  "july", "september", "october", "november", "december",
                  "anemometer", "annual"]
    for m in strip_safe:
        name = name.replace(m, '')
    
    name = re.sub(r'[_\W]+', ' ', name)
    words = name.split()
    strip_risky = {"march", "mar", "may", "jan", "feb",
                   "sep", "oct", "nov", "dec", "apr", 
                   "jun", "jul", "aug", "august"}
    
    cleaned_words = [w for w in words if w not in strip_risky]
    
    name = " ".join(cleaned_words).strip()  
    return name.title()

# -------------------- LOGIC 3: FUZZY FOLDER MATCHING --------------------

def is_word_subset_match(norm1, norm2):
    w1 = norm1.split()
    w2 = norm2.split()
    
    min_len = min(len(w1), len(w2))
    if min_len == 0: return False
    
    for i in range(min_len):
        word1, word2 = w1[i], w2[i]
        
        if len(word1) <= 3 or len(word2) <= 3:
            if word1 != word2: 
                return False
        else:
            ratio = SequenceMatcher(None, word1, word2).ratio()
            if ratio < 0.82: 
                return False
                
    return True

def get_target_folder_name(raw_station_name):
    norm_new = normalize_string(raw_station_name)
    
    if norm_new in station_folder_map:
        return station_folder_map[norm_new]
    
    best_match = None
    best_ratio = 0.0
    
    for existing_norm, real_folder_name in station_folder_map.items():
        if (norm_new in existing_norm) or (existing_norm in norm_new):
            return real_folder_name
            
        ratio = SequenceMatcher(None, norm_new, existing_norm).ratio()
        
        if ratio > 0.85 and ratio > best_ratio:
            best_ratio = ratio
            best_match = real_folder_name

    if best_match:
        station_folder_map[norm_new] = best_match
        return best_match
        
    for existing_norm, real_folder_name in station_folder_map.items():
        if is_word_subset_match(norm_new, existing_norm):
            station_folder_map[norm_new] = real_folder_name
            return real_folder_name

    final_name = raw_station_name.replace(" ", "_")
    station_folder_map[norm_new] = final_name
    return final_name

# -------------------- LOGIC 4: TITLE REPLACEMENT & CONTENT ANALYSIS --------------------

def check_and_fix_csv_metadata(filepath, original_clean_filename):
    """
    Handles two cases:
    1. RENAME: Replaces junk titles with 'STATION - MONTH YEAR' found in note.
    2. REDATE: Appends 'MONTH YEAR' found in note to the existing title.
    Returns: action_type ("RENAME", "REDATE", or None), new_filename, modified_rows, old_title, new_title
    """
    action_type = None
    new_filename = original_clean_filename
    rows = []
    
    title_idx = -1
    note_idx = -1
    title_targets = [
        "OBSERVATIONS AT STATIONS OF THE SECOND ORDER",
        "QUARTERLY WEATHER REPORT"
    ]
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read().replace('\x00', '')
        
        reader = csv.reader(io.StringIO(text))
        for i, row in enumerate(reader):
            rows.append(row)
            if not row: continue
            
            col0 = row[0].strip().lower()
            if col0 == '# title' and len(row) > 1:
                title_idx = i
            elif col0 == '# note' and len(row) > 1:
                note_idx = i
                
        old_title = ""
        new_title = ""
        note_val = ""
                
        if title_idx != -1 and note_idx != -1:
            old_title = rows[title_idx][1].strip()
            note_val = rows[note_idx][1].strip()
            
            month_pattern = r"(january|february|march|april|may|june|july|august|september|october|november|december)"
            
            is_bad_title = any(target in old_title.upper() for target in title_targets)
            
            # --- CHECK 1: RENAME (Bad Title -> Swap entirely) ---
            if is_bad_title:
                match = re.search(rf"^(.*?)[.,]?\s*-\s*{month_pattern}\s+(\d{{4}})", note_val, re.IGNORECASE)
                if match:
                    station_part = match.group(1).strip()
                    month_part = match.group(2).strip()
                    year_part = match.group(3).strip()
                    
                    new_title = note_val
                    rows[title_idx][1] = new_title
                    rows[note_idx][1] = "null"
                    
                    action_type = "RENAME"
                    
            # --- CHECK 2: REDATE (Title is fine -> Append date) ---
            if not action_type:
                match = re.match(rf"^\s*{month_pattern}\s+(\d{{4}})\.?\s*$", note_val, re.IGNORECASE)
                if match:
                    month_part = match.group(1).strip()
                    year_part = match.group(2).strip()
                    
                    # We use old_title as the station part for filename construction
                    station_part = old_title
                    
                    new_title = f"{old_title} - {month_part.capitalize()} {year_part}"
                    rows[title_idx][1] = new_title
                    rows[note_idx][1] = "null"
                    
                    action_type = "REDATE"

            # --- If either action was taken, rebuild the filename ---
            if action_type:
                page_match = re.match(r'^(\d+)_', original_clean_filename)
                page_num = page_match.group(1) if page_match else ""
                
                table_match = re.search(r'_(table_\d+)', original_clean_filename.lower())
                table_num = table_match.group(1) if table_match else ""
                
                station_clean = re.sub(r'[^\w\s]', '', station_part).strip().lower().replace(' ', '_')
                month_clean = month_part.lower()
                
                parts = []
                if page_num: parts.append(page_num)
                if station_clean: parts.append(station_clean)
                if month_clean: parts.append(month_clean)
                if year_part: parts.append(year_part)
                if table_num: parts.append(table_num)
                
                if parts:
                    new_filename = "_".join(parts) + ".csv"
                    
        return action_type, new_filename, rows, old_title, new_title
        
    except Exception as e:
        print(f"Error checking metadata for {filepath.name}: {e}")
        return None, original_clean_filename, [], "", ""
        
    except Exception as e:
        print(f"Error checking metadata for {filepath.name}: {e}")
        return False, original_clean_filename, []

MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12
}

# Creates a regex pattern matching any month word exactly
pattern_str = r'\b(' + '|'.join(sorted(MONTH_MAP.keys(), key=len, reverse=True)) + r')\b'
month_regex = re.compile(pattern_str)
anemometer_keywords_regex = re.compile(r'\b(roof|robinson|cup|anemometer|gust?)\b', re.IGNORECASE)

def analyze_file_content(filepath):
    unique_months = set()
    total_lines = 0
    max_cols = 0
    has_anemometer_term = False
    has_invalid_anemometer_terms = False

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # THIS is the magic line that destroys the NUL bytes so csv.reader won't crash
            text = f.read().replace('\x00', '')
        
        text_lower = text.lower()
            
        # Check for distinct months
        matches = month_regex.findall(text.lower())
        for match in matches:
            unique_months.add(MONTH_MAP[match])

        # Check for anemometer keywords in text
        if anemometer_keywords_regex.search(text):
            has_anemometer_term = True
        
        # if "barometer" or "pressure" appears (ignoring height_above_ground_barometer)
        text_for_neg = text_lower.replace("height_above_ground_barometer", "")
        text_for_neg = re.sub(r"dines'?\s+pressure\s+tube(?:\s+anemometer)?", "", text_for_neg)
        text_for_neg = text_for_neg.replace("pressure tube anemometer", "")
        text_for_neg = text_for_neg.replace("pressure tube", "")
        if re.search(r'\b(barometer|pressure)\b', text_for_neg):
            has_invalid_anemometer_terms = True

        # Because the NUL bytes are gone, csv.reader will now work perfectly
        f_io = io.StringIO(text)
        reader = csv.reader(f_io)
        for row in reader:
            total_lines += 1
            if len(row) > max_cols:
                max_cols = len(row)
        
        is_anemometer_content = has_anemometer_term or (max_cols == 8) # fallback if none of the regex are in the anemometer file/filename. 
                                                                        # anemometer files tended to have 8 cols
    

        return len(unique_months), total_lines, is_anemometer_content, has_invalid_anemometer_terms
    except Exception as e:
        print(f"Error reading {filepath.name} for content: {e}")
        return 0, 0, False, False

def get_source_year(filepath):
    # reads top rows of csv and extracts the year from source_filename row
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                if 'SOURCE_FILENAME' in line.upper():
                    match = re.search(r'(18|19)\d{2}', line)
                    if match:
                        return match.group(0)
    except Exception:
        pass
    return None


# -------------------- MAIN LOOP --------------------

count_daily = 0
count_monthly = 0
count_anemometer = 0
count_annual = 0
count_sunshine = 0
count_collisions = 0
count_renames = 0
count_redates = 0

station_folder_map = {}

# --- Pre-load existing folders from disk (Only for Daily/Monthly as Anemometer/Annual/Sunshine have no town subfolders) ---
for root_dir in [daily_root, monthly_root]:
    if root_dir.exists():
        for existing_folder in root_dir.iterdir():
            if existing_folder.is_dir():
                norm_existing = normalize_string(existing_folder.name)
                if norm_existing not in station_folder_map:
                    station_folder_map[norm_existing] = existing_folder.name

for input_dir in input_dirs:
    print(f"\nProcessing Input Folder: {input_dir}")
    if not input_dir.exists():
        print(f"Skipping, folder not found: {input_dir}")
        continue

    files = list(input_dir.glob("*.csv"))
    files.sort(key=lambda x: len(x.name))
    
    total = len(files)
    print(f"Found {total} csvs")

    for i, csv_file in enumerate(files):
        if i > 0 and i % 100 == 0: 
            print(f"Processing {i}/{total}...")
        
        # --- Sanitize filename ---
        original_filename = csv_file.name
        clean_filename = original_filename.replace('œ', 'oe').replace('æ', 'ae').replace('Œ', 'Oe').replace('Æ', 'Ae')
        clean_filename = unicodedata.normalize('NFKD', clean_filename).encode('ASCII', 'ignore').decode('utf-8')
        clean_lower = clean_filename.lower()
        
        # --- Title Replacement (rename or redate(add date from note)) ---
        action_type, clean_filename, modified_rows, old_title, new_title = check_and_fix_csv_metadata(csv_file, clean_filename)
        
        if action_type == "RENAME":
            count_renames += 1
            with open(rename_report_path, "a", encoding="utf-8") as f:
                f.write(f"Original File: {original_filename}\n")
                f.write(f"  Replaced Title: '{old_title}'  -->  '{new_title}'\n")
                f.write(f"  New Filename:   {clean_filename}\n")
                f.write("-" * 40 + "\n")
                
        elif action_type == "REDATE":
            count_redates += 1
            with open(redate_report_path, "a", encoding="utf-8") as f:
                f.write(f"Original File: {original_filename}\n")
                f.write(f"  Appended Date: '{old_title}'  -->  '{new_title}'\n")
                f.write(f"  New Filename:  {clean_filename}\n")
                f.write("-" * 40 + "\n")
        
        # Sterilize the new filename just in case
        clean_filename = clean_filename.replace('œ', 'oe').replace('æ', 'ae').replace('Œ', 'Oe').replace('Æ', 'Ae')
        clean_filename = unicodedata.normalize('NFKD', clean_filename).encode('ASCII', 'ignore').decode('utf-8')
        clean_lower = clean_filename.lower()

        # Extract Year Early (For Anemometer bounds and Junk reconstruction)
        file_year = get_source_year(csv_file)
        if not file_year:
            # Fallback to year in existing filename if metadata fails
            year_match = re.search(r'\b((?:18|19)\d{2})\b', clean_filename)
            if year_match:
                file_year = year_match.group(1)
        
        is_anemometer_year = False
        if file_year and file_year.isdigit():
            if 1908 <= int(file_year) <= 1910:
                is_anemometer_year = True

         # --- Content Analysis ---
        distinct_months_count, total_lines, is_anemometer_content, has_invalid_anemometer_terms = analyze_file_content(csv_file)
        
        # --- Check for special types ---
        is_anemometer = False
        # file name contains anemometer/anemograph/wind/cups = anemometer table
        if "anemometer" in clean_lower or "anemograph" in clean_lower or "wind" in clean_lower or "cups" in clean_lower:
            is_anemometer = True
        # heuristics: detect keywords in file or whether file has 8 cols, limited only to files that are 1908-1910 inclusive
        elif is_anemometer_year and not has_invalid_anemometer_terms:
            if is_anemometer_content:
                is_anemometer = True
        is_annual = "annual" in clean_lower or "pm" in clean_lower or "local" in clean_lower
        is_sunshine = "sunshine" in clean_lower and "those" in clean_lower or "selfrecording" in clean_lower

        # --- Extraction & Routing ---
        if is_anemometer:
            dest_folder = anemometer_root
            count_anemometer += 1
        elif is_annual:
            dest_folder = annual_root
            count_annual += 1
        elif is_sunshine:
            dest_folder = sunshine_root
            count_sunshine += 1
        else:
            # Only calculate subfolders for Daily/Monthly
            month_string = get_month_substring(clean_filename)

            # --- The New Daily vs Monthly Logic ---
            if month_string:
                is_daily = True
            else:
                # If no month in filename, check contents. 
                # Monthly files list many months. Daily files usually list 1.
                if distinct_months_count >= 4:
                    is_daily = False # It's a Monthly file
                else:
                    is_daily = True  # It's a Daily file that was missing the month in the filename
            # overriding rule: less than 30 lines in the csv is monthly table
            if total_lines < 30:
                is_daily = False
            
            # Extract clean station name for folder
            raw_station = extract_station_name(clean_filename)

            if is_daily and month_string:
                pattern = re.compile(re.escape(month_string), re.IGNORECASE)
                raw_station = pattern.sub("", raw_station).strip()
            
            raw_station = " ".join(raw_station.split()).strip()
            if re.match(r'^(table|table\s*line|line|unknown(\s*station)?)(\s*\d+)?$', raw_station, re.IGNORECASE):
                raw_station = ""
            if not raw_station:
                raw_station = "Unknown_Station"
                # RECONSTRUCT JUNK FILENAMES (e.g. 2904_table_line... -> 2904_1878_table_2.csv)
                        
                page_match = re.match(r'^(\d+)_', clean_filename)
                page_num = page_match.group(1) if page_match else ""
                
                table_match = re.search(r'_(table_\d+)', Path(clean_filename).stem)
                table_num = table_match.group(1) if table_match else ""
                
                # Assemble the new clean string
                parts = []
                if page_num: parts.append(page_num)
                if month_string: parts.append(month_string)
                if file_year: parts.append(file_year)
                if table_num: parts.append(table_num)
                
                if parts:
                    clean_filename = "_".join(parts) + Path(original_filename).suffix

            final_station_folder = get_target_folder_name(raw_station)

            if is_daily:
                dest_folder = daily_root / final_station_folder
                count_daily += 1
            else:
                dest_folder = monthly_root / final_station_folder
                count_monthly += 1
            
            dest_folder.mkdir(parents=True, exist_ok=True)
        
        # --- COLLISION PREVENTION ---
        dest_path = dest_folder / clean_filename
        
        if dest_path.exists():
            count_collisions += 1
            print(f"  [!] Collision Risk: {clean_filename} already exists!")
            
            year_existing = get_source_year(dest_path)
            year_new = get_source_year(csv_file)

            # Auto-rename by appending _duplicate1, _duplicate2, etc.
            base_name = dest_path.stem
            ext = dest_path.suffix

            # rename the existing file if the year was found from source_filename
            if year_existing and not base_name.endswith(str(year_existing)):
                new_existing_path = dest_folder / f"{base_name}_{year_existing}{ext}"
                if not new_existing_path.exists() and new_existing_path != dest_path:
                    dest_path.rename(new_existing_path)
                    print(f"> Renamed old file to: {new_existing_path.name}")
            # define new path for the incoming file based on its year
            if year_new and not base_name.endswith(str(year_new)):
                dest_path = dest_folder / f"{base_name}_{year_new}{ext}"
                print(f"> Targeting new file as : {dest_path.name}")
            # fallback if there is still a collision (e.g. both from same year)
            if dest_path.exists():
                counter = 1
                fallback_base = dest_path.stem
                while dest_path.exists():
                    dest_path = dest_folder / f"{fallback_base}_duplicate{counter}{ext}"
                    counter += 1
                print(f"> Safley appended fallback to new file: {dest_path.name}")
            
            # Log it to the report
            with open(collision_report_path, "a", encoding="utf-8") as f:
                f.write(f"Source Folder: {input_dir.name}\n")
                f.write(f"Original Intended Name: {clean_filename}\n")
                f.write(f"Existing file extracted year: {year_existing}\n")
                f.write(f"New file extracted year: {year_new}\n")
                f.write(f"Final Saved As: {dest_path.name}\n")
                f.write("-" * 40 + "\n")
        
        # --- COPY FILE ---
        try:
            # CRITICAL FIX: If RENAME or REDATE happened, write the modified rows!
            if action_type:  
                with open(dest_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(modified_rows)
            else:
                shutil.copy2(csv_file, dest_path)
        except Exception as e:
            print(f"Error moving {original_filename}: {e}")

print("\n" + "-" * 40)
print(f"Sorting Complete.")
print(f"Daily Files:      {count_daily}")
print(f"Monthly Files:    {count_monthly}")
print(f"Anemometer Files: {count_anemometer}")
print(f"Annual Files:     {count_annual}")
print(f"Sunshine Files:   {count_sunshine}")
print("-" * 40)
print(f"Titles Rescued:     {count_renames}")
if count_renames > 0:
    print(f"See {rename_report_path.name} for details.")
print(f"Titles Appended:  {count_redates}")
if count_redates > 0:
    print(f"See {redate_report_path.name} for details.")
print(f"Collisions Averted: {count_collisions}")
if count_collisions > 0:
    print(f"See {collision_report_path} for details on renamed files.")
# print(f"Sparse files report saved to: {report_file_path.name}")
