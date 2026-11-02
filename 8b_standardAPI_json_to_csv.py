import json
import csv
import re
from pathlib import Path
from typing import Any, Dict, List

# -----------------------------
# Helpers
# -----------------------------

def standardise_filename(text: str, max_len: int = 80) -> str:
    """
    Parses "ARMAGH. - FEBRUARY 1897." into "armagh_february_1897"
    """
    text = text.lower()
    month_pattern = r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    
    # Search for Month followed by anything, then a 4-digit Year
    match = re.search(rf"{month_pattern}.*?(\d{{4}})", text)
    
    if match:
        month = match.group(1)
        year = match.group(2)
        
        # The location is everything before the month
        location_raw = text[:match.start()].strip()
        location_clean = re.sub(r"[^\w\s]", "", location_raw).strip()
        location_clean = re.sub(r"\s+", "_", location_clean)
        
        final = f"{location_clean}_{month}_{year}"
    else:
        # Fallback if no month/year is found
        clean = re.sub(r"[^\w\s]", "", text).strip()
        final = re.sub(r"\s+", "_", clean)
        
    return final[:max_len]


def is_table(obj: Any) -> bool:
    """Check if a dictionary represents a table structure."""
    return isinstance(obj, dict) and "columns" in obj and "data" in obj


def extract_tables(obj: Any) -> List[Dict[str, Any]]:
    """
    Robustly extract tables from *any* structure.
    Accounts for raw lists, single dicts, individual API calls, and batch API outputs.
    """
    if isinstance(obj, list):
        tables = []
        for item in obj:
            if is_table(item):
                tables.append(item)
            else:
                tables.extend(extract_tables(item))
        return tables

    if is_table(obj):
        return [obj]

    if not isinstance(obj, dict):
        return []

    candidates = obj.get("candidates", [])
    if not candidates and "response" in obj:
        candidates = obj["response"].get("candidates", [])

    tables = []
    for cand in candidates:
        content = cand.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if not text:
                continue
            
            # Clean markdown code blocks if the LLM added them
            text_clean = text.strip()
            if text_clean.startswith("```json"):
                text_clean = text_clean[7:]
            if text_clean.endswith("```"):
                text_clean = text_clean[:-3]
            text_clean = text_clean.strip()

            try:
                parsed = json.loads(text_clean)
                tables.extend(extract_tables(parsed))
            except json.JSONDecodeError:
                continue

    return tables


def write_csv(table: Dict[str, Any], csv_path: Path) -> bool:
    title = table.get("title", "Untitled")
    metadata = table.get("metadata", {})
    columns = table.get("columns", [])
    data = table.get("data", [])

    if not columns or not data:
        return False

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # ---- Title ----
        writer.writerow(["# TITLE", title])

        # ---- Metadata ----
        if metadata:
            writer.writerow(["# METADATA"])
            for k, v in metadata.items():
                if isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        writer.writerow([f"# {k}.{sub_k}", sub_v])
                else:
                    writer.writerow([f"# {k}", v])
            writer.writerow([])

        # ---- Table ----
        writer.writerow(columns)

        for row in data:
            if len(row) < len(columns):
                row += [""] * (len(columns) - len(row))
            writer.writerow(row)

    return True


# -----------------------------
# Main Directory Processor
# -----------------------------

def process_folder(input_dir: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    for filepath in input_dir.glob("*_3.json"):
        base_name = filepath.stem
        
        # Extract the first sequence of digits to act as the page number (e.g. from "page_45" or "p79_1892")
        page_match = re.search(r'\d+', base_name)
        page_num = page_match.group() if page_match else "unknown"

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except json.JSONDecodeError:
            print(f"Failed to decode JSON: {filepath.name}")
            continue

        if isinstance(obj, dict) and "error" in obj:
            print(f"Error block found in {filepath.name}, skipping.")
            continue

        tables = extract_tables(obj)
        if not tables:
            print(f"No tables found in {filepath.name}")
            continue

        for t_idx, table in enumerate(tables, start=1):
            title = table.get("title", "Untitled")
            
            # Parses into format: "armagh_february_1897"
            safe_title = standardise_filename(title)

            # Combines into format: "1_armagh_january_1894_table1.csv"
            csv_name = f"{page_num}_{safe_title}_table_{t_idx}.csv"
            csv_path = output_dir / csv_name

            if write_csv(table, csv_path):
                print(f"Wrote {csv_path.name}")


# -----------------------------
# Execution
# -----------------------------

if __name__ == "__main__":
    # Define directories using pathlib.Path
    INPUT_DIR = Path("")
    OUTPUT_DIR = Path("")
    
    print(f"Starting batch conversion from {INPUT_DIR}...")
    process_folder(INPUT_DIR, OUTPUT_DIR)
    print("Finished processing all files.")