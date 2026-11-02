import pandas as pd
import os
import datetime
import codecs
import copy
import sys
import csv
import re
import configparser
import math
import yaml
import shutil
from datetime import datetime, time, timedelta, date
from pathlib import Path

# ==========================================
# 1. CONFIGURATION 
# ==========================================
THIS_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = THIS_DIR / 'SSO_metadata.yaml'

# --- Define Input and Output Paths Here ---
INPUT_ROOT = Path("")
OUTPUT_ROOT = Path("")
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
# Temporary directory for Disk-Backed processing (Prevents OOM crashes)
TEMP_DIR = OUTPUT_ROOT / "_temp_sef_data"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
BATCH_LIST_PATH = None # Replace with Path("...") if using a batch list, or leave as None

# QC Setup: Column math ---
QC_CSV_PATH = Path("/columns_qc_pass.csv")

# Memory for negative Barometer Heights found during pre-scan
STATION_NEGATIVE_HOBS = {}

def load_qc_colmath():
    """Loads pass/fail/unverified status into a lookup dict keyed by (filename, column_name)."""
    status_map = {}
    if QC_CSV_PATH and QC_CSV_PATH.exists():
        try:
            df_qc = pd.read_csv(QC_CSV_PATH)
            if 'File' in df_qc.columns and 'Column' in df_qc.columns:
                for _, row in df_qc.iterrows():
                    f_name = str(row['File']).strip().lower()
                    c_name = str(row['Column']).strip().lower()
                    status_map[(f_name, c_name)] = 'pass'
        except Exception as e:
            print(f"Warning: Failed to load QC file: {e}")

    # Load unverified sets and mark them distinctly, without overwriting a 'pass'
    for path, reason in [(QC_CSV_PATH.parent / "columns_skipped_no_mean.csv", 'unverified_no_mean'),
                          (QC_CSV_PATH.parent / "columns_skipped_no_data.csv", 'unverified_no_data'),
                          (QC_CSV_PATH.parent / "columns_skipped_no_mean_no_data.csv", 'unverified_no_mean_no_data')]:
        if path.exists():
            try:
                df_skip = pd.read_csv(path)
                for _, row in df_skip.iterrows():
                    key = (str(row['File']).strip().lower(), str(row['Column']).strip().lower())
                    status_map.setdefault(key, reason)
            except Exception as e:
                print(f"Warning: Failed to load {path.name}: {e}")

    return status_map

QC_COLMATH_SET = load_qc_colmath()

def clean_column_name(col):
    """Must exactly match column_math_validation.py's clean_column_name for QC key matching to work."""
    c = str(col)
    c = re.sub(r'[^\x20-\x7E]', '', c)
    c = re.sub(r'\s+', ' ', c)
    return c.strip()

# --- Maps SEF variables to YAML metadata blocks ---
YAML_VBL_MAP = {
    'p': ['barometer', 'barometer_height'],
    'Ta': ['temperature', 'thermometer_height'],
    'Tn': ['temperature', 'thermometer_height'],
    'Tx': ['temperature', 'thermometer_height'],
    'e': ['hygrometry', 'temperature', 'thermometer_height'],
    'rh': ['hygrometry', 'temperature', 'thermometer_height'],
    'rr': ['rain', 'rain_gauge_height', 'station_height'],
    'w': ['wind_force'],
    'dd': ['wind_direction', 'wind_force'],
    'n': ['cloud'],
    'ss': ['sunshine']
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"CRITICAL ERROR: Config file not found at expected path:\n  {CONFIG_FILE}")
        sys.exit(1)
    try:
        # Load entirely as YAML since the file contains YAML metadata rules
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading config file: {e}")
        sys.exit(1)

    return config

CONFIG = load_config()

# ––––––––––––––––––––––––––––––
# wind direction conversion
# -------------------------------

def convert_wind_direction(raw_val, year):
    """Converts wind direction based on the specific year rules."""
    year = int(year)

    val_str = str(raw_val).strip().upper()
    
    # If observer was unsure (indicated by a ?), discard value
    if '?' in val_str:
        return "NA"
        
    # Clean up punctuation: remove spaces, dots, and brackets
    val_str = val_str.replace('.', '').replace(' ', '').replace('(', '').replace(')', '')

    # Universal catch for CALM across all eras
    if val_str == 'CALM':
        return 0.0
    
    # Before 1912 -> Letters to Degrees
    if year < 1912:
        direction_conversion = {
            'N': 360, 'NORTH': 360, 'NBYE': 11.25,'NNE': 22.5,'NEBYN': 33.75,'NE': 45,'NEBYE': 56.25,
            'ENE': 67.5,'EBYN': 78.75,'E': 90, 'EAST': 90,'EBYS': 101.25,'ESE': 112.5,'SEBYE': 123.75,
            'SE': 135,'SEBYS': 146.25,'SSE': 157.5,'SBYE': 168.75,
            'S': 180, 'SOUTH': 180, 'SBYW': 191.25,'SSW': 202.5,'SWBYS': 213.75,
            'SW': 225,'SWBYW': 236.25,'WSW': 247.5,'WBYS': 258.75,
            'W': 270, 'WEST': 270, 'WBYN': 281.25,'WNW': 292.5,'NWBYW': 303.75,
            'NW': 315,'NWBYN': 326.25,'NNW': 337.5,'NBYW': 348.75
        }
        
        # 1. Direct Match
        if val_str in direction_conversion: 
            return direction_conversion[val_str]
            
        # 2. Dynamic Midpoint Calculation for Ranges (e.g., NNE-NE)
        if '-' in val_str:
            parts = val_str.split('-')
            if len(parts) == 2:
                p1, p2 = parts[0], parts[1]
                if p1 in direction_conversion and p2 in direction_conversion:
                    deg1 = direction_conversion[p1]
                    deg2 = direction_conversion[p2]
                    
                    # Calculate the clockwise distance between the two points
                    cw_dist = (deg2 - deg1) % 360
                    
                    # Only convert if the clockwise shift is a quarter compass (90°) or less.
                    # This safely rejects >90° shifts and backwards transcriptions (like ENE-NE or E-N)
                    if cw_dist <= 90:
                        midpoint = (deg1 + (cw_dist / 2.0)) % 360
                        
                        # In SEF, 0 is calm. True North is always 360.
                        return 360.0 if midpoint == 0 else midpoint
                    else:
                        # Return NA for invalid/massive ranges so it prints nicely in the .tsv
                        return "NA"
                        
        return float(raw_val) # Fallback if already numeric
        
    # 1912 to 1917 inclusive -> 32-point compass to Degrees
    elif 1912 <= year <= 1917:
        val_float = float(raw_val)
        if 0 < val_float <= 32:
            return val_float * 11.25
        return val_float # Fallback if > 32 (already degrees)
        
    # 1918 onwards -> Already in Degrees
    else:
        return float(raw_val)

# units
    # whole record
        # humidity: %
        # cloud amount: 1-10
        # sunshine: hours
    # year < 1912
        # pressure (air and vapour): inHg
        # temperature, depression of wetbulb temp, min temp on grass: farenheit
        # wind direction: letters
        # wind force: beaufort scale or miles per hour if from anemometer stations
        # rain: inches
    # year >= 1912
        # pressure (air and vapour): mb
        # temperature, depression of wetbulb temp, min temp on grass: kelvin
        # wind direction: points or degrees
        # wind force: beaufort scale or m/s
        # rain: mm
    
def get_era_logic(qty_type, year):
    """
    Returns (conversion_function, original_unit_string) based on the quantity type and year.
    All outputs are formatted for SEF standard (C, hPa, mm, m/s).
    """
    year = int(year)
    
    if qty_type == 'temperature':
        if year < 1912:
            return lambda x: (float(x) - 32) * 5/9, 'F'
        else:
            return lambda x: float(x) - 273, 'K'  # K to C, assuming that the thermometers were for these years read in F and converted to K using +273.0 as the .15 was only determined in the 1950s.
                                                # we assume the thermometer reading F is correct and the error is introduced in the conversion to K
                                                # to reverse the error, we subtract 273.0 to get back to the original thermometer reading
                                                # 273.0 conversion is detailed here, p.7 https://digital.nmla.metoffice.gov.uk/IO_69c4ee61-f9df-47e0-b37f-71a1a2d43a1a/ 
            
    elif qty_type == 'temp_diff': # Specifically for depression of wetbulb
        if year < 1912:
            return lambda x: float(x) * 5/9, 'F' # A difference of 1F = 5/9C
        else:
            return lambda x: float(x), 'K'       # A difference of 1K = 1C
            
    elif qty_type == 'pressure':
        if year < 1912:
            return lambda x: float(x) * 33.8639, 'inHg' # Source: WMO Guide to instruments and methods 2024 edition https://library.wmo.int/viewer/68695/download?file=WMO-8-vI-2024_en.pdf&type=pdf&navigator=1
        else:
            return lambda x: float(x), 'mb'
            
    elif qty_type == 'rain':
        if year < 1912:
            return lambda x: float(x) * 25.4, 'in'
        else:
            return lambda x: float(x), 'mm'
            
    elif qty_type == 'wind_dir':
        # Pass year into the conversion function
        return lambda x: convert_wind_direction(x, year), ''
        
    elif qty_type == 'wind_force':
        # Defer conversion to apply_active_corrections which reads the YAML
        def safe_wind(x):
            x_str = str(x).upper().strip()
            if x_str == 'CALM': 
                return 0.0
                
            # Handle ranges like '2-3' or '2 - 5'
            if '-' in x_str:
                parts = x_str.split('-')
                if len(parts) == 2:
                    try:
                        val1 = float(parts[0].strip())
                        val2 = float(parts[1].strip())
                        return (val1 + val2) / 2.0
                    except ValueError:
                        pass # Fall through to the standard float conversion to trigger a normal error
                        
            return float(x_str)
            
        return safe_wind, ''
            
    elif qty_type == 'relative_humidity':
        return lambda x: float(x), '%'
    
    elif qty_type == 'vapour_pressure':
        if year < 1912:
            return lambda x: float(x) * 33.8639, 'inHg'
        else:
            return lambda x: float(x), 'mb'
    
    # converts from SSO method of 1-10 (0: clear sky. 10: completely overcast) to SEF %
    # if '?' in value, then replace with NA
    elif qty_type == 'cloud':
        def safe_cloud(x):
            if '?' in str(x):
                return 'NA'
            return float(x) * 10
        return safe_cloud, '' 
    
    elif qty_type == 'sunshine_duration':
        return lambda x: float(x), 'hrs'

    return lambda x: float(x), ''

def get_precision(vbl_code, year):
    """
    Returns number of decimal places for a variable based on the era
    """
    year = int(year)
    
    if vbl_code in ['p', 'mslp']:
        # inHg converted to hPa: 3 decimal places for 1873-1882, 2 for 1883-1911
        # mb: 1 decimal place
        if year < 1883:
            return 3
        elif 1882 < year < 1912:
            return 2
        elif year > 1911:
            return 1

    elif vbl_code in ['Ta', 'Tn', 'Tx', 'TGn']:
        # Temperatures given to 1 decimal place for both F and K
        # K to C conversion: 1 decimal place because 273.0 was used during the era of original observations
        return 1
    
    elif vbl_code == 'e':
        # inHg converted to hPa: 3 decimal places for 1873-1911
        # mb: 1 decimal place
        if year < 1912:
            return 3
        elif year > 1911:
            return 1
        
    elif vbl_code == 'rr':
        # Inches to mm: 3 decimal places
        # mm: 1 decimal place
        return 3 if year < 1912 else 1
        
    elif vbl_code == 'dd':
        # Wind direction: whole degrees
        return 0
        
    elif vbl_code == 'n':
        # Cloud cover: whole numbers
        return 0
        
    # Default for wind force (m/s), sunshine (hours), etc.
    return 1

VARIABLE_RULES = {
    # --- SIMPLE VARIABLES ---
    'p': {
        'mode': 'simple',
        'qty_type': 'pressure',
        'keywords': ['barometer', 'air pressure'],
        'units': 'hPa',
        'period': 0,
        'stat': 'point'
    },
    'Ta': {
        'mode': 'simple',
        'qty_type': 'temperature',
        'keywords': ['temperature', 'temp'],
        'exclude': ['grass', 'max', 'min', 'dep', 'wet'],
        'units': 'C',
        'period': 0,
        'stat': 'point',
    },
    'Tx': {
        'mode': 'simple',
        'qty_type': 'temperature',
        'keywords': ['max'],
        'exclude': ['grass'],
        'units': 'C',
        'period': 'p24hour', # p = since previous observation presuming previous observation was within 1 day see: https://github.com/C3S-Data-Rescue-Lot1-WP3/SEF/wiki/time_period_codes
        'stat': 'maximum',
        'structure': 'daily'
    },
    'Tn': {
        'mode': 'simple',
        'qty_type': 'temperature',
        'keywords': ['min'],
        'exclude': ['grass'],
        'units': 'C',
        'period': 'p24hour',
        'stat': 'minimum',
        'structure': 'daily'
    },
    'dep_wet': {
        'mode': 'simple',
        'qty_type': 'temp_diff',
        'keywords': ['dep', 'wet'],
        'exclude': ['relative', 'percent', 'vapour', 'tension', 'per-cent'],
        'units': 'C',
        'period': 0,
        'stat': 'point'
    },
    'e': {
        'mode': 'simple',
        'qty_type': 'vapour_pressure',
        'keywords': ['tension', 'vapour'],
        'exclude': ['relative', 'percent', 'dep', 'wet', 'per-cent'],
        'units': 'hPa',
        'period': 0,
        'stat': 'point'
    },
    'rh': {
        'mode': 'simple',
        'qty_type': 'relative_humidity',
        'keywords': ['humidity', 'relative', 'percent', 'per-cent'],
        'exclude': ['tension', 'vapour', 'dep', 'wet'],
        'units': '%',
        'period': 0,
        'stat': 'point'
    },
    'dd': {
        'mode': 'simple',
        'qty_type': 'wind_dir',
        'keywords': ['direction', 'dir', 'veer', 'north'],
        'units': 'degree',
        'period': 'NA',
        'stat': 'point' # needed to have a stat to allow for dataresqc R package flags to be implemented. put as point as true stat and period are unknown.
    },
    'w': {
        'mode': 'simple',
        'qty_type': 'wind_force',
        'keywords': ['frc','force', 'speed', 'velocity'],
        'units': 'm/s',
        'period': 'NA',
        'stat': 'point' # needed to have a stat to allow for dataresqc R package flags to be implemented. put as point as true stat and period are unknown.
    },
    'n': {
        'mode': 'simple',
        'qty_type': 'cloud',
        'keywords': ['cloud', 'amount'],
        'units': '%',
        'period': 0,
        'stat': 'point'
    },
    'rr': {
        'mode': 'simple',
        'qty_type': 'rain',
        'keywords': ['rain'],
        'units': 'mm',
        'period': 'p24hour',
        'stat': 'sum',
        'structure': 'daily'
    },
    'ss': {
        'mode': 'simple',
        'qty_type': 'sunshine_duration',
        'keywords': ['sunshine'],
        'units': 'hrs',
        'period': 'p24hour',
        'stat': 'sum',
        'structure': 'daily'
    },
    'TGn': {
        'mode': 'simple',
        'qty_type': 'temperature',
        'keywords': ['grass'],
        'units': 'C',
        'period': 'p24hour',
        'stat': 'minimum',
        'structure': 'daily'
    },
 
}


# ==========================================
# 3. METADATA & PARSING
# ==========================================

def parse_year_range(year_data):
    """
    Converts YAML metadata year inputs into a flat list of ints.
    Handles single ints, lists, string ranges ('1887-1896'), and dicts ({start: 1877, end: 1880}).
    """
    if isinstance(year_data, int): return [year_data]
    elif isinstance(year_data, list): return [int(y) for y in year_data]
    elif isinstance(year_data, str):
        if '-' in year_data:
            start, end = year_data.split('-')
            return list(range(int(start), int(end) + 1))
        return [int(year_data)]
    elif isinstance(year_data, dict):
        start = year_data.get('start', 1800)
        end = year_data.get('end', 2099)
        
        if isinstance(start, (datetime, date)): start = start.year
        elif isinstance(start, str) and '-' in start: start = int(start.split('-')[0])
        
        if isinstance(end, (datetime, date)): end = end.year
        elif isinstance(end, str):
            if end == '?': end = 2099
            elif '-' in end: end = int(end.split('-')[0])
            
        return list(range(int(start), int(end) + 1))
    return []

def parse_date(date_data, default):
    """Parses date dicts/strings into date objects for exact bounding."""
    if not date_data or date_data == '?': return default
    if isinstance(date_data, date): return date_data
    if isinstance(date_data, datetime): return date_data.date()
    try:
        date_str = str(date_data).strip()
        if len(date_str) == 4: return date(int(date_str), 1, 1)
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return default

class MetadataRules:
    def __init__(self, config_dict):
        self.config = config_dict
        self.rules = self.config.get('hours_of_observation', {})
        self.exceptions = self.rules.get('exceptions', [])
        self.defaults = self.rules.get('defaults', [])
        
    def get_expected_times(self, station_name, observation_date, vbl_code):
        """
        Returns a list of expected time strings (e.g., ['09:00', '21:00']) 
        for a specific station, date, and variable using parsed YAML rules.
        """
        station_name = station_name.lower().strip()
        obs_year = observation_date.year
        
        # Safely handle both datetime and date objects
        if isinstance(observation_date, datetime):
            obs_date = observation_date.date()
        else:
            obs_date = observation_date
            
        # 1. Check exceptions first
        for exc in self.exceptions:
            st_data = exc.get('station', [])
            if isinstance(st_data, str): st_data = [st_data]
            stations = [s.lower().strip() for s in st_data]
            
            if station_name not in stations: continue
            
            # Check year/date boundaries
            match = False
            if 'year_range' in exc:
                if obs_year in parse_year_range(exc['year_range']): match = True
            if 'date_range' in exc:
                # FIXED: Removed 'datetime.' prefix
                start = parse_date(exc['date_range'].get('start'), date(1800, 1, 1))
                end = parse_date(exc['date_range'].get('end'), date(2099, 12, 31))
                if start <= obs_date <= end: match = True
                
            if match:
                # Build normalized vars dict to split keys like "Tn, Tx"
                vars_dict = {}
                for k, v in exc.items():
                    if k not in ['station', 'year_range', 'date_range']:
                        for sub_k in k.split(','): vars_dict[sub_k.strip()] = v
                
                if vbl_code in vars_dict: return vars_dict[vbl_code]
                if 'general' in vars_dict: return vars_dict['general']

        # 2. Check defaults
        for default in self.defaults:
            if 'date_range' in default:
                # FIXED: Removed 'datetime.' prefix
                start = parse_date(default['date_range'].get('start'), date(1800, 1, 1))
                end = parse_date(default['date_range'].get('end'), date(2099, 12, 31))
                if start <= obs_date <= end:
                    vars_dict = {}
                    for k, v in default.items():
                        if k not in ['date_range', 'time_zone']:
                            for sub_k in k.split(','): vars_dict[sub_k.strip()] = v
                            
                    if vbl_code in vars_dict: return vars_dict[vbl_code]
                    if 'general' in vars_dict: return vars_dict['general']
                    
        return ["09:00"]

# Instantiate Metadata Rules globally using the YAML config file
META_RULES_ENGINE = MetadataRules(CONFIG)

def parse_dms(dms_str):
    if not dms_str: return None
    match = re.search(r'(\d+)[\D]+(\d+)[\D]+([NSEW])', dms_str.upper())
    if match:
        deg, mn, direction = float(match.group(1)), float(match.group(2)), match.group(3)
        decimal = deg + (mn / 60.0)
        return round(-decimal if direction in ['S', 'W'] else decimal, 4)
    return None

def parse_time_from_colname(colname):
    c_low = str(colname).lower().replace(' ', '').replace('_', '')

    if 'midt' in c_low or 'midnight' in c_low: return '00:00', time(0, 0)
    if 'noon' in c_low: return '12:00', time(12, 0)

    pattern = re.compile(r'(?<!\d)(\d{1,2})(?:[:\.](\d{2}))?(a\.?m\.?|p\.?m\.?|a\.|p\.|h)')

    for match in pattern.finditer(c_low):
        token = match.group(3)
        end_pos = match.end()
        next_char = c_low[end_pos] if end_pos < len(c_low) else ''

        # If the token doesn't end in a period, it needs a non-letter boundary after it —
        # otherwise it may just be the start of a longer, unrelated word (e.g. "a.mean").
        # If it ends in a period, the period itself is a clear enough boundary,
        # regardless of what text follows (e.g. "9 a.m. reading" is genuine).
        if not token.endswith('.') and next_char.isalpha():
            continue  # reject this candidate, keep scanning for a later valid match

        h = int(match.group(1))
        m = int(match.group(2)) if match.group(2) else 0

        if token.startswith('a'):
            h = 0 if h == 12 else h
        elif token.startswith('p'):
            h = h + 12 if h < 12 else h
        elif token == 'h' and h == 24:
            h = 0

        h, m = h % 24, m % 60
        return f"{h:02d}:{m:02d}", time(h, m)

    # fallback: bare 9 / 21 with digit boundaries only (no letter/digit adjacency)
    if re.search(r'(?<!\d)9(?!\d)', c_low): return '09:00', time(9, 0)
    if re.search(r'(?<!\d)21(?!\d)', c_low): return '21:00', time(21, 0)

    return None, None

def match_yaml_rule(rule, station, year, month=1, lat=None, lon=None):
    """Checks if a specific YAML rule applies to the given station, year, and month."""
    if not isinstance(rule, dict): return False
    
    y, m = int(year), int(month)
    
    # Check year matching
    if 'year_range' in rule:
        if y not in parse_year_range(rule['year_range']): return False
        
    # Check exact date/month matching
    if 'date_range' in rule:
        start = parse_date(rule['date_range'].get('start'), date(1800,1,1))
        end = parse_date(rule['date_range'].get('end'), date(2099,12,31))
        
        file_ym = y * 100 + m
        start_ym = start.year * 100 + start.month
        end_ym = end.year * 100 + end.month
        
        if not (start_ym <= file_ym <= end_ym): return False
        
    # Check station inclusion
    if 'station' in rule:
        st_list = [s.lower().strip() for s in rule['station']] if isinstance(rule['station'], list) else [rule['station'].lower().strip()]
        if station.lower() not in st_list: return False
            
    # Check station exclusion
    if 'exceptions' in rule:
        exc_data = rule['exceptions']
        if isinstance(exc_data, list) and len(exc_data) > 0 and isinstance(exc_data[0], str):
            ex_list = [s.lower().strip() for s in exc_data]
            if station.lower() in ex_list: return False
        elif isinstance(exc_data, str):
            if station.lower() == exc_data.lower().strip(): return False
            
    return True

def get_rule_year_suffix(rule):
    """Creates a string like '_1897_1905' or '_1877' after 'written_in_book' from the rule's date/year range."""
    yr = rule.get('year_range') or rule.get('date_range')
    if not yr: 
        return ""
        
    if isinstance(yr, (int, str)):
        return f"_{str(yr).replace('-', '_').strip()}"
        
    if isinstance(yr, dict):
        s = str(yr.get('start', '')).split('-')[0]
        e = str(yr.get('end', '')).split('-')[0]
        
        # Clean up open-ended dates so they don't print "2099"
        if e == '2099' or e == '?': 
            e = ''
        
        if s and e: return f"_{s}_{e}"
        if s: return f"_{s}"
        if e: return f"_{e}"
        
    return ""

def get_rule_meta(rule):
    """Extracts valid metadata key-value pairs from a matched rule and appends the year suffix."""
    ignore_keys = {'year_range', 'date_range', 'station', 'exceptions', 'locations', 
                   'exception_info', 'value', 'unit'}
    
    # Get the dynamic year suffix (e.g., '_1897_1905')
    yr_suffix = get_rule_year_suffix(rule)
    
    parts = []
    for k, v in rule.items():
        if k not in ignore_keys:
            # Clean pipes and newlines so it doesn't break SEF TSV formatting
            clean_v = str(v).replace('|', ';').replace('\n', ' ').strip()
            
            # Format SEF Standard Keys (e.g., Instrument_1916=...)
            if k.lower() == 'instrument':
                parts.append(f"Instrument{yr_suffix}={clean_v}")
            # Format all custom descriptive keys (e.g., written_in_book_1897_1905:...)
            else:
                parts.append(f"{k}{yr_suffix}:{clean_v}")
                
    return parts

def get_yaml_meta_for_variable(station_name, year, vbl_code, month=1, lat=None, lon=None):
    """Finds all applicable YAML metadata for a specific station, year, and variable."""
    year = int(year)
    yaml_categories = YAML_VBL_MAP.get(vbl_code, [])
    meta_parts = []
    
    for category in yaml_categories:
        category_data = CONFIG.get(category)
        if not category_data: continue
            
        if isinstance(category_data, list):
            for rule in category_data:
                if match_yaml_rule(rule, station_name, year, month, lat, lon):
                    meta_parts.extend(get_rule_meta(rule))
                    
        elif isinstance(category_data, dict):
            exceptions_list = category_data.get('exceptions', [])
            if not exceptions_list and 'default' in category_data and isinstance(category_data['default'], dict):
                exceptions_list = category_data['default'].get('exceptions', [])
                
            matched_exception = False
            for rule in exceptions_list:
                if match_yaml_rule(rule, station_name, year, month, lat, lon):
                    meta_parts.extend(get_rule_meta(rule))
                    matched_exception = True
            
            if not matched_exception and 'default' in category_data:
                rule = category_data['default']
                if match_yaml_rule(rule, station_name, year, month, lat, lon):
                    meta_parts.extend(get_rule_meta(rule))
                    
    return meta_parts

def get_final_sensor_alt(meta_info, real_vbl_code, year, month):
    c_year, c_month = int(year), int(month)
    st_clean = meta_info['name'].lower().strip()
    try: st_alt = float(meta_info.get('alt', 0.0))
    except (ValueError, TypeError): st_alt = 0.0
    final_alt_val = st_alt
    
    if real_vbl_code in ['p', 'mslp']:
        hob_str = meta_info.get('height_of_barometer', '')
        if hob_str:
            m = re.search(r'(-?\d+(\.\d+)?)', str(hob_str))
            if m: 
                hob_val = float(m.group(1))
                # Before April 1911: Alt = Station MSL + HoB
                if c_year < 1911 or (c_year == 1911 and c_month < 4): 
                    final_alt_val = st_alt + hob_val
                # April 1911 onwards: Alt = exactly the HoB 
                else: 
                    final_alt_val = hob_val
                        
    # 2. Air thermometers (Station MSL + height of instrument above ground)
    elif real_vbl_code in ['Ta', 'Tn', 'Tx', 'dep_wet']:
        th_str = meta_info.get('height_of_thermometer', '')
        if th_str:
            m = re.search(r'(-?\d+(\.\d+)?)', str(th_str))
            if m: final_alt_val = st_alt + float(m.group(1))
            
    # 3. Rain Gauge (Station MSL + height of gauge above ground)
    elif real_vbl_code == 'rr':
        rg_str = meta_info.get('height_of_rain_gauge', '')
        if rg_str:
            m = re.search(r'(-?\d+(\.\d+)?)', str(rg_str))
            if m: final_alt_val = st_alt + float(m.group(1))
            
    # 4. Anemometer (Extracted directly from YAML MSL keys)
    elif real_vbl_code in ['w', 'dd']:
        y_rules = get_applicable_yaml_rules(st_clean, c_year, real_vbl_code)
        ane_alt = None
        for r in y_rules:
            if 'anemometer_height_above_msl_m' in r:
                ane_alt = float(r['anemometer_height_above_msl_m'])
            elif 'anemometer_height_above_msl_ft' in r:
                ane_alt = float(r['anemometer_height_above_msl_ft']) * 0.3048
        if ane_alt is not None:
            final_alt_val = ane_alt
            
    return final_alt_val

def get_time_zone_abbr(station_name, year):
    """
    Determines the correct time zone from the YAML and returns an abbreviation.
    Defaults to Local mean time if no specific rule matches.
    """
    station_clean = station_name.lower().strip()
    year = int(year)
    
    # Default fallback
    tz_raw = "Local mean time"
    
    for rule in CONFIG.get('time_zones', []):
        # Check year bounds if present
        if 'year_range' in rule:
            if year not in parse_year_range(rule['year_range']):
                continue
        
        # Check station match
        st_list = rule.get('stations', [])
        if isinstance(st_list, str):
            if st_list.lower() == 'all':
                # Check exceptions first
                ex_list = [s.lower().strip() for s in rule.get('exceptions', [])]
                if station_clean in ex_list:
                    tz_raw = rule.get('exception_time_zone', tz_raw)
                    break # Specific exception found, stop looking
                else:
                    tz_raw = rule.get('time_zone', tz_raw)
                    # DO NOT BREAK HERE! Allow specific rules further down to override this.
            else:
                if station_clean == st_list.lower().strip():
                    tz_raw = rule.get('time_zone', tz_raw)
                    break
        else:
            st_list = [s.lower().strip() for s in st_list]
            if station_clean in st_list:
                tz_raw = rule.get('time_zone', tz_raw)
                break
            
    # Convert raw YAML timezone string to abbreviation
    tz_raw_low = tz_raw.lower()
    if 'dublin' in tz_raw_low: return ' Dublin Mean Time'
    if 'gmt' in tz_raw_low or 'greenwich' in tz_raw_low: return ' Greenwich Mean Time'
    if 'local' in tz_raw_low: return ' Local Mean Time'
    
    return tz_raw.upper().replace(' ', '')

def get_applicable_yaml_rules(station_name, year, vbl_code, month=1, lat=None, lon=None):
    """Returns the actual YAML dictionaries that apply to this station/year."""
    year = int(year)
    yaml_categories = YAML_VBL_MAP.get(vbl_code, [])
    applicable_rules = []
    
    for category in yaml_categories:
        category_data = CONFIG.get(category)
        if not category_data: continue
            
        if isinstance(category_data, list):
            for rule in category_data:
                # ADD LAT/LON HERE
                if match_yaml_rule(rule, station_name, year, month, lat, lon):
                    applicable_rules.append(rule)
                    
        elif isinstance(category_data, dict):
            exceptions_list = category_data.get('exceptions', [])
            if not exceptions_list and 'default' in category_data and isinstance(category_data['default'], dict):
                exceptions_list = category_data['default'].get('exceptions', [])
            
            matched_exception = False
            for rule in exceptions_list:
                # ADD LAT/LON HERE
                if match_yaml_rule(rule, station_name, year, month, lat, lon):
                    applicable_rules.append(rule)
                    matched_exception = True
            
            if not matched_exception and 'default' in category_data:
                rule = category_data['default']
                # ADD LAT/LON HERE
                if match_yaml_rule(rule, station_name, year, month, lat, lon):
                    applicable_rules.append(rule)
                    
    return applicable_rules

def get_wind_unit(station_name, year):
    """Looks up the specific wind unit for a station/year from the YAML."""
    rules = get_applicable_yaml_rules(station_name, year, 'w')
    for rule in rules:
        if 'unit' in rule:
            return str(rule['unit']).lower().strip()
    return 'beaufort'

def get_pressure_sef_code(station_name, year):
    """Determines if pressure for this year/station is 'p' (station level) or 'mslp' (Mean Sea Level)."""
    year = int(year)
    rules = get_applicable_yaml_rules(station_name, year, 'p')
    
    # Check specific YAML notes for 'station level'
    for rule in rules:
        info = str(rule.get('written_in_book', '')).lower()
        if 'without that reduction' in info or 'station level' in info:
            return 'p'
            
    # Default historical bounds based on logbook history
    if 1886 <= year <= 1911:
        return 'p'
        
    return 'mslp'

def apply_active_corrections(val, vbl_code, station_name, year, meta):
    """
    Actively modifies the value (in standard SEF units like hPa or C) 
    based on historical rules defined in the YAML.
    """
    station_clean = station_name.lower().strip()
    year = int(year)
    rules = get_applicable_yaml_rules(station_clean, year, vbl_code, 1, float(meta.get('lat', 0)), float(meta.get('lon', 0)))
    
    # In the original logbooks:
        # 1873-1885, 1912-1921: pressure values are reduced to 32˚F and to MSL, 
            # corrected for instrument error and for the variation of gravity with latitude  
        # 1886-1911: pressure values are NOT reduced to MSL, but are reduced to 32˚F,
            # corrected for instrument error and for the variation of gravity with latitude 

    # 1. Barometer correction (Dartmoor)
    if vbl_code in ['p', 'mslp']:
        for rule in rules: 
            # Check for Dartmoor Exception (1873-1877): subtract 0.060 inHg (2.0318 hPa)
            if station_clean == 'dartmoor' and 'exception_info' in rule:
                if '0.060' in str(rule['exception_info']):
                    if year < 1878:
                        val -= 2.0318

    # Wind conversions (beautfort or mph to m/s, based on YAML config)
    elif vbl_code == 'w':
        # Default to beaufort if nothing is specified in YAML
        unit = 'beaufort'
        
        # Look for a specific unit definition in the matched rules
        for rule in rules:
            if 'unit' in rule:
                unit = str(rule['unit']).lower().strip()
        
        # Apply the appropriate conversion to m/s
        if unit == 'miles per hour':
            val = val * 0.44704
            
        elif unit == 'beaufort':
            b_val = str(round(val))
            # Met Office Beaufort to m/s map (using mean wind speed in m/s)
            # https://weather.metoffice.gov.uk/guides/coast-and-sea/beaufort-scale
            # conversions to m/s for beaufort ranges or .5 were done using arithmetic mean
            beaufort_scale = {
                '0': 0.0, '1': 1, '2': 3, '3': 5, '4': 7, 
                '5': 10, '6': 12, '7': 15, '8': 19, '9': 23, 
                '10': 27, '11': 31, '12': 33,
                '0-1': 0.5, '1-2': 2,'2-3':4 ,'3-4': 6,'4-5':8.5 ,'5-6': 11,'6-7':13.5 ,'7-8':17 ,'8-9': 21,'9-10': 25,
                '0.5': 0.5, '1.5': 2,'2.5':4 ,'3.5': 6,'4.5':8.5 ,'5.5': 11,'6.5':13.5 ,'7.5':17 ,'8.5': 21,'9.5': 25
            }
            val = beaufort_scale.get(b_val, val)
                
        elif unit == 'm/s':
            pass # Already in m/s, do nothing

    return val

def extract_metadata(input_file_path, year, month):
    year = int(year)
    meta = {
        'name': 'UNKNOWN', 'lat': 0.0, 'lon': 0.0, 'alt': '0',
        'height_of_barometer': '', 'gravity_correction': '',
        'height_of_thermometer': '', 'height_of_rain_gauge': ''
    }
    
    # Helper to convert feet/inches to meters if year < 1912 (Handles commas and negatives)
    def process_height(val_str):
        clean_str = val_str.replace(',', '').replace(' ', '').lower()
        
        # Check if the string contains inches (e.g. '1ft8in' or just '8in')
        if 'in' in clean_str:
            # Extract feet (optional)
            ft_match = re.search(r'(-?\d+)ft', clean_str)
            feet = float(ft_match.group(1)) if ft_match else 0.0
            
            # Extract inches
            in_match = re.search(r'(\d+(\.\d+)?)in', clean_str)
            inches = float(in_match.group(1)) if in_match else 0.0
            
            # Calculate total decimal feet
            total_feet = feet + (inches / 12.0)
            
            # Convert decimal feet to meters
            if year < 1912:
                total_feet *= 0.3048
            return round(total_feet, 1)
            
        else:
            # Standard numeric extraction (no explicit 'in' suffix)
            m = re.search(r'(-?\d+(\.\d+)?)', clean_str)
            if m:
                val = float(m.group(1))
                if year < 1912:
                    val *= 0.3048
                return round(val, 1)
                
        return None
        
    raw_alt = None
    raw_hob = None
    
    try:
        with open(input_file_path, 'r', encoding='utf-8', errors='replace') as f:
            for _ in range(50): 
                line = f.readline().strip()
                if not line: continue
                
                if 'day' in line.lower() and any(x in line.lower() for x in ['barometer', 'rain', 'temp', 'wind']):
                    break
                
                line = line.lstrip('#').strip()
                parts = line.split(',', 1) 
                if len(parts) < 2: continue
                
                k, v = parts[0].strip().lower(), parts[1].strip()
                
                if 'title' in k: 
                    raw_name = v.upper()
                    raw_name = re.sub(r'\b(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER|JAN|FEB|MAR|APR|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b', '', raw_name)
                    raw_name = re.sub(r'\b\d{4}\b', '', raw_name)
                    raw_name = re.sub(r'[.-]', ' ', raw_name)
                    meta['name'] = " ".join(raw_name.split())
                    
                elif 'latitude' in k: meta['lat'] = parse_dms(v) or 0.0
                elif 'longitude' in k: meta['lon'] = parse_dms(v) or 0.0
                
                elif 'height_above_msl' in k or 'altitude' in k or 'elevation' in k: 
                    h = process_height(v)
                    if h is not None: 
                        raw_alt = h
                        meta['alt'] = f"{h:.1f}"
                
                elif 'barometer' in k and 'height' in k: 
                    h = process_height(v)
                    if h is not None:
                        raw_hob = h
                        meta['height_of_barometer'] = f"{h:.1f}m"
                    else:
                        meta['height_of_barometer'] = v
                    
                elif 'thermometer' in k and 'height' in k: 
                    h = process_height(v)
                    meta['height_of_thermometer'] = f"{h:.1f}m" if h is not None else v
                    
                elif 'rain' in k and 'height' in k: 
                    h = process_height(v)
                    meta['height_of_rain_gauge'] = f"{h:.1f}m" if h is not None else v
                    
                elif 'gravity' in k and 'correction' in k: 
                    meta['gravity_correction'] = v
                    
    except Exception: 
        pass
            
    return meta

def apply_metadata_overrides(meta, year, month):
    """
    Checks the YAML config for specific metadata overrides and applies them dynamically.
    """
    year = int(year)
    month = int(month)
    station_clean = meta['name'].lower().strip()
    
    overrides = CONFIG.get('metadata_overrides', [])
    
    for rule in overrides:
        if match_yaml_rule(rule, station_clean, year, month):
            
            # --- Altitude Overrides ---
            if 'alt_m' in rule:
                meta['alt'] = f"{float(rule['alt_m']):.1f}"
            elif 'alt_ft' in rule:
                meta['alt'] = f"{float(rule['alt_ft']) * 0.3048:.1f}"
                
            # --- Instrument Height Overrides ---
            if 'hob_m' in rule:
                meta['height_of_barometer'] = f"{float(rule['hob_m']):.1f}m"
            elif 'hob_ft' in rule:
                meta['height_of_barometer'] = f"{float(rule['hob_ft']) * 0.3048:.1f}m"
                
            if 'therm_m' in rule:
                meta['height_of_thermometer'] = f"{float(rule['therm_m']):.1f}m"
            elif 'therm_ft' in rule:
                meta['height_of_thermometer'] = f"{float(rule['therm_ft']) * 0.3048:.1f}m"
                
            if 'rain_m' in rule:
                meta['height_of_rain_gauge'] = f"{float(rule['rain_m']):.1f}m"
            elif 'rain_ft' in rule:
                meta['height_of_rain_gauge'] = f"{float(rule['rain_ft']) * 0.3048:.1f}m"
                
            # --- Coordinate Overrides ---
            if 'lat' in rule:
                meta['lat'] = float(rule['lat'])
            if 'lon' in rule:
                meta['lon'] = float(rule['lon'])
                
            # --- Name Overrides ---
            if 'name' in rule:
                meta['name'] = str(rule['name'])
                
    return meta

def import_csv_safe(input_file_path):
    abs_idx = -1
    try:
        with open(input_file_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if not row: continue
                joined = " ".join(str(cell).strip().lower() for cell in row if cell)
                if ("barometer" in joined or "air pressure" in joined) and "temp" in joined and len(row) > 3:
                    abs_idx = i
                    break
        if abs_idx == -1: return None

        df = pd.read_csv(input_file_path, header=abs_idx)
        df.columns = [clean_column_name(c) for c in df.columns]
        return df
    except Exception as e:
        print(f"  [!] import_csv_safe failed on {input_file_path}: {e}")   # find the real error
        import traceback; traceback.print_exc()   # full stack trace
        return None

# ==========================================
# 6. COLUMN MAPPING & EXTRACTION
# ==========================================

def find_time_cols(df_columns, keywords, excludes):
    """Scans headers for matches; supports multiple columns sharing the same time label."""
    found_cols = {}
    for col in df_columns:
        c_low = col.lower()
        if any(k in c_low for k in keywords) and not any(e in c_low for e in excludes):
            label, _ = parse_time_from_colname(col)
            if label:
                found_cols.setdefault(label, []).append(col)   # CHANGED: append, never overwrite
                if len(found_cols[label]) > 1:
                    print(f"  [i] Multiple columns share time label '{label}': "
                          f"{found_cols[label]} — keeping ALL, not discarding any")
            else:
                print(f"  [!] Column matched keyword but time could not be parsed: '{col}'")
    return found_cols

def detect_columns(df_cols, vbl_code):
    rules = VARIABLE_RULES[vbl_code]
    mapping = {}

    if rules['mode'] == 'simple':
        if rules.get('structure', 'point') == 'daily':
            matches = []   # CHANGED: collect every match, not just the first
            for col in df_cols:
                c_low = col.lower()
                if any(k in c_low for k in rules.get('keywords', [])) and not any(e in c_low for e in rules.get('exclude', [])):
                    matches.append(col)

            if len(matches) > 1:
                print(f"  [!] Ambiguous match for '{vbl_code}': multiple columns matched "
                      f"({matches}) — using first ('{matches[0]}'), others IGNORED")
            if matches:
                mapping['daily'] = matches[0]
        else:
            mapping = find_time_cols(df_cols, rules.get('keywords', []), rules.get('exclude', []))

    return mapping

def extract_sef_rows(df, meta_info, date_context, vbl_code, mapped_cols, filename):
    rules = VARIABLE_RULES[vbl_code]
    real_vbl_code = rules.get('sef_name', vbl_code)
    time_offset = meta_info['lon'] * 12 / 180
    data_frames = []
    g_year, g_month = date_context['year'], date_context['month']
    g_year_int = int(g_year)
    
    tz_abbr = get_time_zone_abbr(meta_info['name'], g_year)
    day_col = None
    for c in df.columns:
        if str(c).strip().lower() in ['day','date','d']:
            day_col = c
            break
    if not day_col:
        day_col = df.columns[0] # fallback to first col if no name match
    
    # Pre-clean the filename for QC matching
    f_name_lower = filename.strip().lower()
    
    for index, row in df.iterrows():
        try:
            r_day = str(int(float(row[day_col])))
        except Exception: 
            continue 
        
        try: obs_date = date(g_year_int, int(g_month), int(r_day))
        except ValueError: obs_date = date(g_year_int, int(g_month), 1)
        
        if real_vbl_code == 'rr':
            obs_date += timedelta(days=1)
            
        out_year, out_month, out_day = obs_date.year, obs_date.month, obs_date.day
        
        # --- SIMPLE VARIABLES ---
        if rules['mode'] == 'simple':
            items = []
            if rules.get('structure') == 'daily' and 'daily' in mapped_cols:
                if real_vbl_code == 'ss':
                    items.append(('daily', mapped_cols['daily'], None))
                else:
                    expected_times = META_RULES_ENGINE.get_expected_times(meta_info['name'], obs_date, real_vbl_code)
                    exp_time_str = expected_times[0] if expected_times else "09:00"
                    try:
                        h, m = map(int, exp_time_str.split(':'))
                        items.append((exp_time_str, mapped_cols['daily'], time(h, m)))
                    except Exception:
                        items.append(('09:00', mapped_cols['daily'], time(9, 0)))
            else:
                col_list = [(label, col) for label, cols in mapped_cols.items() if label != 'daily' for col in cols]
                expected_times = META_RULES_ENGINE.get_expected_times(meta_info['name'], obs_date, real_vbl_code)

                if expected_times and len(expected_times) == len(col_list):
                    for exp_time, (parsed_label, col) in zip(expected_times, col_list):
                        try:
                            h, m = map(int, exp_time.split(':'))
                            items.append((exp_time, col, time(h, m)))
                        except Exception:
                            items.append(('09:00', col, time(9, 0)))
                else:
                    if not col_list: # guard against the empty case explicitly
                        print(f"  [!] No columns to process for '{vbl_code}' on {obs_date} — skipping row")
                    for parsed_label, col in col_list:
                        h, m = map(int, parsed_label.split(':'))
                        items.append((parsed_label, col, time(h, m)))

            convert_func, orig_unit = get_era_logic(rules['qty_type'], out_year)
            if real_vbl_code == 'w': orig_unit = get_wind_unit(meta_info['name'], out_year)
            unit_str = f" {orig_unit}" if orig_unit else ""
            
            skip_orig = False
            identical_units = ['mb', 'mm', '%', 'oktas/tenths', 'hours', 'h', 'm/s']
            if orig_unit in identical_units: skip_orig = True
            elif rules['qty_type'] == 'wind_dir' and out_year >= 1918: skip_orig = True

            for label, col, t_obj in items:
                try: raw = row[col]
                except KeyError:
                    try: raw = row.iloc[list(df.columns).index(col)]
                    except Exception: continue
                    
                if pd.isna(raw) or str(raw).strip() == '' or str(raw).lower() == 'nan': continue

                # --- Aberdeen 1921 Cloud Cleaning ---
                # For Aberdeen 1921 only, both cloud cover (digits) and visibility (letters) were printed in the cloud col
                # Strips all letters/characters, keeping only digits
                if real_vbl_code == 'n' and meta_info['name'].lower().strip() == 'aberdeen' and g_year_int == 1921:
                    raw = re.sub(r'[^\d.]', '', str(raw)).strip()
                    if not raw: continue  # Skip if it was entirely letters (e.g. "c")
                # ------------------------------------
                    
                try:
                    clean_raw = str(raw).strip().strip('.') 
                    converted_raw = convert_func(clean_raw)
                    
                    if str(converted_raw) == 'NA':
                        val = 'NA'
                    else:
                        val = float(converted_raw)
                        val = apply_active_corrections(val, real_vbl_code, meta_info['name'], out_year, meta_info)
                        prec = get_precision(real_vbl_code, out_year)
                        val = round(val, prec)
                        if prec == 0: val = int(val)
                    
                    # --- QC Column math (wind direction SEFs have qc_colmath=NA) ---
                    if real_vbl_code == 'dd':
                        qc_flag = "NA"
                    else:
                        qc_flag = QC_COLMATH_SET.get((f_name_lower, str(col).strip().lower()), "fail")
                    
                    meta_parts = []
                    if not skip_orig: meta_parts.append(f"orig={str(raw).strip()}{unit_str}")
                    if real_vbl_code != 'ss':
                        if t_obj is None: meta_parts.append(f"orig.time={label}")
                        else: meta_parts.append(f"orig.time={label}{tz_abbr}")
                            
                    # meta_parts.append(f"orig.col={str(col).strip()}") # for debugging
                    # meta_parts.append(f"orig.file={filename}")   # filename for debugging
                    meta_parts.append(f"qc_colmath={qc_flag}")  # Append QC column math flag
                    
                    meta_str = "|".join(meta_parts)
                    
                    add_sef_row(data_frames, out_year, out_month, out_day, t_obj, tz_abbr, 
                                rules.get('period', 0), val, meta_str)
                except Exception as e: 
                    print(f"  -> ERROR converting '{real_vbl_code}' value '{raw}' on {out_year}-{out_month}-{out_day}: {e}")

        
    return data_frames


# Memory Optimization: Append standard Python dicts instead of Pandas DataFrames (95% memory reduction)
def add_sef_row(rows_list, y, m, d, t_obj, tz_abbr, period, val, meta):
    if val == '': return
    try:
        if t_obj is None:
            rows_list.append({
                'Year': int(y), 'Month': int(m), 'Day': int(d), 
                'Hour': 'NA', 'Minute': 'NA', 'Period': period, 
                'Value': val, 'Meta': meta, 
                '_tz_abbr': tz_abbr, '_is_time_null': True
            })
        else:
            rows_list.append({
                'Year': int(y), 'Month': int(m), 'Day': int(d), 
                'Hour': t_obj.hour, 'Minute': t_obj.minute, 'Period': period, 
                'Value': val, 'Meta': meta, 
                '_tz_abbr': tz_abbr, '_is_time_null': False
            })
    except Exception: pass

# ==========================================
# 7. WRITING AGGREGATED SEF
# ==========================================

def get_header_template(meta_info, vbl_code, year, month):
    rules = VARIABLE_RULES[vbl_code]
    real_vbl_code = rules.get('sef_name', vbl_code) 
    c_year, c_month = int(year), int(month)
    
    if real_vbl_code == 'p':
        real_vbl_code = get_pressure_sef_code(meta_info['name'], c_year)
        
    global_meta = CONFIG.get('global_metadata', {})
    source = global_meta.get('source')
    link = global_meta.get('link')
    
    # --- GET SPECIFIC SENSOR ALTITUDE FOR 'Alt' HEADER ---
    final_alt_val = get_final_sensor_alt(meta_info, real_vbl_code, c_year, c_month)
    
    missing_flags = ['0', '0.0', '0.00', '', 'MISMATCH', 'NONE', 'NAN', 'NULL']
    
    raw_alt = str(meta_info.get('alt', '')).strip().upper()
    if raw_alt in missing_flags:
        final_alt_str = "NA"
    else:
        final_alt_str = f"{final_alt_val:.1f}"

    # 1. Start with CSV-derived Metadata
    sef_meta_parts = ["Adjusted=N"]
    
    if real_vbl_code in ['p', 'mslp']:
        sef_meta_parts.append("PTC=Y")
        sef_meta_parts.append("PTC_Correction=32F")
        sef_meta_parts.append("PGC=Y")
        if c_year >= 1889:
            gc = str(meta_info.get('gravity_correction', '')).strip()
            if gc.upper() in missing_flags: sef_meta_parts.append("PGC_Correction=NA")
            elif gc: sef_meta_parts.append(f"PGC_Correction={gc}")
            
    elif real_vbl_code in ['Ta', 'Tn', 'Tx', 'dep_wet']:
        th = str(meta_info.get('height_of_thermometer', '')).strip()
        if th.upper() in missing_flags:
            sef_meta_parts.append("height_of_thermometer=NA")
        elif th:
            sef_meta_parts.append(f"height_of_thermometer={th}")
            
    elif real_vbl_code == 'rr':
        rg = str(meta_info.get('height_of_rain_gauge', '')).strip()
        if rg.upper() in missing_flags:
            sef_meta_parts.append("height_of_raingauge=NA")
        elif rg:
            sef_meta_parts.append(f"height_of_raingauge={rg}")

    # 2. Append newly extracted YAML Metadata
    yaml_meta = get_yaml_meta_for_variable(meta_info['name'], year, real_vbl_code, c_month, meta_info.get('lat'), meta_info.get('lon'))
    sef_meta_parts.extend(yaml_meta)
    
    if meta_info['name'].lower().strip() == 'fort william':
        sef_meta_parts.append("Note= precise latitude and longitude are uncertain due to conflicting heights of the station and the barometer")

    if meta_info['name'].lower().strip() == 'dartmoor' and real_vbl_code in ['p', 'mslp'] and c_year < 1878:
        sef_meta_parts.append("Correction=+2.0318 hPa")


    # Format to SEF string
    sef_meta_str = "|".join(sef_meta_parts) if sef_meta_parts else ""
    
    return {
        'SEF': '1.0.0', 
        'ID': meta_info['name'].replace(' ', '_'), 
        'Name': meta_info['name'].title().replace("'S", "'s"),
        'Lat': meta_info['lat'] if meta_info['lat'] != 0.0 else "NA", 
        'Lon': meta_info['lon'] if meta_info['lon'] != 0.0 else "NA", 
        'Alt': final_alt_str,
        'Source': source, 'Link': link, 'Vbl': real_vbl_code, 'Stat': rules.get('stat', ''),
        'Units': rules.get('units', ''), 
        'Meta': sef_meta_str
    }


def _pack(m_list):
    if m_list is None: return m_list
    elif isinstance(m_list, str): return m_list
    else: return ','.join(m_list)

def write_aggregated_sef(agg_data, output_root):
    print(f"\n--- Writing {len(agg_data)} aggregated SEF files ---")
    for group_key, payload in agg_data.items():
        station_name, lat, lon, alt, vbl_code = group_key
        if not payload['rows']: continue
        
        # Convert massive list of memory-efficient dictionaries into a single Pandas DataFrame right before writing
        df_combined = pd.DataFrame(payload['rows'])
        payload['rows'] = [] # Free RAM immediately
        
        # --- APPLY UTC TIME OFFSETS DYNAMICALLY ---
        # Because we do this here, missing months inherit the exact, healed Longitude of the group!
        def calculate_utc(row):
            if row['_is_time_null']:
                return row['Year'], row['Month'], row['Day'], 'NA', 'NA'
            
            tz = str(row['_tz_abbr']).strip()
            if tz == 'GMT':
                offset = 0.0
            elif tz == 'DMT':
                offset = -0.4225  # Dublin Mean Time is 25 mins 21 seconds behind UTC
            else:
                offset = lon * 12 / 180  # LMT uses the final, correct group Longitude
                
            local_dt = datetime(row['Year'], row['Month'], row['Day'], row['Hour'], row['Minute'])
            utc_dt = local_dt - timedelta(hours=offset)
            
            return utc_dt.year, utc_dt.month, utc_dt.day, utc_dt.hour, utc_dt.minute

        if not df_combined.empty:
            df_combined[['Year', 'Month', 'Day', 'Hour', 'Minute']] = df_combined.apply(calculate_utc, axis=1, result_type='expand')
            # Clean up the temporary helper columns
            df_combined = df_combined.drop(columns=['_tz_abbr', '_is_time_null'])
        
        df_combined.sort_values(by=['Year', 'Month', 'Day', 'Hour', 'Minute', 'Period'], inplace=True)
        
        first_row = df_combined.iloc[0]
        last_row = df_combined.iloc[-1]
        
        start_str = f"{int(first_row['Year']):04d}{int(first_row['Month']):02d}{int(first_row['Day']):02d}"
        end_str = f"{int(last_row['Year']):04d}{int(last_row['Month']):02d}{int(last_row['Day']):02d}"
        
        st_clean = station_name.replace(' ', '_').upper()
        out_name = f"{st_clean}_{vbl_code}_{start_str}_{end_str}.tsv"
        out_path = os.path.join(output_root, st_clean, out_name)
        
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        obs = payload['header']
        
        with codecs.open(out_path, 'w', encoding='utf-8') as f:
            obs['Meta'] = _pack(obs['Meta'])
            for key in ('SEF', 'ID', 'Name', 'Source', 'Lat', 'Lon', 'Alt', 'Link', 'Vbl',
                       'Stat', 'Units', 'Meta'):
                val = obs.get(key, '')
                if val is not None and str(val) != 'nan': f.write(f"{key}\t{val}\n")
                else: f.write(f"{key}\t\n")

            df_combined.to_csv(f, sep='\t', header=True, index=False)
            
        print(f"  Created: {out_path} ({len(df_combined)} rows)")

# ==========================================
# 8. ORCHESTRATION & FILE FINDING
# ==========================================
# for disk-backed aggregation
NEXT_GROUP_ID = 1
GROUP_INFO = {}
def get_raw_group_key(meta, file_vbl_code, year, month):
    station = meta['name']
    try: c_lat = float(meta['lat'])
    except (ValueError, TypeError): c_lat = 0.0
    try: c_lon = float(meta['lon'])
    except (ValueError, TypeError): c_lon = 0.0
    
    c_final_alt_val = get_final_sensor_alt(meta, file_vbl_code, year, month)
    missing_flags = ['0', '0.0', '0.00', '', 'MISMATCH', 'NONE', 'NAN', 'NULL']
    
    raw_alt = str(meta.get('alt', '')).strip().upper()
    is_missing_alt = raw_alt in missing_flags
    
    is_missing_inst = False
    if file_vbl_code in ['p', 'mslp']:
        hob = str(meta.get('height_of_barometer', '')).strip().upper()
        if hob in missing_flags: is_missing_inst = True
    elif file_vbl_code in ['Ta', 'Tn', 'Tx']:
        th = str(meta.get('height_of_thermometer', '')).strip().upper()
        if th in missing_flags: is_missing_inst = True
    elif file_vbl_code == 'rr':
        rg = str(meta.get('height_of_rain_gauge', '')).strip().upper()
        if rg in missing_flags: is_missing_inst = True

    if is_missing_alt or is_missing_inst: c_final_alt_str = "MISSING"
    else: c_final_alt_str = f"{c_final_alt_val:.1f}"

    if c_final_alt_str != "MISSING":
        for k in GROUP_INFO.keys():
            k_station, k_lat, k_lon, k_alt_str, k_vbl = k
            if (k_station == station and k_vbl == file_vbl_code and k_lat == c_lat and k_lon == c_lon):
                if k_alt_str != "MISSING":
                    k_final_alt_val = float(k_alt_str)
                    if abs(c_final_alt_val - k_final_alt_val) < 1.0:
                        return k
                        
    return (station, c_lat, c_lon, c_final_alt_str, file_vbl_code)

def get_date_context(filepath):
    fname = os.path.basename(filepath).lower()
    ym_match = re.search(r'(\d{4})_(\d{2})', fname)
    if ym_match: return {'year': ym_match.group(1), 'month': ym_match.group(2)}

def process_file_into_aggregator(input_path):
    global NEXT_GROUP_ID
    print(f"Processing: {os.path.basename(input_path)}")
    if not os.path.exists(input_path): return
    
    date_context = get_date_context(input_path)
    if not date_context: return
    
    meta = extract_metadata(input_path, date_context['year'], date_context['month'])
    
    st = meta['name'].lower().strip()
    hob_str = meta.get('height_of_barometer', '')
    if hob_str and st in STATION_NEGATIVE_HOBS:
        m = re.search(r'(-?\d+(\.\d+)?)', str(hob_str))
        if m:
            val = float(m.group(1))
            if val > 0 and round(val, 1) in STATION_NEGATIVE_HOBS[st]:
                meta['height_of_barometer'] = hob_str.replace(m.group(1), f"-{m.group(1)}", 1)

    df = import_csv_safe(input_path)
    if df is None: return

    meta = apply_metadata_overrides(meta, date_context['year'], date_context['month'])
    
    for vbl_code in VARIABLE_RULES:
        mapped_cols = detect_columns(df.columns, vbl_code)
        if not mapped_cols: continue
        
        vbl_meta = meta.copy()
        file_vbl_code = VARIABLE_RULES[vbl_code].get('file_name', vbl_code)
        real_vbl_code = VARIABLE_RULES[vbl_code].get('sef_name', vbl_code)
        
        if real_vbl_code == 'p':
            file_vbl_code = get_pressure_sef_code(vbl_meta['name'], date_context['year'])
            real_vbl_code = file_vbl_code
            
        filename = os.path.basename(input_path)
        extracted_rows = extract_sef_rows(df, vbl_meta, date_context, vbl_code, mapped_cols, filename)
        if not extracted_rows: continue
        
        group_key = get_raw_group_key(vbl_meta, file_vbl_code, date_context['year'], date_context['month'])
        
        if group_key not in GROUP_INFO:
            GROUP_INFO[group_key] = {
                'id': NEXT_GROUP_ID,
                'header': get_header_template(vbl_meta, vbl_code, date_context['year'], date_context['month']),
                'years': set()
            }
            NEXT_GROUP_ID += 1
        else:
            new_yaml_meta = get_yaml_meta_for_variable(vbl_meta['name'], date_context['year'], real_vbl_code, date_context['month'], vbl_meta.get('lat'), vbl_meta.get('lon'))
            current_meta_str = GROUP_INFO[group_key]['header'].get('Meta', '')
            current_parts = current_meta_str.split('|') if current_meta_str else []
            added_something = False
            for part in new_yaml_meta:
                if part and part not in current_parts:
                    current_parts.append(part)
                    added_something = True
            if added_something:
                GROUP_INFO[group_key]['header']['Meta'] = "|".join([p for p in current_parts if p])

        # Disk-Backed memory safety: Write extracted rows directly to disk, freeing RAM immediately
        group_id = GROUP_INFO[group_key]['id']
        temp_csv = TEMP_DIR / f"{group_id}.csv"
        file_exists = temp_csv.exists()
        
        with open(temp_csv, 'a', newline='', encoding='utf-8') as f:
            fieldnames = ['Year', 'Month', 'Day', 'Hour', 'Minute', 'Period', 'Value', 'Meta', '_tz_abbr', '_is_time_null']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for r in extracted_rows:
                writer.writerow(r)
                GROUP_INFO[group_key]['years'].add(int(r['Year']))

def consolidate_orphans():
    print("\n--- Consolidating Missing Metadata ---")
    valid_groups = {}
    orphan_groups = {}
    
    for k, info in GROUP_INFO.items():
        station, lat, lon, alt_str, vbl = k
        if (float(lat) == 0.0 or float(lon) == 0.0) or alt_str == "MISSING":
            orphan_groups[k] = info
        else:
            valid_groups[k] = info
            
    for o_key, o_info in orphan_groups.items():
        o_station = o_key[0]
        o_vbl = o_key[4] 
        o_id = o_info['id']
        o_file = TEMP_DIR / f"{o_id}.csv"
        if not o_file.exists(): continue
        
        candidates = [k for k in valid_groups.keys() if k[0] == o_station and k[4] == o_vbl]
        if not candidates:
            valid_groups[o_key] = o_info
            continue

        # Group orphan rows by destination candidate to avoid massive looping
        rows_by_cand = {}
        with open(o_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                row_year = int(row['Year'])
                best_cand = None
                for ck in candidates:
                    if row_year in valid_groups[ck]['years']:
                        best_cand = ck; break
                if not best_cand:
                    best_cand = candidates[-1]
                    valid_groups[best_cand]['years'].add(row_year)
                
                cand_id = valid_groups[best_cand]['id']
                if cand_id not in rows_by_cand: rows_by_cand[cand_id] = []
                rows_by_cand[cand_id].append(row)
                
        # Append rows into candidate files efficiently
        for cand_id, rows in rows_by_cand.items():
            cand_file = TEMP_DIR / f"{cand_id}.csv"
            with open(cand_file, 'a', newline='', encoding='utf-8') as out_f:
                writer = csv.DictWriter(out_f, fieldnames=fieldnames)
                for r in rows: writer.writerow(r)
        
        # Merge YAML Headers
        for cand_id in rows_by_cand.keys():
            # Find the full key for this candidate ID
            best_cand = next(k for k, v in valid_groups.items() if v['id'] == cand_id)
            
            orphan_meta_str = o_info['header'].get('Meta', '')
            valid_meta_str = valid_groups[best_cand]['header'].get('Meta', '')
            
            valid_parts = valid_meta_str.split('|') if valid_meta_str else []
            orphan_parts = orphan_meta_str.split('|') if orphan_meta_str else []
            
            added_something = False
            for part in orphan_parts:
                if part and part not in valid_parts and "NA" not in part.split(':')[-1].split('=')[-1]:
                    key_name = part.split(':')[0].split('=')[0]
                    if not any(v_part.startswith(key_name) for v_part in valid_parts):
                        valid_parts.append(part)
                        added_something = True
                    
            if added_something:
                valid_groups[best_cand]['header']['Meta'] = "|".join([p for p in valid_parts if p])

        # Delete orphan file
        o_file.unlink()

    return valid_groups

def write_aggregated_sef(final_groups):
    print(f"\n--- Writing final SEF files from Disk Cache ---")
    for group_key, info in final_groups.items():
        station_name, lat, lon, alt, vbl_code = group_key
        cand_id = info['id']
        cand_file = TEMP_DIR / f"{cand_id}.csv"
        
        if not cand_file.exists(): continue
        
        df_combined = pd.read_csv(cand_file, dtype={'Hour': str, 'Minute': str, '_tz_abbr': str, '_is_time_null': str})
        
        def calculate_utc(row):
            if str(row['_is_time_null']).lower() == 'true': 
                return int(row['Year']), int(row['Month']), int(row['Day']), 'NA', 'NA'
            tz = str(row['_tz_abbr']).strip()
            if tz == 'GMT': offset = 0.0
            elif tz == 'DMT': offset = -0.4225
            else: offset = lon * 12 / 180
            local_dt = datetime(int(row['Year']), int(row['Month']), int(row['Day']), int(float(row['Hour'])), int(float(row['Minute'])))
            utc_dt = local_dt - timedelta(hours=offset)
            return utc_dt.year, utc_dt.month, utc_dt.day, utc_dt.hour, utc_dt.minute

        if not df_combined.empty:
            df_combined[['Year', 'Month', 'Day', 'Hour', 'Minute']] = df_combined.apply(calculate_utc, axis=1, result_type='expand')
            df_combined = df_combined.drop(columns=['_tz_abbr', '_is_time_null'])
        
        df_combined.sort_values(by=['Year', 'Month', 'Day', 'Hour', 'Minute', 'Period'], inplace=True)
        
        first_row = df_combined.iloc[0]
        last_row = df_combined.iloc[-1]
        start_str = f"{int(first_row['Year']):04d}{int(first_row['Month']):02d}{int(first_row['Day']):02d}"
        end_str = f"{int(last_row['Year']):04d}{int(last_row['Month']):02d}{int(last_row['Day']):02d}"
        
        st_clean = station_name.replace(' ', '_').upper()
        out_name = f"{st_clean}_{vbl_code}_{start_str}_{end_str}.tsv"
        out_path = os.path.join(OUTPUT_ROOT, st_clean, out_name)
        
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        obs = info['header']
        
        with codecs.open(out_path, 'w', encoding='utf-8') as f:
            obs['Meta'] = _pack(obs['Meta'])
            for key in ('SEF', 'ID', 'Name', 'Source', 'Lat', 'Lon', 'Alt', 'Link', 'Vbl', 'Stat', 'Units', 'Meta'):
                val = obs.get(key, '')
                if val is not None and str(val) != 'nan': f.write(f"{key}\t{val}\n")
                else: f.write(f"{key}\t\n")
            df_combined.to_csv(f, sep='\t', header=True, index=False)
            
        print(f"  Created: {out_path} ({len(df_combined)} rows)")

def index_input_directory(root_dir):
    file_map = {}
    for dirpath, _, filenames in os.walk(root_dir):
        for f in filenames:
            if f.endswith('.csv') and not f.startswith('.'):
                file_map[f.lower()] = os.path.join(dirpath, f)
    return file_map

def main():
    files_to_process = []
    
    if BATCH_LIST_PATH and BATCH_LIST_PATH.exists():
        print(f"--- Running in Batch List Mode: {BATCH_LIST_PATH} ---")
        file_index = index_input_directory(str(INPUT_ROOT))
        df_list = pd.read_csv(BATCH_LIST_PATH)
        path_col = next((c for c in df_list.columns if c.lower() in ['filepath','file','path','filename']), df_list.columns[0])
        for _, row in df_list.iterrows():
            fpath_raw = row[path_col]
            if pd.isna(fpath_raw) or not str(fpath_raw).strip(): continue
            fpath_raw = str(fpath_raw).strip()
            target_filename = os.path.basename(fpath_raw).lower()
            if os.path.exists(fpath_raw): files_to_process.append(fpath_raw)
            elif os.path.exists(os.path.abspath(fpath_raw)): files_to_process.append(os.path.abspath(fpath_raw))
            elif target_filename in file_index: files_to_process.append(file_index[target_filename])
            else:
                jp = INPUT_ROOT / fpath_raw
                if jp.exists(): files_to_process.append(str(jp))
                else: print(f"SKIPPING: '{fpath_raw}'")

    elif INPUT_ROOT and INPUT_ROOT.exists():
        print(f"--- Running in Directory Walk Mode: {INPUT_ROOT} ---")
        for dirpath, _, filenames in os.walk(INPUT_ROOT):
            for f in filenames:
                if f.endswith('.csv') and not f.startswith('.'):
                    if BATCH_LIST_PATH and BATCH_LIST_PATH.name == f: continue
                    files_to_process.append(os.path.join(dirpath, f))
    else:
        print("Error: No valid input_root or batch_list found in config.")
        return

    global STATION_NEGATIVE_HOBS
    STATION_NEGATIVE_HOBS = {}
    
    print("\n--- Pre-scanning files for negative Barometer heights ---")
    for fp in files_to_process:
        date_ctx = get_date_context(fp)
        if not date_ctx: continue
        meta = extract_metadata(fp, date_ctx['year'], date_ctx['month'])
        hob_str = meta.get('height_of_barometer', '')
        if hob_str:
            m = re.search(r'(-?\d+(\.\d+)?)', str(hob_str))
            if m:
                val = float(m.group(1))
                if val < 0:
                    st = meta['name'].lower().strip()
                    if st not in STATION_NEGATIVE_HOBS:
                        STATION_NEGATIVE_HOBS[st] = set()
                    STATION_NEGATIVE_HOBS[st].add(round(abs(val), 1))

    print(f"\n--- Processing {len(files_to_process)} files (Disk-Backed) ---")
    for fp in files_to_process:
        process_file_into_aggregator(fp)

    final_groups = consolidate_orphans()
    write_aggregated_sef(final_groups)
    
    print("\n--- Cleaning up temporary files ---")
    shutil.rmtree(TEMP_DIR, ignore_errors=True)

if __name__ == "__main__":
    main()