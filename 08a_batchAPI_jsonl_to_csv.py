import json
import csv
import re
from pathlib import Path
from typing import Any, Dict

# -----------------------------
# Helpers
# -----------------------------

def get_unique_path(filepath: Path):
    """
    Checks if a file already exists BEFORE writing. 
    If it does, appends _1, _2 to prevent overwriting.
    Returns: (Unique Path, Boolean indicating if it had to be renamed)
    """
    if not filepath.exists():
        return filepath, False
    
    counter = 1
    while True:
        new_path = filepath.parent / f"{filepath.stem}_{counter}{filepath.suffix}"
        if not new_path.exists():
            return new_path, True
        counter += 1


def split_title_and_note(raw_title: str):
    """
    Finds standard metadata phrases in the title (Height, Lat, Long) 
    and slices them out to create a clean title and a separate note.
    """
    note_start_regex = re.compile(r"(height\s+above|\blong\b|\blat\b|latitude|longitude|gravity\s+correction)", re.IGNORECASE)
    months = r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    date_regex = re.compile(r"\b" + months + r"\b\s*\d{4}", re.IGNORECASE)
    
    start_match = note_start_regex.search(raw_title)
    
    if not start_match:
        return raw_title.strip(), ""
        
    start_idx = start_match.start()
    date_match = date_regex.search(raw_title[start_idx:])
    
    if date_match:
        end_idx = start_idx + date_match.start()
        note = raw_title[start_idx:end_idx].strip(' .,-')
        clean_t = raw_title[:start_idx].strip(' .,-') + " " + raw_title[start_idx + date_match.start():].strip(' .,-')
    else:
        note = raw_title[start_idx:].strip(' .,-')
        clean_t = raw_title[:start_idx].strip(' .,-')
        
    clean_t = re.sub(r'\s+', ' ', clean_t)
    clean_t = clean_t.replace(' .', '.').replace(', .', ',')
    clean_t = clean_t.strip(' .,-')
    
    return clean_t, note


def standardise_filename(text: str, max_len: int = 80) -> str:
    text = text.lower()
    month_pattern = r"\b(january|february|march|april|may|june|july|august|september|october|november|december)[a-z]*\.?"
    parts = re.split(f"({month_pattern}.*)", text, maxsplit=1)
    
    if len(parts) > 1:
        station_part = parts[0].strip()
        date_part = "".join(parts[1])
    else:
        station_part = text
        date_part = ""

    station_clean = re.sub(r"[^\w\s]", "", station_part).strip()
    station_clean = re.sub(r"\s+", "_", station_clean)

    date_clean = re.sub(r"[^\w\s]", "", date_part).strip()
    date_clean = re.sub(r"\s+","_", date_clean)

    if station_clean and date_clean:
        final = f"{station_clean}_{date_clean}"
    elif date_clean:
        final = date_clean
    else:
        final = station_clean
    return final[:max_len]


def extract_tables_lenient(obj):
    try:
        candidates = obj["response"]["candidates"]
    except (KeyError, TypeError):
        return []

    for cand in candidates:
        content = cand.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if not text:
                continue

            clean_text = text.strip()
            if clean_text.startswith("```"):
                clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
                clean_text = re.sub(r"\s*```$", "", clean_text)
            
            try:
                parsed = json.loads(clean_text)
            except json.JSONDecodeError:
                continue

            if isinstance(parsed, list):
                return [t for t in parsed if isinstance(t, dict)]
            elif isinstance(parsed, dict):
                return [parsed]

    return []


def write_csv(table: Dict[str, Any], csv_path: Path):
    title = table.get("title", "Untitled")
    extracted_note = table.get("extracted_note", "")
    source_filename = table.get("source_filename", "")
    metadata = table.get("metadata", {})
    columns = table.get("columns", [])
    data = table.get("data", [])

    if not columns or not data:
        return False

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL, escapechar='\\')
        writer.writerow(["# TITLE", str(title)])
        writer.writerow(["# SOURCE_FILENAME", str(source_filename)])
        if extracted_note:
            writer.writerow(["# NOTE", str(extracted_note)])

        if metadata:
            writer.writerow(["# METADATA"])
            for k, v in metadata.items():
                if isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        writer.writerow([f"# {k}.{sub_k}", str(sub_v)])
                elif isinstance(v, list):
                    writer.writerow([f"# {k}", ", ".join(map(str, v))])
                else:
                    writer.writerow([f"# {k}", str(v)])
            writer.writerow([])

        safe_columns = [str(c) if c is not None else "" for c in columns]
        writer.writerow(safe_columns)

        for row in data:
            if not isinstance(row, list):
                row = [row]
            if len(row) < len(columns):
                row += [""] * (len(columns) - len(row))
            safe_row = [str(cell) if cell is not None else "" for cell in row]
            writer.writerow(safe_row)

    return True

def write_txt_fallback(table: Dict[str, Any], txt_path: Path):
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"SOURCE FILENAME: {table.get('source_filename', 'Unknown')}\n")
        f.write("="*50 + "\n")
        for key, value in table.items():
            f.write(f"--- {key.upper()} ---\n")
            f.write(f"{str(value)}\n\n")

# -----------------------------
# Main JSONL processor
# -----------------------------

def jsonl_to_csv(jsonl_path: Path, output_dir: Path, failed_txt_path: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Load the Failed Images List
    failed_images = set()
    with open(failed_txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                failed_images.add(Path(line).name)
    
    # Counters
    total_lines = 0
    skipped_no_source_filename = 0
    skipped_matched_failed_list = 0
    
    csv_success = 0
    txt_fallback = 0
    raw_text_saved = 0
    overwrites_prevented = 0 

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            total_lines += 1
            line = line.strip()
            
            if not line:
                skipped_no_source_filename += 1
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                skipped_no_source_filename += 1
                continue

            if "error" in obj:
                skipped_no_source_filename += 1
                continue

            tables = extract_tables_lenient(obj)
            
            # --- SCENARIO A: RAW TEXT (NO VALID JSON STRUCT) ---
            if not tables:
                raw_text = ""
                try:
                    for cand in obj.get("response", {}).get("candidates", []):
                        for part in cand.get("content", {}).get("parts", []):
                            if "text" in part:
                                raw_text += part["text"] + "\n"
                except Exception:
                    pass
                
                # STRICT CHECK: Must have text AND the text must contain a valid .jpg string
                if raw_text.strip():
                    match = re.search(r'([a-zA-Z0-9_]+\.(?:jpg|jpeg|JPG|JPEG))', raw_text)
                    
                    if match and "source_filename" in raw_text:
                        filename = match.group(1)
                        if filename in failed_images:
                            skipped_matched_failed_list += 1
                            continue
                        
                        safe_name = standardise_filename(filename)
                        
                        raw_txt_path = output_dir / f"{line_no}_{safe_name}_NO_JSON_RAW_TEXT.txt"
                        
                        # Prevent Overwrite Check BEFORE writing
                        raw_txt_path, renamed = get_unique_path(raw_txt_path)
                        if renamed: overwrites_prevented += 1

                        with open(raw_txt_path, "w", encoding="utf-8") as rf:
                            rf.write("GEMINI RAW TEXT OUTPUT:\n")
                            rf.write("="*50 + "\n")
                            rf.write(raw_text)
                            
                        raw_text_saved += 1
                    else:
                        # Throws out LLM hallucinated instructions like "source_filename (string)"
                        skipped_no_source_filename += 1
                else:
                    skipped_no_source_filename += 1
                continue

            # --- SCENARIO B: PARSED JSON DICTS ---
            valid_tables = [t for t in tables if t.get("source_filename")]
            if not valid_tables:
                skipped_no_source_filename += 1
                continue

            first_filename = valid_tables[0].get("source_filename", "").strip()
            if first_filename in failed_images:
                skipped_matched_failed_list += 1
                continue

            for t_idx, table in enumerate(valid_tables, start=1):
                raw_title = table.get("title", f"Table_Line_{line_no}")
                
                clean_title, extracted_note = split_title_and_note(raw_title)
                
                table["title"] = clean_title
                table["extracted_note"] = extracted_note

                safe_title = standardise_filename(clean_title[:100])
                if not safe_title:
                    safe_title = f"line_{line_no}"

                base_name = f"{line_no}_{safe_title}_table_{t_idx}"
                csv_path = output_dir / f"{base_name}.csv"
                txt_path = output_dir / f"{base_name}_FAILED_FORMAT.txt"

                columns = table.get("columns", [])
                data = table.get("data", [])
                
                if columns and data:
                    csv_path, renamed = get_unique_path(csv_path)
                    if renamed: overwrites_prevented += 1
                    
                    if write_csv(table, csv_path):
                        csv_success += 1
                else:
                    txt_path, renamed = get_unique_path(txt_path)
                    if renamed: overwrites_prevented += 1
                    
                    write_txt_fallback(table, txt_path)
                    txt_fallback += 1
                    
                    
    # --- Print Detailed Report ---
    print("\n" + "=" * 50)
    print(" EXTRACTION FILTER REPORT ")
    print("=" * 50)
    print(f"Total lines read from JSONL:             {total_lines}")
    print("-" * 50)
    print(f"[ SKIPPED / FAILED IMAGES ]")
    print(f"True Failures (from Audit list):         {len(failed_images)}")
    print(f"  -> Breakdown of skips during extraction:")
    print(f"     - Filtered explicitly by failed list: {skipped_matched_failed_list}")
    print(f"     - Missing/No filename in JSONL line:  {skipped_no_source_filename}")
    print("-" * 50)
    print("[ SUCCESSFULLY EXTRACTED & RESCUED ]")
    print(f"Valid CSV files created:                 {csv_success}")
    print(f"Malformed JSONs rescued (.txt):          {txt_fallback}")
    print(f"Raw Text JSONs rescued (.txt):           {raw_text_saved}")
    print("-" * 50)
    if overwrites_prevented > 0:
        print(f"⚠️  Overwrites Prevented (Files Renamed):  {overwrites_prevented}")
    else:
        print(f"Overwrites Prevented:                    0 (Clean run!)")
    print("=" * 50 + "\n")



# -----------------------------
# usage
# -----------------------------

jsonl_file = Path("")
output_dir = Path("")

failed_txt_path = Path("")

jsonl_to_csv(jsonl_file, output_dir, failed_txt_path)

