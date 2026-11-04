import os
import time
import json
import typing
import glob
from pathlib import Path
from google import genai
from google.genai import types
import typing_extensions as typing

# --- 1. CONFIGURATION ---
FAILED_LIST_FILE = ".txt"
INPUT_FOLDER = ""        # Folder containing your images
OUTPUT_FOLDER = ""  # Folder to save JSON results
MODEL_NAME = "gemini-3.1-pro-preview" 
API_KEY = ""

MANUAL_IGNORE_LIST = [
]

# --- 2. SCHEMA DEFINITIONS ---
class Metadata(typing.TypedDict):
    height_above_msl: str
    height_above_ground_barometer: str
    height_above_ground_thermometers: str
    rain_gauge_height: str
    longitude: str
    latitude: str
    gravity_correction: str
    note: str | None

class TableData(typing.TypedDict):
    title: str
    metadata: Metadata
    columns: list[str]
    # IMPORTANT: The model fills this list of lists.
    # We define strict types here to help the model understand the data.
    data: list[list[str | float | int | None]]

MeteorologicalResponse = list[TableData]

# --- 3. CLIENT SETUP ---
client = genai.Client(api_key=API_KEY)

def process_single_image(image_path: Path):
    """
    Sends one image to Gemini and returns the parsed JSON object.
    """
    print(f"Processing: {image_path.name}...")

    # Load image bytes
    try:
        image_bytes = image_path.read_bytes()
    except Exception as e:
        print(f" [Error] Could not read file: {e}")
        return None

    # Refined Prompt for Accuracy + Alignment
    prompt_text = f"""
                Transcribe the meteorological tables from this image.
                
                IMPORTANT:
                The 'source_filename' field in the JSON MUST be exactly: "{image_path.name}"
                Extract each meteorological table exactly once. Do not output duplicate tables.
                The 'data' field must be a list of lists.
                You MUST maintain strict column alignment. 
                The final row must align with the rest of the table.
                If a cell in the table is empty, blank, or contains a dash indicating no data, you MUST use null in the JSON array. 
                Do NOT skip values. 
                The length of every row in 'data' must match the length of 'columns'. 
                Extract the title, metadata, columns, and rows exactly as defined in the schema.
                Do not extract any column whose header contains the word 'remarks'.
                """

    content = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            types.Part(text=prompt_text),
        ],
    )

    # Config
    generate_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=MeteorologicalResponse,
        max_output_tokens=50192, #same as batch api call
        temperature=1.0, #same as batch api call
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[content],
            config=generate_config,
        )
        
        # Parse result immediately to ensure valid JSON
        return json.loads(response.text)

    except Exception as e:
        print(f"  [API Error] {image_path.name}: {e}")
        return None

def main():
    # Create output directory if it doesn't exist
    Path(OUTPUT_FOLDER).mkdir(parents=True, exist_ok=True)
    
    # read failed list
    if not os.path.exists(FAILED_LIST_FILE):
        print(f"Error: could not find list file: {FAILED_LIST_FILE}")
        return
    print(f"Reading target images from: {FAILED_LIST_FILE}")
    target_images = []
    with open(FAILED_LIST_FILE, "r") as f:
        for line in f:
            clean_path_str = line.strip()
            if not clean_path_str: continue
            path_obj = Path(clean_path_str)
            filename = path_obj.name
            # # check ignore list 
            # if filename in MANUAL_IGNORE_LIST:
            #     print(f"Ignoring: {filename} (manually excluded)")
            #     continue
            if not path_obj.exists():
                print(f"Warning: file not found on disk: {clean_path_str}")
                continue
            target_images.append(path_obj)
    print("-" * 40)
    print(f"Queue Size: {len(target_images)} images")
    print("-" * 40)

    for i, img_path in enumerate(target_images):
        output_filename = f"{img_path.stem}.json"
        output_path = Path(OUTPUT_FOLDER) / output_filename
        if output_path.exists():
            print(f"[{i+1}/{len(target_images)}] skipping {img_path.name} (done)")
            continue
        print(f"[{i+1}/{len(target_images)}] sending {img_path.name} (done)")
        result_json = process_single_image(img_path)
        if result_json:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result_json, f, indent=2)
            print(f"> Saved JSON")
    print(f"\nProcessing complete")
if __name__ == "__main__":
    main()


#     # Get list of images (jpg, png, jpeg)
#     image_files = list(Path(INPUT_FOLDER).glob("*.[jJ][pP]*[gG]"))
    
#     if not image_files:
#         print(f"No images found in {INPUT_FOLDER}")
#         return

#     print(f"Found {len(image_files)} images. Starting batch...")

#     # Iterate through images
#     for i, img_path in enumerate(image_files):
        
#         # Define the output filename (e.g., image1.jpg -> image1.json)
#         output_filename = f"{img_path.stem}.json"
#         output_path = Path(OUTPUT_FOLDER) / output_filename

#         # Skip if already processed (Resume capability)
#         if output_path.exists():
#             print(f"Skipping {img_path.name} (already exists)")
#             continue

#         # Process
#         result_json = process_single_image(img_path)

#         if result_json:
#             # Save individual JSON file immediately
#             with open(output_path, "w", encoding="utf-8") as f:
#                 json.dump(result_json, f, indent=2)
#             print(f"  Saved to {output_filename}")
        
#         # Optional: Sleep briefly to avoid hitting rate limits if you are on the free tier
#         # time.sleep(2) 

#     print("\nBatch processing complete.")

# if __name__ == "__main__":
#     main()
