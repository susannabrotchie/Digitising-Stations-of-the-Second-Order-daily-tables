import csv
import re
import pandas as pd
import numpy as np
from pathlib import Path
import io
import yaml

pd.set_option('future.no_silent_downcasting', True)
# -------------------- CONFIG --------------------

input_dir = Path("")
input_folders = [
    input_dir / "/Daily", # main input folder
    input_dir / "", # files that don't get through SSO/.../Daily to SSO_formatted because of missing/badly formatted headers
    input_dir / "" # files that were incomplete on extraction from the API and were sent back to chatbot to make complete
]

input_yaml = input_dir / ".yaml" # config for files that made it to SSO_formatted but had unknown station and/or month

if input_yaml.exists():
    with open(input_yaml, 'r') as f:
        unknown_station_month_config = yaml.safe_load(f)
else:
    unknown_station_month_config = {}
    print(f"YAML config not found. Proceeding without it.")

output_dir = Path("/Daily")

report_dir = Path("")
unicode_report_path = report_dir / "unicode_characters.csv"
notes_report_path = report_dir / "notes.csv"
decimal_added_report_path = report_dir / "decimal_places_added.csv"
implausible_vapour_report_path = report_dir / "implausible_vapour_tension.csv"
implausible_wetbulb_depression_report_path = report_dir / "implausible_wetbulb_depression.csv"
wind_force_hyphen_to_decimal_report_path = report_dir / "wind_force_hyphen_to_decimal_fixes.csv"
asterisk_report_path = report_dir / "removed_asterisks_report.csv"
ocr_symbol_to_decimal_i_to_1_report = report_dir / "ocr_symbol_to_decimal_i_to_1.csv" # mistranscriptions
wind_tidy_report_path = report_dir / "wind_tidy_corrections_report.csv"
merged_cell_report_path = report_dir / "merged_cell_fixes.csv"
fix_spaced_decimals_report_path = report_dir / "fix_spaced_decimals.csv"
cloud_report_path = report_dir / "cloud_cols_incorrect_10s_and_0s.csv"
year_rescued_from_sourcefilename_path = report_dir / "year_rescued_from_sourcefilename.csv"
duplicate_files_path = report_dir / "duplicate_files.csv"
gravity_correction_path = report_dir / "gravity_correction_fixes.csv"
duplicate_columns_path = report_dir / "duplicate_columns.csv"
transposed_nx_report_path = report_dir / "transposed_nx_fixes.csv"
rogue_leading_decimals_path = report_dir / "rogue_leading_decimals_fixes.csv"

NA_VALUES = ["", " ", "ND", "nan", "NaN", "None", "<NA>"]

# dictionary to standardise variant station names
station_aliases = {
    "dunrobin_castle_sutherlandshire": "dunrobin_castle",
    "dunrobin": "dunrobin_castle",
    "cronkbourne_douglas_isle_of_man": "cronkbourne_douglas",
    "douglas_cronkbourne_isle_of_man": "cronkbourne_douglas",
    "douglas_isle_of_man": "cronkbourne_douglas",
    "douglas": "cronkbourne_douglas",
    "cronkbourne": "cronkbourne_douglas",
    "falmouth_cornwall": "falmouth",
    "falmouth_cornwall_a": "falmouth",
    "dublin_phoenix_park": "dublin",
    "dublin_phenix_park": "dublin",
    "dublin_phœnix_park": "dublin",
    "dublin_city": "dublin",
    "lauderdale": "laudale",
    "lauder": "laudale",
    "cheltenham_gloucestershire": "cheltenham",
    "audley_end_essex": "audley_end",
    "eskdalemuir_dumfriesshire": "eskdalemuir",
    "fort_william_invernessshire": "fort_william",
    "ladylaw_near_hawick": "ladylaw",
    "shrewsbury_shropshire": "shrewsbury",
    "southport_lancashire": "southport",
    "woolacombe_devonshire": "woolacombe",
    "birr_castle_kings_county": "birr_castle",
    "birr_castle_parsonstown": "birr_castle",
    "parsonstown": "birr_castle",
    "plymouth_devonshire": "plymouth",
    "southport_lancashire": "southport",
    "scarborough_yorkshire": "scarborough",
    "deerness_orkney": "deerness",
    "swanbister_orkney": "swanbister_and_stenness",
    "stenness": "swanbister_and_stenness",
    "stenness_orkney": "swanbister_and_stenness",
    "stnness": "swanbister_and_stenness",
    "stinness": "swanbister_and_stenness",
    "swanbister": "swanbister_and_stenness",
    "tillypronie_aberdeenshire": "tillypronie",
    "southampton_hampshire": "southampton",
    "southampton_hants": "southampton",
    "stonyhurst_lancashire": "stonyhurst",
    "eskdalemuir_dumfriesshire": "eskdalemuir",
    "eskdalemuir_dumfries_shire": "eskdalemuir",
    "eskdalemuir_dumfries": "eskdalemuir",
    "dumfries": "eskdalemuir",
    "dumfriesshire": "eskdalemuir",
    "edgbaston": "birmingham",
    "birmingham_edgbaston": "birmingham",
    "markree_castle_sligo": "markree_castle",
    "limerick": "limerick_mungret_college",
    "st_aubins": "st_aubins_jersey"
}


# -------------------- HELPERS --------------------

def get_schema(year_str):
    """
    Switchboard: Returns the correct column layout and critical indices based on the year.
    """
    try:
        year = int(year_str)
    except (ValueError, TypeError):
        year = 1890 # Default to middle period if unknown

    if 1873 <= year <= 1874:
        return {
            "name": "1873,1874",
            "headers": [
                "Date", "Barometer. Reduced to 32˚ and Sea Level. 8 a.m.", "Barometer. Reduced to 32˚ and Sea Level. 4 p.m.",
                "Barometer. Reduced to 32˚ and Sea Level. Midt.",
                "Air Temperature 8 a.m.", "Air Temperature 4 p.m.", "Air Temperature Midt.", 
                "Air Temperature Min.", "Air Temperature Max.",
                "Tension of Vapour 8 a.m.", "Tension of Vapour 4 p.m.", "Tension of Vapour Midt.",
                "Relative Humidity 8 a.m.", "Relative Humidity 4 p.m.", "Relative Humidity Midt.",
                "Wind Direction 8 a.m.", "Wind Force 8 a.m.", "Wind Direction 4 p.m.", "Wind Force 4 p.m.",
                "Wind Direction Midt.", "Wind Force Midt.",
                "Amount of Cloud 8 a.m.", "Amount of Cloud 4 p.m.", "Amount of Cloud Midt.", 
                "Rain 8 a.m."
            ],
            "wind_pairs": [(15, 16), (17, 18), (19, 20)], # Indices for (Dir AM, Force AM), (Dir PM, Force PM)
            "idx_cloud_am": 21, "idx_cloud_pm": 22, "idx_rain": 24
        }
    elif 1875 <= year <= 1879:
        return {
            "name": "1875-1879",
            "headers": [
                "Day", "Barometer 9 a.m.", "Barometer 9 p.m.",
                "Air Temperature 9 a.m.", "Air Temperature 9 p.m.", "Air Temperature Min.", "Air Temperature Max.",
                "Tension of Vapour 9 a.m.", "Tension of Vapour 9 p.m.",
                "Relative Humidity 9 a.m.", "Relative Humidity 9 p.m.",
                "Wind Direction 9 a.m.", "Wind Force 9 a.m.", "Wind Direction 9 p.m.", "Wind Force 9 p.m.",
                "Amount of Cloud 9 a.m.", "Amount of Cloud 9 p.m.", "Rain 9 a.m."
            ],
            "wind_pairs": [(11, 12), (13, 14)], # Indices for (Dir AM, Force AM), (Dir PM, Force PM)
            "idx_cloud_am": 15, "idx_cloud_pm": 16, "idx_rain": 17
        }
    
    elif 1880 <= year <= 1885:
        return {
            "name": "1880-1885",
            "headers": [
                "Day", "Barometer at 32˚ and M.S.L. 9 a.m.", "Barometer at 32˚ and M.S.L. 9 p.m.",
                "Air Temperature 9 a.m.", "Air Temperature 9 p.m.", "Air Temperature Min.", "Air Temperature Max.",
                "Tension of Vapour 9 a.m.", "Tension of Vapour 9 p.m.",
                "Relative Humidity 9 a.m.", "Relative Humidity 9 p.m.",
                "Wind Direction 9 a.m.", "Wind Force 9 a.m.", "Wind Direction 9 p.m.", "Wind Force 9 p.m.",
                "Amount of Cloud 9 a.m.", "Amount of Cloud 9 p.m.", "Rain 9 a.m."
            ],
            "wind_pairs": [(11, 12), (13, 14)], # Indices for (Dir AM, Force AM), (Dir PM, Force PM)
            "idx_cloud_am": 15, "idx_cloud_pm": 16, "idx_rain": 17
        }
    elif 1886 <= year <= 1898:
        return {
            "name": "1886-1898",
            "headers": [
                "Day", "Barometer at 32° Faht. 9 a.m.", "Barometer at 32° Faht. 9 p.m.",
                "Air Temperature 9 a.m.", "Air Temperature 9 p.m.", "Air Temperature Min.", "Air Temperature Max.",
                "Humidity Dep. of Wet. 9 a.m.", "Humidity Dep. of Wet. 9 p.m.",
                "Humidity Vapour Tension 9 a.m.", "Humidity Vapour Tension 9 p.m.",
                "Humidity Percentage 9 a.m.", "Humidity Percentage 9 p.m.",
                "Wind Direction 9 a.m.", "Wind Force 9 a.m.", "Wind Direction 9 p.m.", "Wind Force 9 p.m.",
                "Cloud Amount 9 a.m.", "Cloud Amount 9 p.m.", "Rain 9 a.m."
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    elif 1899 <= year <= 1901:
        return {
            "name": "1899-1901",
            "headers": [
                "Day", "Barometer at 32° Faht. 9 a.m.", "Barometer at 32° Faht. 9 p.m.",
                "Air Temperature 9 a.m.", "Air Temperature 9 p.m.", "Air Temperature Min.", "Air Temperature Max.",
                "Humidity Dep. of Wet. 9 a.m.", "Humidity Dep. of Wet. 9 p.m.",
                "Humidity Vapour Pressure 9 a.m.", "Humidity Vapour Pressure 9 p.m.",
                "Humidity Percentage 9 a.m.", "Humidity Percentage 9 p.m.",
                "Wind Direction 9 a.m.", "Wind Force 9 a.m.", "Wind Direction 9 p.m.", "Wind Force 9 p.m.",
                "Cloud Amount 9 a.m.", "Cloud Amount 9 p.m.", "Rain 24 hours beginning 9 a.m."
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    elif 1902 <= year <= 1905:
        return {
            "name": "1902-1905",
            "headers": [
                "Day", "Barometer at 32° Faht. at Station Level 9 a.m.", "Barometer at 32° Faht. at Station Level 9 p.m.",
                "Air Temperature 9 a.m.", "Air Temperature 9 p.m.", "Air Temperature Min.", "Air Temperature Max.",
                "Humidity Dep. of Wet. 9 a.m.", "Humidity Dep. of Wet. 9 p.m.",
                "Humidity Vapour Pressure 9 a.m.", "Humidity Vapour Pressure 9 p.m.",
                "Humidity Percentage 9 a.m.", "Humidity Percentage 9 p.m.",
                "Wind Direction 9 a.m.", "Wind Force 9 a.m.", "Wind Direction 9 p.m.", "Wind Force 9 p.m.",
                "Cloud Amount 9 a.m.", "Cloud Amount 9 p.m.", "Rain 24 hours beginning 9 a.m."
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    elif 1906 <= year <= 1907:
        return {
            "name": "1906-1907",
            "headers": [
                "Day", "Barometer at 32° Faht. at Level and Latitude of Station 9 a.m.", "Barometer at 32° Faht. at Station Level and Latitude of Station 9 p.m.",
                "Air Temperature 9 a.m.", "Air Temperature 9 p.m.", "Air Temperature Max.", "Air Temperature Min.",
                "Humidity Dep. of Wet. 9 a.m.", "Humidity Dep. of Wet. 9 p.m.",
                "Humidity Vapour Pressure 9 a.m.", "Humidity Vapour Pressure 9 p.m.",
                "Humidity Percentage 9 a.m.", "Humidity Percentage 9 p.m.",
                "Wind Direction 9 a.m.", "Wind Force (0-12) 9 a.m.", "Wind Direction 9 p.m.", "Wind Force (0-12) 9 p.m.",
                "Cloud Amount 9 a.m.", "Cloud Amount 9 p.m.", "Rain 24 hours beginning 9 a.m.",
                "Sunshine", "Min. Temp. on Grass"
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    elif 1908 <= year <= 1910:
        return {
            "name": "1908-1910",
            "headers": [
                "Day", "Barometer at 32° Faht. at Level and Latitude of Station 9 a.m.", "Barometer at 32° Faht. at Station Level and Latitude of Station 9 p.m.",
                "Air Temperature 9 a.m.", "Air Temperature 9 p.m.", "Air Temperature Max.", "Air Temperature Min.",
                "Humidity Dep. of Wet. 9 a.m.", "Humidity Dep. of Wet. 9 p.m.",
                "Humidity Vapour Pressure 9 a.m.", "Humidity Vapour Pressure 9 p.m.",
                "Humidity Percentage 9 a.m.", "Humidity Percentage 9 p.m.",
                "Wind Direction 9 a.m.", "Wind Force (0-12) or Velocity (miles per hour) 9 a.m.", 
                "Wind Direction 9 p.m.", "Wind Force (0-12) or Velocity (miles per hour) 9 p.m.",
                "Cloud Amount 9 a.m.", "Cloud Amount 9 p.m.", "Rain 24 hours beginning 9 a.m.",
                "Sunshine", "Min. Temp. on Grass"
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    elif 1910 <= year <= 1911:
        return {
            "name": "1910-1911",
            "headers": [
                "Day", "Barometer at 32° Faht. at Level and Latitude of Station 9 h.", "Barometer at 32° Faht. at Station Level and Latitude of Station 21 h.",
                "Air Temperature 9 h.", "Air Temperature 21 h.", "Air Temperature Max.", "Air Temperature Min.",
                "Humidity Dep. of Wet. 9 h.", "Humidity Dep. of Wet. 21 h.",
                "Humidity Vapour Pressure 9 h.", "Humidity Vapour Pressure 21 h.",
                "Humidity Percentage 9 h.", "Humidity Percentage 21 h.",
                "Wind Direction 9 h.", "Wind Force (0-12) or Velocity (miles per hour) 9 h.", 
                "Wind Direction 21 h.", "Wind Force (0-12) or Velocity (miles per hour) 21 h.",
                "Cloud Amount 9 h.", "Cloud Amount 21 h.", "Rain, 24 hours beginning 9 h.",
                "Sunshine", "Min. Temp. on Grass"
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    elif 1912 <= year <= 1915:
        return {
            "name": "1912-1915",
            "headers": [
                "Day", "Barometer at 32˚ Faht. Mean Sea Level and Standard Gravity. (Latitude 45˚.) 9 h.", "Barometer at 32˚ Faht. Mean Sea Level and Standard Gravity. (Latitude 45˚.) 21 h.",
                "Air Temperature in Degrees Absolute 9 h.", "Air Temperature in Degrees Absolute 21 h.", "Air Temperature in Degrees Absolute Max.", "Air Temperature in Degrees Absolute Min.",
                "Humidity Dep. of Wet. 9 h.", "Humidity Dep. of Wet. 21 h.",
                "Humidity Vapour Pressure 9 h.", "Humidity Vapour Pressure 21 h.",
                "Humidity Percentage 9 h.", "Humidity Percentage 21 h.",
                "Wind Direction in Points (8=E, 16=S) 9 h.", "Wind Force (0-12) or Velocity (metres per second) 9 h.", 
                "Wind Direction in Points (8=E, 16=S) 21 h.", "Wind Force (0-12) or Velocity (metres per second) 21 h.",
                "Cloud Amount 9 h.", "Cloud Amount 21 h.", "Rain, 24 hours beginning 9 a.m.", "Sunshine", "Min. Temp. on Grass"
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    elif 1916 <= year <= 1917:
        return {
            "name": "1916-1917",
            "headers": [
                "Day", "Air Pressure at Mean Sea Level 9 h.", "Air Pressure at Mean Sea Level 21 h.",
                "Air Temperature in Degrees Absolute 9 h.", "Air Temperature in Degrees Absolute 21 h.", "Air Temperature in Degrees Absolute Max.", "Air Temperature in Degrees Absolute Min.",
                "Humidity Dep. of Wet. 9 h.", "Humidity Dep. of Wet. 21 h.",
                "Humidity Vapour Pressure 9 h.", "Humidity Vapour Pressure 21 h.",
                "Humidity Percentage 9 h.", "Humidity Percentage 21 h.",
                "Wind Direction in Points (8=E, 16=S) 9 h.", "Wind Force (0-12) or Velocity (metres per second) 9 h.", 
                "Wind Direction in Points (8=E, 16=S) 21 h.", "Wind Force (0-12) or Velocity (metres per second) 21 h.",
                "Cloud Amount 9 h.", "Cloud Amount 21 h.", "Rain, 24 hours beginning 9 a.m.", "Sunshine", "Min. Temp. on Grass"
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    elif 1918 <= year <= 1921:
        return {
            "name": "1918-1921",
            "headers": [
                "Day", "Air Pressure at Mean Sea Level 9 h.", "Air Pressure at Mean Sea Level 21 h.",
                "Air Temperature in Degrees Absolute 9 h.", "Air Temperature in Degrees Absolute 21 h.", "Air Temperature in Degrees Absolute Max.", "Air Temperature in Degrees Absolute Min.",
                "Humidity Dep. of Wet. 9 h.", "Humidity Dep. of Wet. 21 h.",
                "Humidity Vapour Pressure 9 h.", "Humidity Vapour Pressure 21 h.",
                "Humidity Percentage 9 h.", "Humidity Percentage 21 h.",
                "Wind Veer from North 9 h.", "Wind Force or Speed 9 h.", 
                "Wind Veer from North 21 h.", "Wind Force or Speed 21 h.",
                "Cloud Amount 9 h.", "Cloud Amount 21 h.", "Rain, 24 hours beginning 9 a.m.", "Sunshine", "Min. Temp. on Grass"
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    else:
        return {
            "name": "1921",
            "headers": [
                "Day", "Air Pressure at Mean Sea Level 9 h.",  "Air Pressure at Mean Sea Level 21 h.", "Air Temperature in Degrees Absolute Dry Bulb 9 h.",
                "Air Temperature in Degrees Absolute Dry Bulb 21 h.", "Air Temperature in Degrees Max. 21 h. to 21h.", 
                "Air Temperature in Degrees Min. 21 h. to 21h.","Humidity Dep. of Wet. 9 h.", "Humidity Dep. of Wet. 21 h.",
                "Humidity Vapour Pressure 9 h.", "Humidity Vapour Pressure 21 h.", "Humidity Percentage 9 h.", "Humidity Percentage 21 h.", 
                "Wind Veer from North and Force or Speed 9 h. deg", "Wind Veer from North and Force or Speed 9h. f. or m/s.", 
                "Wind Veer from North and Force or Speed 21 h. deg", "Wind Veer from North and Force or Speed 21h. f. or m/s.", 
                "Cloud Amount and Weather 9 h.", "Cloud Amount and Weather 21 h.", 
                "Rain 24 hr. beginning 9 h.", "Sunshine", "Min. Temp. on Grass"
            ],
            "wind_pairs": [(13, 14), (15, 16)],
            "idx_cloud_am": 17, "idx_cloud_pm": 18, "idx_rain": 19
        }
    
def detect_observation_hours(raw_header):
    """
    Scans input header row and determines station's actual AM/PM observation hours (e.g. 8/20, 9/21, 10/22)
    robust to:
      - 9 h., 21h., etc
      - 8 a.m., 4 p.m., etc
      - "0 h. to 24 h." range phrases on Rain/Max/Min columns. these are excluded so they don't get mistaken for the station's observing hours across other variables.
    Also returns whether a rain range and/or max/min range phrase was present,
    so callers needing that info don't have to rescan the header separately.

    Returns: (am_hour, pm_hour, has_rain_range, has_maxmin_range)
    am_hour / pm_hour are ints or None if undetectable.
    """
    raw_hdr_str = " ".join([str(c).lower() for c in raw_header])
    rain_range_pattern = r'0\s*h\.?\s*to\s*24\s*h\.?'

    # ---- Detect range phrase per relevant column type (checked per-cell) ----
    has_rain_range = False
    has_maxmin_range = False
    for cell in raw_header:
        c_lower = str(cell).lower()
        if not re.search(rain_range_pattern, c_lower):
            continue
        if "rain" in c_lower:
            has_rain_range = True
        if ("max" in c_lower or "min" in c_lower) and "grass" not in c_lower:
            has_maxmin_range = True

    # ---- Strip the range phrase before hour-of-observation detection ----
    hour_scan_cells = []
    for cell in raw_header:
        c_lower = str(cell).lower()
        cleaned = re.sub(rain_range_pattern, '', c_lower)
        hour_scan_cells.append(cleaned)

    hdr_for_hour_scan = " ".join(hour_scan_cells)

    # ---- Try "N h." style tokens first ----
    hour_tokens = sorted(set(int(m) for m in re.findall(r'(?<!\.)(?<!\d)(\d{1,2})\s*h\.?\b', hdr_for_hour_scan)))

    am_hour, pm_hour = None, None
    uses_h_notation = False
    if len(hour_tokens) >= 2:
        am_hour, pm_hour = hour_tokens[0], hour_tokens[-1]
        uses_h_notation = True
    else:
        # Fall back to plain "N a.m."/"N p.m." wording (e.g. "8 a.m.", "4 p.m.")
        am_matches = [int(m) for m in re.findall(r'(?<!\.)(?<!\d)(\d{1,2})\s*a\.?\s*m\.?', hdr_for_hour_scan)]
        pm_matches = [int(m) for m in re.findall(r'(?<!\.)(?<!\d)(\d{1,2})\s*p\.?\s*m\.?', hdr_for_hour_scan)]
        am_hour = am_matches[0] if am_matches else None
        pm_hour = pm_matches[0] if pm_matches else None

    return am_hour, pm_hour, has_rain_range, has_maxmin_range, uses_h_notation


def hour_in_header(hour, text, meridiem=None):
    """
    Checks if `hour` appears in `text` followed by a time-suffix.
    meridiem=None: any suffix (h., a.m., or p.m.) — for the "N h." case where
    am/pm never share text at all.
    meridiem='am' / 'pm': require specifically that suffix — needed whenever
    am_hour == pm_hour (e.g. "9 a.m." and "9 p.m." use the same digit).
    """
    if hour is None:
        return False
    if meridiem == 'am':
        pattern = rf"(?<!\.)(?<!\d){hour}(?!\d)\s*a\.?\s*m\.?"
    elif meridiem == 'pm':
        pattern = rf"(?<!\.)(?<!\d){hour}(?!\d)\s*p\.?\s*m\.?"
    else:
        pattern = rf"(?<!\.)(?<!\d){hour}(?!\d)\s*(?:h\.?|a\.?\s*m\.?|p\.?\s*m\.?)"
    return bool(re.search(pattern, text))


def replace_hour_in_header(old_hour, new_hour, text):
    """
    Finds `old_hour` followed by any common time-suffix spelling and replaces
    just the number, preserving whatever suffix format was actually present.
    """
    pattern = rf"(?<!\.)(?<!\d){old_hour}(?!\d)(\s*(?:h\.?|a\.?\s*m\.?|p\.?\s*m\.?))"
    return re.sub(pattern, lambda m: f"{new_hour}{m.group(1)}", text)

def customise_target_headers(target_headers, raw_header):
    am_hour, pm_hour, has_rain_range, has_maxmin_range, uses_h_notation = detect_observation_hours(raw_header)

    # If raw input used plain a.m./p.m. wording (12-hour clock), pm_hour is
    # e.g. "9" from "9 p.m." — but an "h."-notation target expects the
    # 24-hour equivalent (21). Convert before substituting into those targets.
    if pm_hour is not None and not uses_h_notation:
        pm_hour_24h = pm_hour if pm_hour == 12 else pm_hour + 12
    else:
        pm_hour_24h = pm_hour

    am_hour_24h = am_hour  # AM numeral is the same on both clock systems

    raw_hdr_str = " ".join([str(c).lower() for c in raw_header])
    wind_modifiers = []
    if "m/s" in raw_hdr_str: wind_modifiers.append("m/s")
    if "mph" in raw_hdr_str: wind_modifiers.append("mph")
    if "beaufort" in raw_hdr_str: wind_modifiers.append("Beaufort")
    if "†" in raw_hdr_str: wind_modifiers.append("†")
    if "(0-12)" in raw_hdr_str or "0-12" in raw_hdr_str: wind_modifiers.append("(0-12)")

    new_headers = []
    for head in target_headers:
        new_head = head
        h_lower = new_head.lower()

        # Does THIS target header use "N h." notation, or plain a.m./p.m. wording?
        head_is_h_notation = bool(re.search(r'(?<!\.)(?<!\d)\d{1,2}\s*h\.?\b', h_lower))

        effective_am = am_hour_24h if head_is_h_notation else am_hour
        effective_pm = pm_hour_24h if head_is_h_notation else pm_hour
        pm_default = 21 if head_is_h_notation else 9

        if effective_am is not None and effective_am != 9 and hour_in_header(9, h_lower, meridiem=None if head_is_h_notation else 'am'):
            new_head = replace_hour_in_header(9, effective_am, new_head)

        if effective_pm is not None and effective_pm != pm_default and hour_in_header(pm_default, new_head.lower(), meridiem=None if head_is_h_notation else 'pm'):
            new_head = replace_hour_in_header(pm_default, effective_pm, new_head)

        if has_rain_range and "rain" in h_lower:
            new_head = "Rain, 0 h. to 24 h."

        if has_maxmin_range and ("max" in h_lower or "min" in h_lower) and "grass" not in h_lower:
            if "0 h. to 24 h." not in new_head:
                new_head = f"{new_head} 0 h. to 24 h."

        if "wind" in h_lower and ("force" in h_lower or "speed" in h_lower):
            if wind_modifiers:
                new_head = f"{new_head} {' '.join(wind_modifiers)}"

        new_headers.append(new_head)

    return new_headers

def fix_excel_corruptions(rows):
    """
    Some input folders had to be manually edited to fix Gemini issues
    This function deals with Excel formatting issues that are introduced by this step
    Fixes Excel auto-date formatting (e.g. "03-Apr" -> "3-4").
    Strips leading apostrophes used to prevent Excel formulas (e.g. "'3-4" -> "3-4" or "'+0.034" -> "+0.034).
    """
    # Map Excel's 3-letter month abbreviations back to their numerical equivalents
    month_to_num = {
        "jan": "1", "feb": "2", "mar": "3", "apr": "4",
        "may": "5", "jun": "6", "jul": "7", "aug": "8",
        "sep": "9", "oct": "10", "nov": "11", "dec": "12"
    }

    cleaned_rows = []
    for row in rows:
        clean_row = []
        for cell in row:
            s_cell = str(cell).strip()
            
            if not s_cell:
                clean_row.append(cell)
                continue

            # Strip leading apostrophe
            if s_cell.startswith("'"):
                s_cell = s_cell[1:]

            # Fix Date Formatting (e.g. "03-Apr")
            # Regex looks for exactly 1-2 digits, a dash, and 3 letters.
            match_a = re.match(r'^(\d{1,2})-([A-Za-z]{3})$', s_cell)
            if match_a:
                d1 = match_a.group(1).lstrip("0") # Strip leading zero (03 -> 3)
                m_str = match_a.group(2).lower()
                if m_str in month_to_num:
                    s_cell = f"{d1}-{month_to_num[m_str]}"
            
            clean_row.append(s_cell)
            
        cleaned_rows.append(clean_row)
        
    return cleaned_rows

def read_and_fix_unicode(csv_path, filename, unicode_report_list):
    """
    Reads a CSV file safely. Replaces Null bytes (\x00 or literal '\\u0000') with a dot (.).
    Reads the file as a complete block to protect multiline quotes in metadata notes.
    """
    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    # Check for actual null byte OR the 6-character literal string "\u0000"
    if '\x00' in content or '\\u0000' in content:
        
        # Count occurrences for the report
        count = content.count('\x00') + content.count('\\u0000')
        
        # Globally replace them
        content = content.replace('\x00', '.').replace('\\u0000', '.')
        
        unicode_report_list.append({
            "File": filename,
            "Row Index": "Various",
            "Original Text": "File contained Null bytes",
            "Corrected Text": "Replaced with '.'",
            "Issue": f"Replaced {count} Null Byte(s)"
        })
        
    # Pass the complete, clean text block to the CSV reader
    # This natively handles quotes that span across multiple lines!
    f_string = io.StringIO(content)
    reader = csv.reader(f_string)
    rows = list(reader)
            
    return rows

def normalize_cell_whitespace(rows):
    """
    Collapses embedded newlines, tabs, and runs of whitespace within each cell
    down to a single space. This must run before any column classification or
    splitting logic, since embedded newlines inside quoted CSV fields can:
      1. Break assumptions in downstream regexes that expect a single space
         delimiter (e.g. "26\n4" should behave identically to "26 4").
      2. Signal that the raw CSV had a quoting/row-alignment problem worth
         flagging, since a genuine data cell shouldn't normally contain a
         newline in the first place.
    """
    normalized_rows = []
    for row in rows:
        normalized_row = []
        for cell in row:
            s = str(cell)
            s = re.sub(r'\s+', ' ', s).strip()
            normalized_row.append(s)
        normalized_rows.append(normalized_row)
    return normalized_rows

def fix_merged_comma_cells(rows, filename, report_list):
    """
    Finds cells where OCR merged two numbers with a comma (e.g. "84, 78").
    Splits them into two separate cells in the row.
    Logs the fix to a report.
    """
    fixed_rows = []
    
    for row_idx, row in enumerate(rows):
        # We don't process the header row (row_idx == 0 typically passed here)
        # But we pass data_rows to this function so all rows are data.
        new_row = []
        fixed_something = False
        
        for col_idx, cell in enumerate(row):
            s_cell = str(cell).strip()
            
            # Look for exactly: Digits, comma, optional space, Digits (e.g., "84, 78" or "84,78")
            # We enforce that both sides look like numbers to avoid splitting text.
            match = re.match(r'^(\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)$', s_val := s_cell.replace('"', ''))
            
            if match:
                # Split it into two values
                val1 = match.group(1)
                val2 = match.group(2)
                
                new_row.append(val1)
                new_row.append(val2)
                fixed_something = True
                
                report_list.append({
                    "File": filename,
                    "Row Index": row_idx,
                    "Original Value": s_cell,
                    "Corrected Values": f"{val1} | {val2}"
                })
            else:
                new_row.append(cell)
                
        fixed_rows.append(new_row)
        
    return fixed_rows

def resolve_location_candidates(candidates, station, station_known, first_baro_val, second_baro_val):
    """
    Resolves which location-candidate applies for a given source_filename match.

    - If the file's station is already known (from folder/filename), just find
      the candidate whose 'location' matches it and return its month.
      No first_cell/second_cell needed — disambiguation isn't required because
      we already know which station this file belongs to.
    - If the station is unknown, disambiguate via first_cell/second_cell against
      the actual barometer reading extracted from the CSV. If there's only one
      candidate and no disambiguator, accept it (nothing to disambiguate).
    """

    # 1. If station is already known, just find the matching location
    if station_known:
        for cand in candidates:
            cand_loc = str(cand.get('location', '')).strip().lower()
            if cand_loc and cand_loc == station.lower():
                return cand.get('month'), cand.get('location')
        return None, None

    # 2. Station is unknown. Try to find a match based on first_cell / second_cell
    for cand in candidates:
        # Check First Cell Rule
        if 'first_cell' in cand:
            if not first_baro_val:
                continue # We don't have the data to check this rule
            try:
                if abs(float(cand['first_cell']) - float(first_baro_val)) < 0.001:
                    return cand.get('month'), cand.get('location')
            except (ValueError, TypeError):
                if str(cand['first_cell']).strip() == str(first_baro_val).strip():
                    return cand.get('month'), cand.get('location')
                    
        # Check Second Cell Rule
        elif 'second_cell' in cand:
            if not second_baro_val:
                continue
            try:
                if abs(float(cand['second_cell']) - float(second_baro_val)) < 0.001:
                    return cand.get('month'), cand.get('location')
            except (ValueError, TypeError):
                if str(cand['second_cell']).strip() == str(second_baro_val).strip():
                    return cand.get('month'), cand.get('location')
                    
        # If the YAML entry has NO disambiguation rules (no first_cell), accept it!
        else:
            return cand.get('month'), cand.get('location')

    # 3. Fallback
    # If we get here, it means we had candidates, but they all required disambiguation 
    # (e.g. first_cell: 29.5) and our CSV extraction failed to find a matching number.
    if len(candidates) == 1:
        # If there's only one candidate anyway, just take it, regardless of the failed cell check!
        cand = candidates[0]
        return cand.get('month'), cand.get('location')

    return None, None

def clean_metadata_title(meta_rows):
    """
    finds title row in metadata, removes all punctuation and applies proper case
    removes stray letters (a, b, c, d, e)
    these were attached to station names in the logbooks to indicate in which collection the aggregate data were published
    e.g. 'ARMAGH, a. - FEBRUARY 1907.' becomes 'Armagh February 1907'
    """
    if not meta_rows:
        return meta_rows
    
    for row in meta_rows:
        has_text = False
        for idx, cell in enumerate(row):
            s = str(cell).strip()
            if s:
                # remove boilerplate title text
                patterns = [
                    r"daily\s+readings\s+at\s+meteorological\s+stations\s+of\s+the\s+first\s+and\s+second\s+orders",
                    r"observations\s+at\s+stations\s+of\s+the\s+second\s+order",
                ]
                for pattern in patterns:
                    s = re.sub(pattern, "", s, flags=re.IGNORECASE)

                # Looks for a 4-digit year at start of title string, followed by a space
                # this fixes "1913 Deerness Orkney April 1913" to become "Deerness Orkney April 1913"
                s = re.sub(r'^\s*(17|18|19|20)\d{2}\s+', '', s)

                # regex looks for commas/spaces followed by any combination of a,b,c,d,e 
                # case-insensitive replacement to clear them
                s = re.sub(r'[,.\s]+([a-eA-E](?:[,.\s]+[a-eA-E])*)[,.\s]*[—–-]', ' ', s)
                
                # replace all remaining non-alphanumeric characters with a space
                clean_str = re.sub(r'[^\w\s]', ' ', s)
                
                # back up: clear any remaining standalone a,b,c,d,e words
                clean_str = re.sub(r'\b[abcdeABCDE]\b', ' ', clean_str)
                
                # collapse multiple spaces into one, strip edges, and apply Title Case
                clean_str = " ".join(clean_str.split()).title()
                
                row[idx] = clean_str
                has_text = True
                
        # stop after first row (title) is clean
        if has_text:
            break 
            
    return meta_rows


def process_metadata_notes(meta_rows, filename, notes_list):
    """
    If there is a 'note' in the metadata rows:
    Delete entire row if 'note' is followed by an empty cell/'null' etc
    If 'note is not followed by empty cell or 'null' etc, leave in csv and put in 'notes.csv' with file path in human_read_csvs
    """
    cleaned_rows = []
    for row in meta_rows:
        row_str = " ".join([str(c) for c in row if c]).lower()
        if "note" in row_str:
            content_cells = [str(c).strip() for c in row if str(c).strip()]
            full_text = " ".join(content_cells)
            clean_text = full_text.replace("#", "") #remove hastag #
            clean_text = re.sub(r'note[s]?[:\.\-]*', '', clean_text, flags=re.IGNORECASE).strip() #remove word 'note'
            if clean_text is not None and str(clean_text).strip().lower() not in ("", "none", "null"):
                notes_list.append({
                    "File": filename,
                    "Extracted Note": clean_text
                })
        cleaned_rows.append(row)
    return cleaned_rows
   
def report_asterisk(filename, col, idx, original_val, corrected_val, report_list):
    report_list.append({
        "File": filename,
        "Column": col,
        "Row Index": idx,
        "Original Value": original_val,
        "Corrected Value": corrected_val
    })

def clean_numeric_string(val):
    """
    Removes quotes, spaces, and converts commas to dots.
    PRESERVES HYPHENS so ranges like '5-6' survive.
    """
    if pd.isna(val) or val == "NA": return "NA"
    s = str(val).strip()
    
    # Replace comma and apostrophe with dot
    # We DO NOT replace hyphen '-' here!
    s = s.replace(",", ".").replace("'", ".").replace('"', "")
    
    return s

def filename_convention(filepath, input_root, date_config, source_file_str, meta_year=None, first_baro_val=None,second_baro_val=None):
    logbook = "sso"
    generic_names = ["daily", "record1_edited_header_files", "record1_texts_rescued"]
    station = "unknown"
    station_known = False

    try:
        rel_parts = filepath.relative_to(input_root).parts
        for part in rel_parts[:-1]:
            p_low = part.lower()
            if p_low not in generic_names:
                # treat boilerplater folder name the same as unknown station
                if re.match(r"^daily[\s_]+readings[\s_]+at[\s_]+meteorological[\s_]+stations[\s_]+of[\s_]+the[\s_]+first[\s_]+and[\s_]+second[\s_]+orders", p_low):
                    continue
                station = p_low
                if p_low not in ("unknown", "unknown_station"):
                    station_known = True
                break
    except Exception:
        pass

    if not station_known:
        stem = filepath.stem.lower()
        clean_stem = re.sub(r'^\d+_', '', stem)
        clean_stem = re.sub(r'_table_\d+.*$', '', clean_stem)
        clean_stem = re.sub(r'_(18|19)\d{2}.*$', '', clean_stem)
        clean_stem = re.sub(r'^(18|19)\d{2}_?', '', clean_stem)
        months_pattern = r'(?:^|_)(january|february|febuary|september|sept|october|november|december|march|mar|april|apr|may|june|jun|july|jul|august|aug|jan|feb|sep|oct|nov|dec)(?:$|_)'
        clean_stem = re.sub(months_pattern, '_', clean_stem)
        clean_stem = clean_stem.strip('_')
        if re.fullmatch(r'(18|19)\d{2}', clean_stem):
            clean_stem = ""
        if clean_stem:
            station = clean_stem
        # station_known stays False here — a filename-derived stem like "p32" is
        # NOT a verified station name, so YAML lookup must still disambiguate.
    
    # removes common boilerplate from filename for tidiness
    boilerplate_pattern = r"(?i)daily[\s_]+readings[\s_]+at[\s_]+meteorological[\s_]+stations[\s_]+of[\s_]+the[\s_]+first[\s_]+and[\s_]+second[\s_]+orders[\s_]*"
    station = re.sub(boilerplate_pattern, '', station)
    
    # clean station name by stripping any _a or _ab
    station = re.sub(r'_[a-e]+$', '', station)

    # check alias dictionary to standardise long file names
    if station in station_aliases:
        station = station_aliases[station]

    name = filepath.stem.lower()
    parent = filepath.parent.name.lower()

    # prevent leading IDs (like 1730_) from being read as the year ---
    # Strip leading digits and underscore just for the year check
    name_no_id = re.sub(r'^\d+_', '', name)

    # YAML look up
    # ==== YAML LOOKUP — SINGLE STRUCTURE: {year: [entries]} ====
    yaml_month = None
    yaml_station = None

    if date_config and source_file_str:
        for year_key, file_list in date_config.items():
            if yaml_month:
                break

            # Group every entry in this year that matches the file's source_filename —
            # a given source_filename should appear once with a locations list, but
            # group defensively in case the same source_filename ever appears twice.
            matching_entries = [
                e for e in file_list
                if str(e.get('source_filename', '')).lower() in source_file_str.lower()
            ]
            if not matching_entries:
                continue

            candidates = []
            for e in matching_entries:
                if 'locations' in e:
                    candidates.extend(e['locations'])
                else:
                    candidates.append(e)

            m, s = resolve_location_candidates(
                candidates, station, station_known, first_baro_val, second_baro_val
            )
            if m:
                yaml_month, yaml_station = m, s

    if yaml_station:
        station = str(yaml_station).strip().lower()

    # determine year with metadata source filename fallback
    year_match = re.search(r"(18|19)\d{2}", name_no_id)
    if not year_match:
        year_match = re.search(r"(18|19)\d{2}", parent)
    
    used_meta_fallback = False # track how many times we get year from source filename (e.g. p24_1884.jpg)

    if year_match:
        year = year_match.group(0)
    elif meta_year:
        year = meta_year
        used_meta_fallback = True # trigger tracker
    else:
        year = "unknown-year"

    # determine Month
    safe_months = {
        "january": "january", 
        "february": "february", "febuary": "february", 
        "september": "september", "sept": "september",
        "october": "october", 
        "november": "november", 
        "december": "december"
    }
    risky_months = {
        "march": "march", "mar": "march",
        "april": "april", "apr": "april",
        "may": "may", 
        "june": "june", "jun": "june",
        "july": "july", "jul": "july",
        "august": "august", "aug": "august",
        "jan": "january", 
        "feb": "february", 
        "sep": "september", 
        "oct": "october", 
        "nov": "november", 
        "dec": "december"
    }
    found_month = "unknownmonth"
    
    for k, v in safe_months.items():
        if k in name:
            found_month = v
            break

    if found_month == "unknownmonth":
        for k, v in risky_months.items():
            pattern = r"(?:^|[^a-z])" + k + r"(?:$|[^a-z])"
            if re.search(pattern, name):
                found_month = v
                break
            
    if found_month == "unknownmonth":
        num_match = re.search(r"[_-](0[1-9]|1[0-2])[_-]", name)
        if num_match:
            try:
                m_num = int(num_match.group(1))
                months_list = ["", "january", "february", "march", "april", "may", "june", 
                               "july", "august", "september", "october", "november", "december"]
                found_month = months_list[m_num]
            except:
                pass
    
    # apply YAML fallback for unknowns
    if found_month == "unknownmonth" and yaml_month:
        month_expander = {
            "jan": "january", "feb": "february", "mar": "march", "apr": "april",
            "may": "may", "jun": "june", "jul": "july", "aug": "august",
            "sep": "september", "oct": "october", "nov": "november", "dec": "december"
        }
        # Expand month name or leave if already a full name
        yaml_month_lower = str(yaml_month).strip().lower()
        found_month = month_expander.get(yaml_month_lower, yaml_month_lower)
    
    return f"{logbook}_{station}_{found_month}_{year}.csv", station, found_month, year, used_meta_fallback
    

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


def deduplicate_headers(header):
    """Ensures column names are unique by appending .1, .2, etc."""
    counts = {}
    new_header = []
    for col in header:
        if col not in counts:
            counts[col] = 0
            new_header.append(col)
        else:
            counts[col] += 1
            new_header.append(f"{col}.{counts[col]}")
    return new_header

def split_veer_force_token(t, current_year):
    """
    Splits a combined wind veer+force token into (veer, force).
    Handles: space-delimited ("20 4"), concatenated ("204", "167"),
    concatenated with a force range ("184-5"), and missing-veer placeholders
    ("-1", "— 1").

    Veer depends on era:
      - 1912-1917: points system, even values 0-32
      - 1918+: degrees, 0-360 (any integer, not just even)
    """
    if 1912 <= current_year <= 1917:
        VALID_VEERS = {str(v) for v in range(0, 34, 2)}      # 0,2,...,32
        veer_max_len = 2
    else:
        VALID_VEERS = {str(v) for v in range(0, 361)}         # 0..360
        veer_max_len = 3

    if t is None:
        return np.nan, np.nan
    t = str(t).strip()
    if t == "" or t.upper() in ("NA", "NULL"):
        return np.nan, np.nan

    # Whitespace-delimited: trust the delimiter, no need to validate the veer value
    m_space = re.match(r'^(\S+)\s+(\S+)$', t)
    if m_space:
        return m_space.group(1), m_space.group(2)

    # Missing veer: leading dash then a force value
    m_missing = re.match(r'^[-—–]+\s*(\d+(?:\.\d+)?)$', t)
    if m_missing:
        return np.nan, m_missing.group(1)

    # Concatenated: "204", "167", "184-5", or (post-1918) "3204" etc.
    m_concat = re.match(r'^(\d+)(?:[-—–](\d+(?:\.\d+)?))?$', t)
    if m_concat:
        digit_run = m_concat.group(1)
        hyphen_suffix = m_concat.group(2)

        # Try the longest valid veer prefix first (era-dependent max length)
        for length in range(min(veer_max_len, len(digit_run) - 1), 0, -1):
            candidate = digit_run[:length]
            if candidate in VALID_VEERS:
                force = digit_run[length:]
                if hyphen_suffix:
                    force = f"{force}-{hyphen_suffix}" if force else hyphen_suffix
                return candidate, force

    return np.nan, np.nan

def fix_calm_force_ocr(df, filename, report_list):
    """
    Fixes OCR misreading '0' as the letter 'c'/'C' in the Wind Force column
    immediately following a 'Calm' wind direction value (e.g. "Calm, c" should
    be "Calm, 0"). Runs before split_wind_columns so force columns are clean
    digits-only before classification.
    """
    dir_col_indices = [
        i for i, c in enumerate(df.columns)
        if "wind" in str(c).lower() and "direction" in str(c).lower()
        and "force" not in str(c).lower()  # skip still-combined columns
    ]

    for dir_idx in dir_col_indices:
        force_idx = dir_idx + 1
        if force_idx >= len(df.columns):
            continue

        for row_idx in range(len(df)):
            dir_val = df.iloc[row_idx, dir_idx]
            force_val = df.iloc[row_idx, force_idx]

            if pd.api.types.is_scalar(dir_val) and pd.isna(dir_val):
                continue
            if str(dir_val).strip().lower() != "calm":
                continue

            if pd.api.types.is_scalar(force_val) and pd.isna(force_val):
                continue

            s_force = str(force_val).strip()
            if s_force in ("c", "C"):
                df.iat[row_idx, force_idx] = "0"
                report_list.append({
                    "File": filename,
                    "Column": df.columns[force_idx],
                    "Row Index": row_idx,
                    "Original Value": s_force,
                    "Corrected Value": "0",
                    "Note": "OCR 'c' after Calm corrected to 0"
                })
    return df

def fix_force_column_ocr_junk(df, filename, report_list):
    """
    Fixes OCR artifacts (stray punctuation, ink smudges misread as quotes,
    commas, etc.) appearing alone in Wind Force cells, e.g. '","'.
    Only strips cells that are PURE junk with no digits at all — genuine
    values like '5-6' (a force range) or 'NA' are left untouched.
    """
    force_col_indices = [i for i, c in enumerate(df.columns) if "wind" in str(c).lower() and "force" in str(c).lower()]

    junk_pattern = re.compile(r'^[\s",\'\.\-—–_*]+$')  # only punctuation/quote/dash/space chars, no digits/letters

    for col_idx in force_col_indices:
        col_name = df.columns[col_idx]
        for row_idx in range(len(df)):
            val = df.iloc[row_idx, col_idx]
            if pd.api.types.is_scalar(val) and pd.isna(val):
                continue

            s_val = str(val).strip()
            if s_val in ("", "NA", "NULL", "Null", "null"):
                continue

            if junk_pattern.match(s_val):
                df.iat[row_idx, col_idx] = "NA"
                report_list.append({
                    "File": filename,
                    "Column": col_name,
                    "Row Index": row_idx,
                    "Original Value": s_val,
                    "Corrected Value": "NA",
                    "Note": "OCR junk/smudge cleared from Force cell"
                })
    return df

def split_wind_columns(df, year_str, filename, report_list):
    """
    Dynamically splits wind columns by analyzing the ACTUAL DATA inside them.
    Includes robust checks to prevent splitting columns that are already perfectly separated.
    """
    actions = []

    try:
        current_year = int(year_str)
    except (ValueError, TypeError):
        current_year = 1890
    
    if not df.empty:
        is_mean = df.iloc[:, 0].astype(str).str.lower().str.contains("mean", na=False)
    else:
        is_mean = pd.Series([False] * len(df))
    
    # 1. Identify all wind-related columns
    wind_cols = [i for i, c in enumerate(df.columns) if any(w in str(c).lower() for w in ["wind", "veer", "speed"])]
    
    skip_next = False
    
    for idx_i, c_idx in enumerate(wind_cols):
        if skip_next:
            skip_next = False
            continue
            
        c_name = str(df.columns[c_idx])
        c_lower = c_name.lower()
        
        # Peek at data
        s_data = df.iloc[:, c_idx].astype(str)[~is_mean].replace(["NA", "<NA>", "nan", "None", ""], "")
        s_data = s_data[s_data != ""]
        
        has_letters = s_data.str.contains(r'[a-zA-Z]', regex=True).any()
        has_digits  = s_data.str.contains(r'\d', regex=True).any()

        next_c_idx = wind_cols[idx_i + 1] if idx_i + 1 < len(wind_cols) else None

        # --- A. CHECK IF ALREADY SPLIT WITH THE NEXT COLUMN ---
        if next_c_idx == c_idx + 1: 
            next_c_name = str(df.columns[next_c_idx])
            next_c_lower = next_c_name.lower()
            
            next_data = df.iloc[:, next_c_idx].astype(str)[~is_mean].replace(["NA", "<NA>", "nan", "None", ""], "")
            next_data = next_data[next_data != ""]
            
            next_has_letters = next_data.str.contains(r'[a-zA-Z]', regex=True).any()
            next_has_digits = next_data.str.contains(r'\d', regex=True).any()
            
            # Condition 1: 4 Wind Columns Total (Classic Dir, Force, Dir, Force layout)
            if len(wind_cols) == 4 and idx_i in [0, 2]:
                skip_next = True
                continue
                
            # Condition 2: Headers explicitly mark the ends as Dir vs Force
            curr_is_dir = any(x in c_lower for x in ["dir.", "(16)"]) or c_lower.endswith("dir") or "dir" in c_lower.split()[-2:]
            next_is_force = next_c_lower.endswith("force") or next_c_lower.endswith("speed") or "force" in next_c_lower.split()[-2:]
            
            if curr_is_dir and next_is_force:
                skip_next = True
                continue
                
            # Condition 3: Data explicitly split (e.g., letters in col 1, digits in col 2)
            if has_letters and not has_digits and next_has_digits and not next_has_letters:
                skip_next = True
                continue

        # --- B. DETERMINE ISOLATED COLUMN ACTION ---
        is_combined = False
        
        if has_letters and has_digits:
            is_combined = True
            
        elif current_year >= 1912 and not has_letters and has_digits:
            has_space_split = s_data.str.contains(r'^\d{1,3}\s+\d*\.?\d+$', regex=True).any()
            if has_space_split:
                is_combined = True
            elif len(wind_cols) <= 2: 
                has_concat_split = s_data.str.contains(r'^\d{2,4}(?:[-—–]\d{1,2})?$', regex=True).any()
                if has_concat_split:
                    is_combined = True
                    
        # NEW FALLBACK: If the column is 100% dashes/NAs (no letters, no digits)
        elif not has_letters and not has_digits:
            # If there are only 2 wind columns in the whole file, they are meant to be combined 9am/9pm
            if len(wind_cols) <= 2:
                is_combined = True

        if is_combined:
            actions.append((c_idx, "split", c_name))
        else:
            if has_letters and not has_digits:
                actions.append((c_idx, "pad_force", c_name))
            elif not has_letters and has_digits and current_year >= 1912 and len(wind_cols) <= 2:
                actions.append((c_idx, "pad_force", c_name))

    # --- C. EXECUTE ACTIONS IN REVERSE ---
    for c_idx, action, col_name in reversed(actions):
        col_lower = str(col_name).lower()
        
        time = "9 p.m." if "p.m." in col_lower or "pm" in col_lower or "21" in col_lower else "9 a.m."
        suffix = f" {time}" if time else ""

        if action == "split":
            # Note: relies on your existing clean_numeric_string and split_veer_force_token functions
            s_clean = df.iloc[:, c_idx].astype(str).apply(clean_numeric_string)
            s_clean = s_clean.replace(["NA", "<NA>", "nan", "None"], "")

            if current_year >= 1912:
                split_results = s_clean.apply(lambda t: split_veer_force_token(t, current_year))
                direction = split_results.apply(lambda x: x[0]).astype("object")
                force = split_results.apply(lambda x: x[1]).astype("object")
            else:
                # pre-1912 logic (Handles -, W -, and numbers perfectly)
                direction = s_clean.str.extract(r"([A-Za-z\-\.\s\(\)]+)", expand=False).str.strip()
                force = s_clean.str.extract(r"([-—–]?\d+(?:\.\d+)?(?:[-—–]\d+(?:\.\d+)?)?|[Nn][Uu][Ll][Ll])", expand=False)
            
            # standard cleaning
            direction = direction.str.replace(r'[Nn][Uu][Ll][Ll]', '', regex=True).str.strip()
            
            if current_year < 1912:
                # Forces pure '-' to become np.nan
                direction = direction.where(direction.str.contains(r'[A-Za-z]', na=False), np.nan)
            
            # Cleans trailing dashes from things like "W -"
            direction = direction.str.rstrip('- ')
            force = force.str.replace(r'(?i)^null$', 'NA', regex=True)

            df.insert(c_idx, f"Wind Direction{suffix}", direction, allow_duplicates=True)
            df.insert(c_idx + 1, f"Wind Force{suffix}", force, allow_duplicates=True)
            df.drop(df.columns[c_idx + 2], axis=1, inplace=True)
            
        elif action == "pad_force":
            df.insert(c_idx + 1, f"Wind Force{suffix}", "NA", allow_duplicates=True)
            df.rename(columns={df.columns[c_idx]: f"Wind Direction{suffix}"}, inplace=True)
        
    # Clean nulls/NaNs from all wind columns (turns np.nan into "NA")
    wind_cols_final = [c for c in df.columns if "wind" in str(c).lower()]
    for col in wind_cols_final:
        s = df[col].astype(str)
        s = s.replace(r'(?i)^\s*null\s*$', 'NA', regex=True)
        s = s.replace(["<NA>", "nan", "NaN", "None", ""], "NA")
        df[col] = s

    return df

def fix_wind_force_hyphens(df, filename, hyphen_report_list):
    """
    Deals with hyphenated values in Wind Force (e.g., '5-6').
    - If Cronkbourne, Plymouth, Scarborough, Oscott, Hastings, Glenalmond, Strathfield Turgiss: Preserves '5-6'.
    - If other: Replaces hyphen with decimal ('5.6').
    """
    # Find column indices that contain "wind" and "force"
    force_col_indices = [i for i, c in enumerate(df.columns) if "wind" in str(c).lower() and "force" in str(c).lower()]
    
    fname_lower = filename.lower()
    is_exempt_station = any(station in fname_lower for station in ["cronkbourne", "plymouth", "scarborough", "oscott", "hastings", "glenalmond", "strathfield", "hawes",
    "douglas", "killarney", "uppingham", "birr"])

    for col_idx in force_col_indices:
        col_name = df.columns[col_idx]
        
        for row_idx in range(len(df)):
            # Use iloc to guarantee we get a single scalar value
            val = df.iloc[row_idx, col_idx]
            
            # Now we can safely check if it's NA
            # We use pd.api.types.is_scalar to ensure it's not a list/series
            if pd.api.types.is_scalar(val) and pd.isna(val):
                continue
            if str(val).strip() == "NA":
                continue
                
            s_val = str(val).strip()
            
            # Regex: exactly "digit(s)-digit(s)"
            match = re.match(r'^(\d+)\s*[-—–]+\s*(\d+)$', s_val)
            
            if match:
                if is_exempt_station:
                    continue # Preserve string
                else:
                    # Convert to decimal
                    new_val_str = f"{match.group(1)}.{match.group(2)}"
                    new_val = float(new_val_str)
                    
                    # Update DataFrame
                    df.iat[row_idx, col_idx] = new_val
                    
                    # Log
                    hyphen_report_list.append({
                        "File": filename,
                        "Column": col_name,
                        "Row Index": row_idx,
                        "Original Value": f"'{s_val}",
                        "Corrected Value": f"'{new_val}",
                        "Note": "Hyphen replaced with decimal"
                    })
                    
    return df

def tidy_wind_direction(df, filename, report_list):
    """
    cleans wind direction columns:
    1. removes all space
    2. replaces 'b.' or 'b' with 'by'
    3. capitalises all letters except 'by' and 'alm' in 'Calm'
    """
    dir_col_indices = [i for i, c in enumerate(df.columns) if "wind" in str(c).lower() and "direction" in str(c).lower()]

    for col_idx in dir_col_indices:
        col_name = df.columns[col_idx]
        force_col_idx = col_idx + 1
        
        for row_idx in range(len(df)):
            # Safely grab a single cell using iloc
            val = df.iloc[row_idx, col_idx]
            
            if pd.api.types.is_scalar(val) and pd.isna(val):
                continue
            if str(val).strip() in NA_VALUES:
                continue

            orig_val = str(val)
            s = orig_val.strip()

            # Gemini OCR fix: Dir: "NI" or "N I" -> Dir: "N", Force: "1" ---
            # Matches compass points (N, NE, SSW, etc) or CALM followed exactly by 'I' or 'i'
            match_i = re.match(r'^([NESWnesw]{1,3}|[Cc][Aa][Ll][Mm])\s*[Ii]$', s)
            if match_i:
                s = match_i.group(1).upper() # Keep just the compass point
                df.iat[row_idx, force_col_idx] = "1" # Push '1' to the Force column
                
                report_list.append({
                    "File": filename, "Column": col_name, "Row Index": row_idx,
                    "Original Value": orig_val, "Corrected Value": f"Dir: {s}, Force: 1"
                })
            
            # Gemini OCR fix: "Calm, o" -> Dir: "Calm", Force: "0" ---
            # Matches 'Calm' followed by spaces/commas and 'o', 'O', or '0'
            match_o = re.match(r'^([Cc][Aa][Ll][Mm])[\s,]*[oO0]$', s)
            if match_o:
                s = "Calm"
                df.iat[row_idx, force_col_idx] = "0" # Push '0' to the Force column
                
                report_list.append({
                    "File": filename, "Column": col_name, "Row Index": row_idx,
                    "Original Value": orig_val, "Corrected Value": "Dir: Calm, Force: 0"
                })

            # e.g., 'Calm. 0' leaves behind 'Calm.' in the direction string
            s = s.rstrip('.,')

            # remove all spaces
            s = s.replace(' ', '')

            # uppercase all letters first to standardise
            s = s.upper()

            # if compass letter precedes 'b' then 'by'
            s = re.sub(r'(?<=[NSEW])B\.?(?=[NSEW])', 'by', s)

            # replacements for 'b.' and 'b' to become 'by'
            s = re.sub(r'\bB\.?\b', 'by', s)

            # lowercase for only 'by'
            s = s.replace('BY', 'by').replace('CALM', 'Calm')

            if s != orig_val:
                df.iat[row_idx, col_idx] = s
                report_list.append({
                    "File": filename,
                    "Column": col_name,
                    "Row Index": row_idx,
                    "Original Value": orig_val,
                    "Corrected Value": s
                })
    return df


def fix_pressure(series, filename, col_name, asterisk_list, decimal_list):
    """
    For years before 1912, fix shorthand pressure values.
    *.29 -> .29 -> 29.29 (using bookended prefixes)
    *29 -> .29 -> 29.29 (using bookended prefixes)
    Example: 29.5 -> 29.5, .02 -> 29.02 (using bookended prefixes).
    Handles cleaning of quotes and commas.
    """
    bookended_prefixes = None
    out = []

    for idx, val in series.items():
        if pd.isna(val) or str(val) == "NA":
            out.append("NA")
            continue

        s_val = str(val).strip()
        has_asterisk = "*" in s_val
        clean_s = s_val.replace("*", "").replace("'", ".").replace('"', "").replace(",", ".")
        
        # replace space with dot e.g. '29 01' becomes '29.01'
        clean_s = re.sub(r'^(\d+)\s+(\d+)$', r'\1.\2', clean_s.strip())

        # fix rogue leading decimal places (eg.g '.29'99' becomes '.29.99' which becomes '29.99')
        # if value starts with a decimal place and has a second decimal place, strip the first one
        if clean_s.startswith(".") and clean_s.count(".") > 1:
            clean_s = clean_s[1:] #drops the first character

        if not clean_s:
            out.append("NA")
            continue

        try:
            v = float(clean_s)
        except ValueError:
            # If float fails (e.g. "29.--"), see if it starts with 25 to 31
            prefix_match = re.match(r'^(2[5-9]|3[01])', clean_s)
            if prefix_match:
                bookended_prefixes = int(prefix_match.group(1))
            out.append(val) # Return original if it's text
            continue

        is_decimal_fixed = False # tracks decimal fixes for the decimal report
        final_val = None 
        has_decimal = "." in clean_s # checks if string already has a decimal point
                                    # deals with instances where '20.05' (mistranscription) became '30.2005'
                                    # this was due to the logic flow below for values < 25.0

        if has_asterisk and bookended_prefixes is not None:
            # *29 or *.29 becomes .29
            # check if value is actually a full reading with a rogue asterisk (30.13*)
            if has_decimal and 25.0 <= v <= 31.5:
                bookended_prefixes = int(v)
                final_val = round(v, 3)
            # otherwise let *29 become 29.29 (for example)
            elif v >= 1.0:
                if v < 100: decimal = v / 100.0
                else: decimal = v / 1000.0
                final_val = round(float(f"{bookended_prefixes}") + decimal, 3)
                is_decimal_fixed = True
            else:
                final_val = round(float(f"{bookended_prefixes}") + v, 3)
        # expected range for pressure values in inHg
        elif 25.00 <= v <= 31.5:
            bookended_prefixes = int(v)
            final_val = round(v, 3)
        # standard SSO shorthand pressure formatting fix
        elif v < 1.0 and bookended_prefixes is not None:
            # Handle .002 -> 29.002
            # logic: prefix + value
            final_val = round(float(f"{bookended_prefixes}") + v, 3)
        # deals with missing decimal points (either typewriting errors or Gemini mistranscription errors)
        elif not has_decimal and (v > 31.0 or (1.0 <= v < 25.0)) and bookended_prefixes is not None:
            if v < 100:
                decimal = v / 100.0 # 13 becomes 0.13
            else:
                decimal = v / 1000.0 # 580 becomes 0.580
            final_val = round(float(f"{bookended_prefixes}") + decimal, 3)
            is_decimal_fixed = True
        else:
            if 25.0 <= v <= 31.5:
                final_val = round(v, 3)
                bookended_prefixes = int(v)
            else:
                final_val = None  # leave for backfill
        out.append(final_val)
        
        if has_asterisk:
            report_asterisk(filename, col_name, idx, s_val, v, asterisk_list)
        if is_decimal_fixed:
            decimal_list.append({
                    "File": filename,
                    "Column": col_name,
                    "Row": idx,
                    "Original Value": val,
                    "Corrected Value": final_val
                })
    
    # now, if still required, back fill from end of the bookended prefixes
    bookended_prefixes = None
    for i in reversed(range(len(series))):
        val_out = out[i]

        # Only treat true full values as prefix setters
        if isinstance(val_out, (int, float)) and 25.0 <= val_out <= 31.5:
            bookended_prefixes = int(val_out)
            continue

        # If already resolved (e.g. forward-filled), skip
        if val_out is not None:
            continue

        val = series.iloc[i]

        if pd.isna(val) or str(val) == "NA":
            out[i] = "NA"
            continue

        s_val = str(val).strip()
        clean_s = s_val.replace("*", "").replace("'", ".").replace('"', "").replace(",", ".")

        try:
            v = float(clean_s)
        except ValueError:
            out[i] = val
            continue

        if bookended_prefixes is not None:
            if v < 1.0:
                out[i] = round(bookended_prefixes + v, 3)
            else:
                if v < 100:
                    decimal = v / 100.0
                else:
                    decimal = v / 1000.0
                out[i] = round(bookended_prefixes + decimal, 3)
        else:
            out[i] = "NA"

    return out

def fix_kelvin_temperature(series, filename, col_name):
    """
    For years 1912 and after, fix shorthand kelvin temperature values.
    Adds 200K to all values, unless Gemini has already added it (where the value will be >200) in which case leave as is
    E.g. 82.2 becomes 282.2
    allow for n and x to be in cell and still add 200
    n and x indicate min and max value in col, respectively
    """

    out = []

    for idx, val in series.items():
        if pd.isna(val) or str(val).strip() in NA_VALUES:
            out.append("NA")
            continue

        clean_s = clean_numeric_string(val)
        if clean_s == "NA":
            out.append("NA")
            continue
    
        # find numeric part of string (handles floats and integers)
        match = re.search(r'[-+]?\d*\.?\d+', clean_s)
        
        if match:
            num_str = match.group(0)
            try:
                v = float(num_str)
                
                # if the value is less than 200, it's shorthand. Add 200.
                if v < 200.0:
                    new_v = round(v + 200.0, 2)
                    
                    # replace only numeric part in string, leaving 'n', 'x', etc., attached
                    # e.g. "82.2n".replace("82.2", "282.2") -> "282.2n"
                    final_str = clean_s.replace(num_str, str(new_v), 1)
                    out.append(final_str)
                else:
                    # value is already >= 200, leave the whole string as is
                    out.append(clean_s)
                    
            except ValueError:
                out.append(val) # Fallback if math fails
        else:
            # No numbers found at all (e.g., pure text), just return original
            out.append(val)
    return out

def fix_vapour_tension(df, filename, current_year, decimal_list, implausible_report_list, asterisk_list):
    """
    for all files:
        cleans asterisks and logs
    for files pre-1912:
        amends leading decimal place so 390 inHg becomes 0.390
    for files 1912 and post:
        units change to mb so rules adapt
    """
    cols = [c for c in df.columns if "vapour" in str(c).lower() and ("tension" in str(c).lower() or "pressure" in str(c).lower())]
    for col in cols:
        col_data = df[col]
        if isinstance(col_data, pd.DataFrame):
            print(f"❌ Duplicate column name detected: {col!r} in {filename} - using first occurrence only")
            col_data = col_data.iloc[:, 0]
        for idx, val in col_data.items():
            if pd.isna(val) or str(val) in NA_VALUES:
                continue
            s_val = str(val)
            if "*" in s_val:
                clean_val_str = clean_numeric_string(s_val).replace("*",".")
                report_asterisk(filename, col, idx, s_val, clean_val_str, asterisk_list)
            else:
                clean_val_str = clean_numeric_string(s_val)
            if clean_val_str == "NA": continue
            try:
                f_val = float(clean_val_str)
            except ValueError:
                continue
            # pre-1912 logic (inHg)
            if current_year < 1912:
                if f_val >= 20.0:
                    # fix missing decimal: 289 becomes 0.289
                    if f_val.is_integer():
                        digits = str(int(f_val))
                    else:
                        digits = str(f_val).replace('.', '')
                    new_val = float(f"0.{digits}")
                    df.at[idx, col] = new_val
                    decimal_list.append({
                        "File": filename,
                        "Column": col,
                        "Row": idx,
                        "Original Value": val,
                        "Corrected Value": new_val
                    })
                elif f_val >= 1.0:
                    # log to implausible vapour pressure list
                    implausible_report_list.append({
                        "File": filename,
                        "Column": col,
                        "Row": idx,
                        "Original Value": val,
                        "Reason": f"Value >= 1.0 ({f_val})"
                    })
                else:
                    df.at[idx, col] = f_val
            # 1912 and post logic (millibars)
            else:
                if f_val >= 75.0:
                    implausible_report_list.append({
                        "File": filename, "Column": col, "Row": idx,
                        "Original Value": val, "Reason": f"Value >= 75.0 ({f_val})"
                    })
                else:
                    # Values like 15.0 or 25.0 are valid millibar readings, save as is.
                    df.at[idx, col] = f_val

    return df

def fix_wetbulb_depression(df, filename, decimal_list, implausible_wetbulb_report_list, asterisk_list):
    cols = [c for c in df.columns if "dep" in str(c).lower() and "wet" in str(c).lower()]
    for col in cols:
        col_data = df[col]
        if isinstance(col_data, pd.DataFrame):
            print(f"❌ Duplicate column name detected: {col!r} in {filename} - using first occurrence only")
            col_data = col_data.iloc[:, 0]
        for idx, val in col_data.items():
            if pd.isna(val) or str(val) in NA_VALUES:
                continue
            s_val = str(val)
            if "*" in s_val:
                clean_val_str = clean_numeric_string(s_val).replace("*",".")
                report_asterisk(filename, col, idx, s_val, clean_val_str, asterisk_list)
            else:
                clean_val_str = clean_numeric_string(s_val)
            if clean_val_str == "NA": continue
            try:
                f_val = float(clean_val_str)
            except ValueError:
                continue
            if f_val >= 20.0:
                if f_val.is_integer():
                    digits = str(int(f_val))
                else:
                    digits = str(f_val).replace('.', '')
                new_val = float(f"0.{digits}")
                df.at[idx, col] = new_val
                decimal_list.append({
                    "File": filename,
                    "Column": col,
                    "Row": idx,
                    "Original Value": val,
                    "Corrected Value": new_val
                })
            else:
                df.at[idx, col] = f_val
    return df

def fix_rain_column(df, filename, decimal_list):
    '''
    cleans rain column
    replaces blank or '-' with '0'
    fixes missing decimals (e.g. '030' -> '0.030', '170' -> '0.170')
    fixes leading deciamls (e.g. '.93' -> '0.93')
    '''
    rain_cols = [c for c in df.columns if "rain" in c.lower()]
    for col in rain_cols:
        df[col] = df[col].replace([r"^\s*$", "NA", "null", r"^\-$", r"^\-$", r"^\—$", r"^\---$", r"^\- $", r"^\--$", r"^\_$", r"^\.\.\.$"], "0", regex=True)
        for idx, val in df[col].items():
            s_val = str(val).strip()
            original_val = s_val
            # missing decimal fix ('030' becomes '0.030')
            if s_val.isdigit() and s_val != "0":
                s_val = "0." + s_val
                decimal_list.append({
                    "File": filename,
                    "Column": col,
                    "Row Index": idx,
                    "Original Value": f"'{original_val}", # makes sure the excel value is correctly formatted
                    "Corrected Value": f"'{s_val}"
                })
            # leading decimal fix ('.93' -> '0.93')
            elif s_val.startswith("."):
                s_val = "0" + s_val
                decimal_list.append({
                    "File": filename,
                    "Column": col,
                    "Row Index": idx,
                    "Original Value": f"'{original_val}",
                    "Corrected Value": f"'{s_val}"
                })
            # overwrite df cell with cleaned value
            df.at[idx,col] = s_val
    return df

def fix_sunshine_column(df):
    '''
    If there are some digits in the column, replace blank or '-' with '0'. 
    If there are no digits in the column, replace blank or '-' with NA.
    '''
    sunshine_cols = [c for c in df.columns if "sunshine" in c.lower()]
    for col in sunshine_cols:
        has_digits = df[col].astype(str).str.contains(r"\d", regex=True, na=False).any()
        replacement = "0" if has_digits else "NA"
        df[col] = df[col].replace(
            [r"^\s*$", "NA", "null", r"^\-$",r"^\-$", r"^\—$", r"^\---$", r"^\- $", r"^\--$", r"^\_$"], 
            replacement, 
            regex=True)
    return df

def fix_cloud_typos(df, filename, report_list):
    """
    fixes OCR issues in cloud cols
    1. 10 with weather symbols behind it can sometimes be read by Gemini as 100 or 1000
       caps any value >= 90 at 10 and logs the change
    2. '000' or '00' transcribed erroneously -> replaced with '0'
    """
    cloud_cols = [c for c in df.columns if "cloud" in str(c).lower()]

    for col in cloud_cols:
        # Use get_loc safely
        loc = df.columns.get_loc(col)
        col_idx = list(np.where(df.columns == col)[0])[0] if isinstance(loc, (slice, np.ndarray, list)) else loc
        
        for row_idx in range(len(df)):
            val = df.iloc[row_idx, col_idx]
            
            if pd.api.types.is_scalar(val) and pd.isna(val):
                continue
            if str(val).strip() in NA_VALUES:
                continue

            s_val = str(val).strip()
            
            # Matches strings that are exactly 2 or more zeros (e.g., '00', '000')
            if re.match(r'^0{2,}$', s_val):
                df.iat[row_idx, col_idx] = "0"
                
                report_list.append({
                    "File": filename,
                    "Column": col,
                    "Row Index": row_idx,
                    # Apostrophe prevents Excel from hiding the zeros
                    "Original Value": f"'{s_val}", 
                    "Corrected Value": "0",
                    "Note": "Multiple zeros corrected to 0"
                })
                continue

            clean_s = clean_numeric_string(s_val)

            if clean_s == "NA":
                continue

            try:
                v = float(clean_s)
            except ValueError:
                continue
            
            # 100≡ -> 10≡
            m = re.match(r'^\s*\d+(?:\.\d+)?(.*)$', s_val)
            suffix = m.group(1) if m else ""

            # if value >= 90, change to 10
            if v >= 90.0:
                new_val = f"10{suffix}"
                df.iat[row_idx, col_idx] = new_val
                
                # Log the change
                report_list.append({
                    "File": filename,
                    "Column": col,
                    "Row Index": row_idx,
                    "Original Value": s_val,
                    "Corrected Value": new_val,
                    "Note": "Cloud OCR typo (>=90) corrected to 10"
                })
                
    return df

def replace_and_log_apostrophe_fixes(df, filename, target_character, replacement_character, report_list):
    '''
    replace G3.1 mistranscriptions of . as ' with . and count
    '''
    for col in df.columns:
        s = df[col].astype(str)

        mask = s.str.contains(re.escape(target_character), regex=True, na=False)

        if mask.any():
            affected_indices = df[mask].index
            for idx in affected_indices:
                orig_val = df.at[idx, col]
                if pd.notna(orig_val):
                    new_val = str(orig_val).replace(target_character, replacement_character)
                    df.at[idx, col] = new_val
                    report_list.append({
                        "File": filename,
                        "Column": col,
                        "Row Index": idx,
                        "Target Character": target_character,
                        "Original Value": orig_val,
                        "Corrected Value": new_val
                    })
    return df

def fix_spaced_decimals(df, filename, report_list):
    """
    Fixes OCR typos where a space separates a decimal point, or a wrong character is used.
    (e.g., '48. 5' -> '48.5', '48° 5' -> '48.5', '10 * 2' -> '10.2')
    """
    for col in df.columns:
        if "remark" in str(col).lower():
            continue
            
        col_idx = df.columns.get_loc(col)
        for row_idx in range(len(df)):
            val = df.iloc[row_idx, col_idx]
            
            if pd.api.types.is_scalar(val) and pd.isna(val): continue
            if str(val).strip() in ["", "NA", "<NA>", "nan", "None"]: continue
                
            orig_val = str(val).strip()
            
            # space before symbol  e.g. "10 .2" or "10 *2"
            s_val = re.sub(r'(\d+)\s+[\.°*]\s*(\d+)', r'\1.\2', orig_val)
            # spaced after symbol e.g. "10. 2" or "10* 2"
            s_val = re.sub(r'(\d+)\s*[\.°*]\s+(\d+)', r'\1.\2', s_val)
            # wrong symbol between numbers e.g. "48°5" or "10*2"
            s_val = re.sub(r'(\d+)[°*](\d+)', r'\1.\2', s_val)

            if s_val != orig_val:
                df.iat[row_idx, col_idx] = s_val
                report_list.append({
                    "File": filename,
                    "Column": col,
                    "Row Index": row_idx,
                    "Original Value": orig_val,
                    "Corrected Value": s_val
                })
    return df

def fix_general_asterisks(df, filename, report_list):
    """
    Handles asterisks in all columns EXCEPT Barometer and Cloud.
    - Lone asterisk -> NA
    - Wind/Remarks -> Removes asterisk entirely (e.g. '* SW 19' -> 'SW 19')
    - '*.209' -> '.209'
    - Other cases -> Replaces with '.'
    """
    for col in df.columns:
        c_lower = str(col).lower()
        
        # Skip Barometer (handled by fix_pressure) and Cloud (user request)
        if "barometer" in c_lower or "cloud" in c_lower:
            continue
            
        is_text_col = "wind" in c_lower or "remark" in c_lower
        col_idx = df.columns.get_loc(col)
        
        for row_idx in range(len(df)):
            val = df.iloc[row_idx, col_idx]
            if pd.api.types.is_scalar(val) and pd.isna(val): continue
            if str(val).strip() in ["", "NA", "nan", "None", "<NA>"]: continue
            
            s_val = str(val).strip()
            if "*" not in s_val: continue
            
            orig_val = s_val
            
            # Lone asterisk -> NA
            if re.match(r'^\s*\*\s*$', s_val):
                s_val = "NA"
            # Text columns -> just remove the asterisk
            elif is_text_col:
                s_val = s_val.replace("*", "").strip()
            # `*.` -> `.`  (*.209 becomes .209)
            elif "*." in s_val:
                s_val = s_val.replace("*.", ".")
            # Anything else -> replace with dot
            else:
                s_val = s_val.replace("*", ".")
                
            if s_val != orig_val:
                df.iat[row_idx, col_idx] = s_val
                
                # Log to the asterisk report
                report_list.append({
                    "File": filename,
                    "Column": col,
                    "Row Index": row_idx,
                    "Original Value": orig_val,
                    "Corrected Value": s_val
                })
    return df

def fix_global_ocr_I_to1(df, filename, report_list):
    """
    Replaces letter 'I' or 'i' with number '1'
    Skips Day and Wind Direction columns
    Uses regex to avoid replacing 'i' inside real words (like 'Station')
    """
    # Find column indices to safely avoid pandas duplicate-name errors
    target_col_indices = [
        i for i, c in enumerate(df.columns)
        if "direction" not in str(c).lower()
    ]
    
    for col_idx in target_col_indices:
        col_name = str(df.columns[col_idx])
        
        for row_idx in range(len(df)):
            val = df.iloc[row_idx, col_idx]
            
            if pd.api.types.is_scalar(val) and pd.isna(val):
                continue
            if str(val).strip() in ["", "NA", "nan", "None", "<NA>"]:
                continue
                
            s_val = str(val).strip()
            
            # Case sensitive check for I or i
            if 'I' in s_val or 'i' in s_val:
                
                # must not be inside a word. replace with 1
                new_val = re.sub(
                    r'(?<![A-Za-z])[Ii]+(?![A-Za-z])',
                    lambda m: "1" * len(m.group(0)),
                    s_val
                )
                
                if new_val != s_val:
                    df.iat[row_idx, col_idx] = new_val
                    
                    report_list.append({
                        "File": filename,
                        "Column": col_name,
                        "Row Index": row_idx,
                        "Original Value": s_val,
                        "Corrected Value": new_val
                    })
                
    return df

def fix_rogue_leading_dots(df, filename, report_list):
    """
    Fixes typos where an extra dot was placed at the start of a number.
    e.g., '.53.4' becomes '53.4'.
    Excludes valid shorthand like '.53' by requiring two dots to trigger.
    """
    for col in df.columns:
        # Skip remarks
        if "remark" in str(col).lower():
            continue
            
        col_idx = df.columns.get_loc(col)
        for row_idx in range(len(df)):
            val = df.iloc[row_idx, col_idx]
            
            if pd.api.types.is_scalar(val) and pd.isna(val): continue
            if str(val).strip() in ["", "NA", "<NA>", "nan", "None"]: continue
                
            orig_val = str(val).strip()
            
            # Regex: Starts with a dot, followed by digits, another dot, and digits
            match = re.match(r'^\.(\d+\.\d+)$', orig_val)
            
            if match:
                # Group 1 contains the string without the leading dot
                s_val = match.group(1)
                
                df.iat[row_idx, col_idx] = s_val
                
                report_list.append({
                    "File": filename,
                    "Column": col,
                    "Row Index": row_idx,
                    "Original Value": orig_val,
                    "Corrected Value": s_val,
                    "Note": "Removed rogue leading dot"
                })
                
    return df

def fix_gravity_correction(meta_rows, filename, report_list):
    """
    Scans metadata rows for gravity_correction.
    If transcribed as a whole number (e.g., '24' or '24 in'), 
    it fixes it to '+.024' or '+.024 in' and logs to the report.
    """
    for row_idx, row in enumerate(meta_rows):
        if not row:
            continue
            
        # Check if this row is the gravity correction row
        if "gravity_correction" in str(row[0]).lower():
            # The value is in the next cell (because of the comma)
            if len(row) > 1:
                orig_val = str(row[1]).strip()
                
                # Regex looks for digits, optionally followed by space and letters (units)
                # Matches: "24", "24 in", "3", "105 in"
                # Ignores already correct values like "+.032 in" because of the '+' and '.'
                match = re.match(r'^(\d+)(\s*[a-zA-Z]*)$', orig_val)
                
                if match:
                    num_part = match.group(1)
                    unit_part = match.group(2)
                    
                    # zfill(3) ensures '3' becomes '003', '24' becomes '024'
                    corrected = f"+.{num_part.zfill(3)}{unit_part}"
                    
                    # Update the metadata row in place
                    row[1] = corrected
                    
                    report_list.append({
                        "File": filename,
                        "Row Index": row_idx,
                        "Original Value": orig_val,
                        "Corrected Value": corrected
                    })
                    
    return meta_rows

def fix_transposed_nx(df, filename, report_list):
    """
    Fixes OCR typos where 'n' or 'x' (min/max indicators) are trapped inside a number.
    e.g., '2n86' -> 'n286', '2x99' -> 'x299'
    """
    for col in df.columns:
        if "remark" in str(col).lower():
            continue
            
        col_idx = df.columns.get_loc(col)
        for row_idx in range(len(df)):
            val = df.iloc[row_idx, col_idx]
            
            if pd.api.types.is_scalar(val) and pd.isna(val): continue
            if str(val).strip() in ["", "NA", "<NA>", "nan", "None"]: continue
                
            orig_val = str(val).strip()
            
            # Regex breakdown:
            # ^(\d+\.?\d*) : Group 1 -> The leading digits (e.g., '2' or '2.')
            # ([nxNX])     : Group 2 -> The trapped letter 'n' or 'x'
            # ([\d\.]+)$   : Group 3 -> The trailing digits/dots (e.g., '86')
            match = re.match(r'^(\d+\.?\d*)([nxNX])([\d\.]+)$', orig_val)
            
            if match:
                # Reconstruct putting Group 2 (the letter) at the front
                s_val = f"{match.group(2)}{match.group(1)}{match.group(3)}"
                
                df.iat[row_idx, col_idx] = s_val
                
                report_list.append({
                    "File": filename,
                    "Column": col,
                    "Row Index": row_idx,
                    "Original Value": orig_val,
                    "Corrected Value": s_val,
                    "Note": "Transposed n/x indicator moved to front"
                })
                
    return df

def export_report(data, path, label, empty_message=None, use_csv=True):

    if not data:
        print(empty_message or f"No {label.lower()} found")
        return

    print(f"Found {len(data)} {label.lower()}. Saving report")

    df = pd.DataFrame(data)

    path.parent.mkdir(parents=True, exist_ok=True)

    output_path = path.with_suffix(".csv") if use_csv else path

    try:

        if use_csv:
            if "unicode" in label.lower():
                df.to_csv(output_path, index=False, encoding="utf-8-sig", escapechar='\\')
            else:
                # Standard CSV export for everything else
                df.to_csv(output_path, index=False, encoding="utf-8-sig")
        else:
            df.to_excel(output_path, index=False)

        print(f"{label} report saved to: {output_path}")

    except Exception as e:
        print(f"Failed saving report to: {output_path}")
        print(f"Actual error: {e}")


# -------------------- MAIN LOOP --------------------
collected_unicode_fixes = []
collected_notes = []
collected_decimal_added_fixes = []
collected_implausible_vapour = []
collected_implausible_wetbulb_depression = []
collected_asterisk_fixes = []
collected_wind_hyphen_decimal_fixes = []
collected_wind_tidy_fixes = []
collected_symbol_i_fixes = []
collected_merged_cells = []
collected_fixed_spaced_decimals = []
collected_cloud_10_fixes = []
collected_year_rescued_from_sourcefilename = []
collected_duplicate_files = []
collected_gravity_correction_fixes = []
collected_duplicate_columns = []
collected_transposed_nx = []
collected_rogue_leading_decimals = []

for current_input_folder in input_folders:
    print(f"\n{'='*40}")
    print(f"Scanning Input Folder: {current_input_folder}")
    print(f"{'='*40}")
    
    if not current_input_folder.exists():
        print(f"❌ Folder not found, skipping: {current_input_folder}")
        continue

    # Get the list of all files in this folder
    files = list(current_input_folder.rglob("*.csv"))
    print(f"Found {len(files)} files in {current_input_folder.name}")
    
    if len(files) == 0:
        continue
            
    # Loop through the files using enumerate to track progress
    for idx_file, csv_file in enumerate(files):
        print(f"--- STARTING FILE {idx_file + 1}/{len(files)}: {csv_file.name} ---")

        # Read raw rows first
        try:
            rows = read_and_fix_unicode(csv_file, csv_file.name, collected_unicode_fixes)
        except Exception as e:
            print(f"❌ Error reading {csv_file}: {e}")
            continue
        
        # Fix any Excel formatting issues introduced by the manual fixes
        rows = fix_excel_corruptions(rows)

        # Fix any incorrect whitespace from gemini output
        rows = normalize_cell_whitespace(rows)

        # safety: did the file return empty?
        if not rows:
            print(f"❌ Skipping {csv_file.name}: File is empty.")
            continue
            
        # extract source_filename for year fallback
        # scans first 10 rows for "# SOURCE_FILENAME" to rescue the year
        # extract source_filename for year fallback
        meta_year = None
        source_file_str = None
        for r in rows[:10]:
            r_str = " ".join([str(c) for c in r]).upper()
            if "SOURCE_FILENAME" in r_str:
                source_file_str = r_str
                ymatch = re.search(r"(18|19)\d{2}", r_str)
                if ymatch:
                    meta_year = ymatch.group(0)
                break
        
        # find barometer values to distinguish between unknown csvs 
        first_baro_val = None
        second_baro_val = None
        
        if source_file_str:
            try:
                temp_hdr_idx = find_header_index(rows)
                if temp_hdr_idx is not None:
                    t_hdr = rows[temp_hdr_idx]

                    am_hour, pm_hour, _, _, uses_h_notation = detect_observation_hours(t_hdr)

                    am_meridiem = None if uses_h_notation else 'am'
                    pm_meridiem = None if uses_h_notation else 'pm'

                    b_am_idx = next((i for i, c in enumerate(t_hdr) if ("barometer" in str(c).lower() or "air pressure" in str(c).lower()) and hour_in_header(am_hour, str(c).lower(), am_meridiem)), -1)
                    b_pm_idx = next((i for i, c in enumerate(t_hdr) if ("barometer" in str(c).lower() or "air pressure" in str(c).lower()) and hour_in_header(pm_hour, str(c).lower(), pm_meridiem)), -1)

                    for r in rows[temp_hdr_idx+1 : temp_hdr_idx+10]:
                        if first_baro_val is None and b_am_idx != -1 and b_am_idx < len(r):
                            raw_am = str(r[b_am_idx]).strip()
                            if raw_am == "" or raw_am.lower() == "null":
                                first_baro_val = "NA" # if input cell is empty, match with YAML of NA
                            else:
                                v_am = clean_numeric_string(raw_am)
                                v_am = v_am.replace("°", ".").replace("'", ".").replace("·", ".").replace("•", ".")
                                v_am = re.sub(r'(?<![a-zA-Z])[Ii](?![a-zA-Z])', '1', v_am)
                                if re.match(r'^-?\d*\.?\d+$', v_am):
                                    first_baro_val = v_am

                        if second_baro_val is None and b_pm_idx != -1 and b_pm_idx < len(r):
                            raw_pm = str(r[b_pm_idx]).strip()
                            if raw_pm == "" or raw_pm.lower() == "null":
                                second_baro_val = "NA"
                            else:
                                v_pm = clean_numeric_string(raw_pm)
                                v_pm = v_pm.replace("°", ".").replace("'", ".").replace("·", ".").replace("•", ".")
                                v_pm = re.sub(r'(?<![a-zA-Z])[Ii](?![a-zA-Z])', '1', v_pm)
                                if re.match(r'^-?\d*\.?\d+$', v_pm):
                                    second_baro_val = v_pm

                        if first_baro_val is not None and second_baro_val is not None:
                            break
            except Exception:
                pass

        # make folder and filenames
        relative_folder = csv_file.parent.relative_to(current_input_folder)
        # clean station and filename
        new_filename, clean_station, clean_month, clean_year, used_meta_fallback = filename_convention(csv_file, current_input_folder, unknown_station_month_config, 
                                                                              source_file_str, meta_year, 
                                                                              first_baro_val, second_baro_val)

        if used_meta_fallback:
            collected_year_rescued_from_sourcefilename.append({
                "Original File": csv_file.name,
                "Rescued Year": meta_year,
                "New Filename": new_filename})

        # format folder name
        clean_folder_name = clean_station.title()

        out_file = output_dir / clean_folder_name / new_filename
        out_file.parent.mkdir(parents=True, exist_ok=True)

        # Overwrite prevention: if the filename already exists, append _1, _2, etc. to the filename
        original_out_file = out_file
        counter = 1
        is_duplicate = False
        while out_file.exists():
            is_duplicate = True
            # Create a new name like: sso_station_january_1899_1.csv
            new_name = f"{original_out_file.stem}_{counter}{original_out_file.suffix}"
            out_file = original_out_file.parent / new_name
            counter += 1
            
        # Update new_filename variable just in case we need it for printing
        new_filename = out_file.name
        if is_duplicate:
            collected_duplicate_files.append({
                "Input File": csv_file.name,
                "Actual Output Name": new_filename
            })
        print(f"Processing {csv_file.name} > {new_filename}")

        # trigger switchboard approach to get correct final headers for the specified year
        year_match = re.search(r"(18|19)\d{2}", new_filename)
        csv_year = year_match.group(0) if year_match else None
        schema = get_schema(csv_year)
        target_headers = schema["headers"]

        # ---- find header ----
        try:
            header_idx = find_header_index(rows)
        except ValueError as e:
            print(f"❌ Skipping {csv_file.name}: {e}")
            continue

        # ---- split structure ----
        raw_meta_rows = rows[:header_idx]
        header = rows[header_idx]
        data_rows = rows[header_idx + 1:]

        # preserves station-specific metadata from column headers such as hours of observation and wind force units
        target_headers = customise_target_headers(target_headers, header)
        th_counts = {}
        for h in target_headers:
            th_counts[h] = th_counts.get(h, 0) + 1
        th_dupes = [h for h, n in th_counts.items() if n > 1]
        if th_dupes:
            print(f"❌ customise_target_headers PRODUCED DUPLICATES in {csv_file.name}: {th_dupes}")
            collected_duplicate_columns.append({
                "File": csv_file.name,
                "Duplicate Columns": ", ".join(th_dupes),
                "Raw Header": header,
                "Source": "customise_target_headers",
            })
        target_headers = deduplicate_headers(target_headers)

        # split merged comma cells e.g. "84, 78"
        # expands row back to correct lenght before pandas
        data_rows = fix_merged_comma_cells(data_rows, csv_file.name, collected_merged_cells)

        # metadata notes extraction
        meta_rows = process_metadata_notes(raw_meta_rows, csv_file.name, collected_notes)

        # clean title
        meta_rows = clean_metadata_title(meta_rows)

        # fix gravity corrections eg 24 -> +.024
        meta_rows = fix_gravity_correction(meta_rows, csv_file.name, collected_gravity_correction_fixes)
        
        # insert station, month and year into CSV title if previously unknown
        for r in meta_rows:
            if r and "title" in str(r[0]).lower():
                # Format as: "Station Month Year" (e.g. "Cronkbourne May 1893")
                station_display = clean_station.replace('_', ' ').title()
                month_display = clean_month.title()
                
                perfect_title = f"{station_display} {month_display} {clean_year}"
                
                # Overwrite the OCR text sitting in the second cell
                if len(r) > 1:
                    r[1] = perfect_title
                else:
                    r.append(perfect_title)
                break

        # ---- Deduplicate Headers ----
        header = deduplicate_headers(header)
        ncols = len(header)

        # Determine the maximum width of the data rows
        max_cols = max((len(r) for r in data_rows), default=len(header))

        # If the data is wider than the header, pad the header list with dummy names
        # so Pandas doesn't throw a "Length mismatch" error
        # don't truncate the data, preserve all data even if messy.
        if max_cols > len(header):
            padded_header = header + [f"Extra_Col_{i}" for i in range(len(header), max_cols)]
        else:
            padded_header = header

        # ---- build DataFrame ----
        df = pd.DataFrame(data_rows, columns=padded_header)

        # Detect and log any duplicate column names BEFORE deduplicating, so we know
        # which files actually hit this and can go inspect their raw headers.
        col_counts = {}
        for c in df.columns:
            col_counts[c] = col_counts.get(c, 0) + 1
        duplicated = [c for c, n in col_counts.items() if n > 1]
        if duplicated:
            print(f"❌ DUPLICATE COLUMN NAMES in {csv_file.name}: {duplicated}")
            collected_duplicate_columns.append({
                "File": csv_file.name,
                "Duplicate Columns": ", ".join(duplicated),
                "Raw Header": header,
            })

        df.columns = deduplicate_headers(list(df.columns)) #safety: make sure columns dont share names from this point on


        # ---- delete "Remarks" column ----
        cols_to_drop = []
        for col in df.columns:
            col_clean = str(col).lower().strip()
            if "remarks" in col_clean:
                cols_to_drop.append(col)
            if cols_to_drop:
                df.drop(columns=cols_to_drop, inplace=True)
                print(f"Deleted remarks columns: {cols_to_drop}")
        
        # ---- spaced decimal fixes ----
        # eg '..316' becomes '.316' and '48. 5' becomes '48.5'
        df = fix_spaced_decimals(df, csv_file.name, collected_fixed_spaced_decimals)

        # ---- fix transposed n and x ----
        # eg '2n86' becomes 'n286'
        df = fix_transposed_nx(df, csv_file.name, collected_transposed_nx)
        
        # ---- replace instances of old font decimal place '·' with '.' ----
        df = df.replace("·", ".", regex=True)
            # can count this in apostrophe report if needed but it is a different type of error
        
        # ---- replace G3.1 mistranscriptions of . as ' with . and count ----
        df = replace_and_log_apostrophe_fixes(df, csv_file.name, "°.", ".", collected_symbol_i_fixes)
        df = replace_and_log_apostrophe_fixes(df, csv_file.name, ".°", ".", collected_symbol_i_fixes)
        df = replace_and_log_apostrophe_fixes(df, csv_file.name, "'.", ".", collected_symbol_i_fixes)
        df = replace_and_log_apostrophe_fixes(df, csv_file.name, ".'", ".", collected_symbol_i_fixes)
        df = replace_and_log_apostrophe_fixes(df, csv_file.name, "'", ".", collected_symbol_i_fixes)
        df = replace_and_log_apostrophe_fixes(df, csv_file.name, "°", ".", collected_symbol_i_fixes) 
        df = replace_and_log_apostrophe_fixes(df, csv_file.name, "..", ".", collected_symbol_i_fixes)

        # global I to 1 fix
        df = fix_global_ocr_I_to1(df, csv_file.name, collected_symbol_i_fixes)

        # asterisk fixes (special logic for wind dir and cloud)
        df = fix_general_asterisks(df, csv_file.name, collected_asterisk_fixes)

        # fix rain column
        df = fix_rain_column(df, csv_file.name, collected_decimal_added_fixes)

        # fix sunshine column
        df = fix_sunshine_column(df)

        # fix 10s mistakenly transcribed as 100 or 1000 in cloud cols
        df = fix_cloud_typos(df, csv_file.name, collected_cloud_10_fixes)

        # replace '-' and '-.' and 'NULL' and 'null' with 'NA' in all columns except rain
        non_rain_cols = [c for c in df.columns if "rain" not in str(c).lower()]
        for col in non_rain_cols:
            df[col] = df[col].replace(r"^(?:\s*[-—–_]+\.?\s*$|\s*(?i:null)\s*)$", "NA", regex=True)

        # ---- normalize NA (First Pass) ----
        df = df.replace(NA_VALUES, pd.NA)
        df = df.replace(r"^\s*$", pd.NA, regex=True)

        # ---- fix rogue leading dots ----
        # e.g. '.53.4' becomes '53.4' for any column
        df = fix_rogue_leading_dots(df, csv_file.name, collected_rogue_leading_decimals)

        # ---- split wind columns ----
        df = fix_calm_force_ocr(df, csv_file.name, collected_wind_tidy_fixes) # c -> 0 if near calm but in a force col
        df = fix_force_column_ocr_junk(df, csv_file.name, collected_wind_tidy_fixes)
        df = split_wind_columns(df, csv_year, csv_file.name, collected_wind_tidy_fixes)

        # ---- tidy wind columns characters ----
        df = tidy_wind_direction(df, csv_file.name, collected_wind_tidy_fixes)

        # ---- rename column headers for consistency ----
        if len(df.columns) == len(target_headers):
            df.columns = target_headers
        else:
            print(f"Warning: Column count mismatch. Expected {len(target_headers)}, got {len(df.columns)}. Skipping column rename.")
        
        # For vapour pressure, barometer inHg and temperature kelvin shorthands:
        # Try to convert year to an integer. If it fails, default to 1890 so it processes.
        try:
            current_year = int(csv_year)
        except (ValueError, TypeError):
            current_year = 1890 

        # fix vapour tension decimal places, different logic for pre and post 1912 due to unit change
        df = fix_vapour_tension(df, csv_file.name, current_year, collected_decimal_added_fixes, collected_implausible_vapour, collected_asterisk_fixes)

        # fix wetbulb depression decimal places
        df = fix_wetbulb_depression(df, csv_file.name, collected_decimal_added_fixes, collected_implausible_wetbulb_depression, collected_asterisk_fixes)

        # fix wind hyphens
        df = fix_wind_force_hyphens(df, csv_file.name, collected_wind_hyphen_decimal_fixes)

        # ---- Final NA fill ----
        df = df.fillna("NA")

        # --- Fix barometer columns shorthand for pre-1912 ---
        baro_cols = [c for c in df.columns if "barometer" in c.lower()]
        
        if current_year < 1912:
            for col in baro_cols:
                df[col] = fix_pressure(df[col], csv_file.name, col, 
                                    collected_asterisk_fixes, collected_decimal_added_fixes)
                
        
        # --- Fix temperature kelvin columns shorthand for 1912 and post ---
        if current_year >= 1912:
            temp_cols = [c for c in df.columns if "temp" in str(c).lower()]
            for col in temp_cols:
                df[col] = fix_kelvin_temperature(df[col], csv_file.name, col)

        # convert df to string to ensure pandas doesn't write <NA>
        df = df.astype(str)

        # replace <NA> and 'nan' with 'NA'
        df = df.replace(["<NA>", "nan", "NaN", "None", ""], "NA")

        # ---- write output ----
        # utf-8-sig ensure excel reads special characters correctly
        with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerows(meta_rows)           
            writer.writerow(df.columns.tolist()) 
            writer.writerows(df.values)

        print(f"Written {out_file}")
        print(f"--- FINISHED FILE {idx_file + 1}/{len(files)}: {csv_file.name} ---")


# export reports
reports = [
    {
        "data": collected_unicode_fixes,
        "path": unicode_report_path,
        "label": "Unicode fixes",
        "empty": "No Unicode replacements required",
    },
    {
        "data": collected_notes,
        "path": notes_report_path,
        "label": "Notes",
        "empty": "No metadata notes found",
    },
    {
        "data": collected_decimal_added_fixes,
        "path": decimal_added_report_path,
        "label": "Decimal fixes",
        "empty": "No decimal place fixes required",
    },
    {
        "data": collected_implausible_vapour,
        "path": implausible_vapour_report_path,
        "label": "Implausible vapour values",
        "empty": "No implausible vapour values found",
    },
    {
        "data": collected_implausible_wetbulb_depression,
        "path": implausible_wetbulb_depression_report_path,
        "label": "Implausible wetbulb depression values",
        "empty": "No implausible wetbulb depression values found",
    },
    {
        "data": collected_wind_hyphen_decimal_fixes,
        "path": wind_force_hyphen_to_decimal_report_path,
        "label": "Wind force hyphen to decimal",
        "empty": "No wind force ranges found",
    },
    {
        "data": collected_wind_tidy_fixes,
        "path": wind_tidy_report_path,
        "label": "Wind direction corrections",
        "empty": "No wind direction corrections required",
    },
    {
        "data": collected_asterisk_fixes,
        "path": asterisk_report_path,
        "label": "Asterisk fixes",
        "empty": "No asterisks found",
    },
    {
        "data": collected_symbol_i_fixes,
        "path": ocr_symbol_to_decimal_i_to_1_report,
        "label": "Character replacements",
        "empty": "No character replacements required",
    },
    {
        "data": collected_merged_cells,
        "path": merged_cell_report_path,
        "label": "Merged cell fixes",
        "empty": "No merged cell fixes required"
    },
    {
        "data": collected_fixed_spaced_decimals,
        "path": fix_spaced_decimals_report_path,
        "label": "OCR typo fixes",
        "empty": "No OCR typo fixes required"
    },
    {
        "data": collected_cloud_10_fixes,
        "path": cloud_report_path,
        "label": "Cloud 10s and/or 0s fixes",
        "empty": "No cloud 10s and/or 0s fixes required"
    },
    {
        "data": collected_year_rescued_from_sourcefilename,
        "path": year_rescued_from_sourcefilename_path,
        "label": "Year rescued from source filename",
        "empty": "No years rescued from source filename"
    },
    {
        "data": collected_duplicate_files,
        "path": duplicate_files_path,
        "label": "Duplicate files",
        "empty": "No duplicate files"
    },
    {
        "data": collected_gravity_correction_fixes,
        "path": gravity_correction_path,
        "label": "Gravity correction fixes",
        "empty": "No gravity correction fixes required"
    },
    {
        "data": collected_duplicate_columns,
        "path": duplicate_columns_path,
        "label": "Duplicate column names",
        "empty": "No duplicate column names found"
    },
    {
        "data": collected_transposed_nx,
        "path": transposed_nx_report_path,
        "label": "Transposed n/x fixes",
        "empty": "No transposed n/x typos found"
    },
    {
        "data": collected_rogue_leading_decimals,
        "path": rogue_leading_decimals_path,
        "label": "Rogue leading decimals fixes",
        "empty": "No rogue leading decimals fixes required"
    },
]

for report in reports:
    export_report(
        data = report["data"],
        path = report["path"],
        label=report["label"],
        empty_message=report["empty"],
        use_csv=True,
    )
