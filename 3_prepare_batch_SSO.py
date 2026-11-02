import os
import json
import time
from pathlib import Path
from google import genai
from google.genai import types
from datetime import datetime

# --- CONFIGURATION ---
BASE_PATH = Path("")
API_KEY = ""
MODEL_NAME = "models/gemini-3.1-pro-preview"

# get today's date so batch request jsonl contains date this script was run for these data (helps keep track)
today_str = datetime.today().strftime("%d%m%Y_%H%M%S")
jsonl_filename = f"batch_requests_{today_str}.jsonl"
output_dir = Path("")
output_dir.mkdir(exist_ok=True)
JSONL_PATH = output_dir / jsonl_filename

START_YEAR = 1900
END_YEAR = 1921


# 1. UPDATE SCHEMA: Add 'source_filename' at the top level
JSON_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            # --- NEW FIELD ---
            "source_filename": {"type": "STRING"}, 
            # -----------------
            "title": {"type": "STRING"},
            "metadata": {
                "type": "OBJECT",
                "properties": {
                    "height_above_msl": {"type": "STRING"},
                    "height_above_ground_barometer": {"type": "STRING"},
                    "height_above_ground_thermometers": {"type": "STRING"},
                    "rain_gauge_height": {"type": "STRING"},
                    "longitude": {"type": "STRING"},
                    "latitude": {"type": "STRING"},
                    "gravity_correction": {"type": "STRING"},
                    "note": {"type": "STRING", "nullable": True}
                }
            },
            "columns": {
                "type": "ARRAY",
                "items": {"type": "STRING"}
            },
            "data": {
                "type": "ARRAY",
                "items": {
                    "type": "ARRAY",
                    "items": {
                        "type": "STRING",
                        "nullable": True
                    }
                }
            }
        }
    }
}

client = genai.Client(api_key=API_KEY)

def get_images_from_year_folder(base_path, start_year, end_year):
    all_images = []
    print(f"Scanning folders {start_year}-{end_year}")

    for year in range(start_year, end_year + 1):
        year_folder = base_path / str(year)

        if not year_folder.exists():
            print(f"Skipping, folder not found: {year_folder}")
        
        images = list(year_folder.glob("*.[jJ][pP]*[gG]"))
        if images:
            print(f"{year} found {len(images)} images")
            all_images.extend(images)
    return all_images


def main():
    image_files = get_images_from_year_folder(BASE_PATH, START_YEAR, END_YEAR)
    if not image_files:
        print(f"No images found.")
        return
    
    print('-' * 40)
    print(f"Total Queue: {len(image_files)} images")
    print('-' * 40)

    with open(JSONL_PATH, "w", encoding="utf-8") as jsonl_file:
        for i, img_path in enumerate(image_files):
            
            print(f"[{i+1}/{len(image_files)}] Uploading {img_path.name}...")
            
            try:
                myfile = client.files.upload(file=img_path)
                
                # 2. UPDATE PROMPT: Inject the filename dynamically
                # We tell the model: "This is file X. Put 'X' in the source_filename field."
                prompt_text = f"""
                Transcribe the meteorological tables from this image.
                
                IMPORTANT:
                The 'source_filename' field in the JSON MUST be exactly: "{img_path.name}"
                Extract each meteorological table exactly once. Do not output duplicate tables.
                The 'data' field must be a list of lists.
                You MUST maintain strict column alignment, especially around the wind columns.
                The final row must align with the rest of the table.
                If a cell in the table is empty, blank, or contains a dash indicating no data, you MUST use null in the JSON array. 
                Do NOT skip values. 
                The length of every row in 'data' must match the length of 'columns'. 
                Ensure you extract all column headers.
                Extract the title, metadata, columns, and rows exactly as defined in the schema.
                Do not extract any column whose header contains the word 'remarks'.
                """

                request_entry = {
                    "request": {
                        "model": MODEL_NAME,
                        "contents": [
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "file_data": {
                                            "mime_type": myfile.mime_type,
                                            "file_uri": myfile.uri
                                        }
                                    },
                                    {
                                        "text": prompt_text # Use the dynamic prompt
                                    }
                                ]
                            }
                        ],
                        "generation_config": {
                            "response_mime_type": "application/json",
                            "response_schema": JSON_SCHEMA,
                            "temperature": 1.0,
                            "max_output_tokens": 50192
                        }
                    }
                }
                
                jsonl_file.write(json.dumps(request_entry) + "\n")
                time.sleep(1)

            except Exception as e:
                print(f"Error: {e}")

    print(f"\nSUCCESS! File '{JSONL_PATH}' created.")

if __name__ == "__main__":
    main()