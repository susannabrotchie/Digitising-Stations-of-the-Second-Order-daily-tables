import os
import json
import re
from pathlib import Path

# --- CONFIGURATION ---
BASE_PATH = Path("")
START_YEAR = 1900
END_YEAR = 1921
FOLDERS = ["", ""]
BATCH_OUTPUT_FILE = ".jsonl"

# list of files that failed (used to send these back to standard API)
REPORT_FILENAME = ".txt"

# Detailed list with reasons for failure
DETAILED_REPORT_FILENAME = ".txt"

# REGEX: Extracts filename from the raw JSON string
FILENAME_REGEX = re.compile(r'source_filename\\?":\s*\\?"(.*?)\\?"')

def main():
    # print(f"Indexing local files {START_YEAR} - {END_YEAR}...")
    print(f"Indexing local files in folders: {FOLDERS}...")
    all_local_files = {}
    # for year in range(START_YEAR, END_YEAR + 1):
    #     year_folder = BASE_PATH / str(year)
    #     if year_folder.exists():
    #         for img in year_folder.glob("*.[jJ][pP]*[gG]"):
    #             all_local_files[img.name] = str(img)
    for folder in FOLDERS:
        folder_path = BASE_PATH / folder
        if folder_path.exists():
            for img in folder_path.glob("*.[jJ][pP]*[gG]"):
                all_local_files[img.name] = str(img)

    total_files = len(all_local_files)
    print(f"Total Local Images: {total_files}")
    print(f"Scanning {BATCH_OUTPUT_FILE}...")

    # Dictionary to store the parsed status of each file found in the output
    processed_files = {}

    with open(BATCH_OUTPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            # 1. Extract Filename using Regex
            match = FILENAME_REGEX.search(line)
            if not match:
                continue
            filename = match.group(1)

            # 2. Parse JSON to find the exact reason
            try:
                entry = json.loads(line)
                is_success = False
                reason = "Unknown Error"

                # Check A: Did the API return a top-level error? (e.g. 400 Bad Request)
                if 'error' in entry:
                    reason = f"API Error: {entry['error'].get('message', 'No message')}"
                
                # Check B: Did the model process it but fail to finish correctly?
                elif 'response' in entry:
                    response_data = entry['response']
                    
                    # Sometimes the prompt itself is blocked before generating candidates
                    if 'promptFeedback' in response_data and 'blockReason' in response_data['promptFeedback']:
                        reason = f"Prompt Blocked: {response_data['promptFeedback']['blockReason']}"
                    
                    # Check the candidate's finish reason
                    elif 'candidates' in response_data and len(response_data['candidates']) > 0:
                        finish_reason = response_data['candidates'][0].get('finishReason', 'UNKNOWN')
                        
                        if finish_reason == "STOP":
                            is_success = True
                            reason = "SUCCESS"
                        else:
                            # e.g., SAFETY, MAX_TOKENS, RECITATION, etc.
                            reason = f"FinishReason: {finish_reason}"
                    else:
                        reason = "No candidates returned by model"
                
                # Save the result for this file
                processed_files[filename] = {
                    "success": is_success,
                    "reason": reason
                }

            except json.JSONDecodeError:
                processed_files[filename] = {
                    "success": False,
                    "reason": "Malformed JSON line in output file"
                }

    # 3. Reconcile Local Files vs Processed Files
    success_count = 0
    failed_files_data = [] # List of tuples: (full_path, reason)

    for fname, full_path in all_local_files.items():
        if fname in processed_files:
            file_data = processed_files[fname]
            if file_data["success"]:
                success_count += 1
            else:
                # File was in output, but had an error
                failed_files_data.append((full_path, file_data['reason']))
        else:
            # File was completely missing from the JSONL output
            failed_files_data.append((full_path, "Not found in batch output (Missing/Skipped)"))

    print('-' * 50)
    print(f"Successfully processed: {success_count}")
    print(f"Failed / Missing files: {len(failed_files_data)}")
    print('-' * 50)

    # 4. Write the reports
    # Ensure output directories exist
    Path(REPORT_FILENAME).parent.mkdir(parents=True, exist_ok=True)
    Path(DETAILED_REPORT_FILENAME).parent.mkdir(parents=True, exist_ok=True)
    
    # Write File 1: Just the paths
    with open(REPORT_FILENAME, "w", encoding='utf-8') as f:
        for path, _ in failed_files_data:
            f.write(path + "\n")
    print(f"Saved simple path list to: {REPORT_FILENAME}")

    # Write File 2: Paths + Detailed Reasons
    with open(DETAILED_REPORT_FILENAME, "w", encoding='utf-8') as f:
        f.write("--- FAILED IMAGES DETAILED REPORT ---\n\n")
        for path, reason in failed_files_data:
            f.write(f"{path} | Reason: {reason}\n")
    print(f"Saved detailed failure report to: {DETAILED_REPORT_FILENAME}")

if __name__ == "__main__":
    main()