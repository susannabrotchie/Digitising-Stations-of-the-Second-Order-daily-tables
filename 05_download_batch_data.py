import os
import requests

# --- CONFIGURATION ---
# Your Job ID from the previous logs
BATCH_ID = "" 
API_KEY = ""
OUTPUT_FILENAME = ""

# read batch id from .txt file
# try:
#     with open(BATCH_ID_FILE, "r") as f:
#         raw_text = f.read().strip()
#         BATCH_ID = raw_text.replace("batches/", "") # API saves ID with batches/ prefix, but the download link construction needs the raw ID
# except FileNotFoundError:
#     print(f"Erorr: could not find ID file at: {BATCH_ID_FILE}")
#     exit()

def main():
    # 1. Construct the specific URL found in the GitHub issue
    # Note the ":download" suffix which bypasses the metadata ID check
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    resource_name = f"files/batch-{BATCH_ID}"
    download_url = f"{base_url}/{resource_name}:download"
    
    print(f"1. Attempting Rescue Download for: {BATCH_ID}")
    print(f"   URL: {download_url}")
    
    headers = {
        "x-goog-api-key": API_KEY
    }
    
    params = {
        "alt": "media"
    }

    print(f"2. Saving to '{OUTPUT_FILENAME}'...")

    try:
        # We allow redirects (allow_redirects=True is default in requests, but being explicit)
        with requests.get(download_url, headers=headers, params=params, stream=True, allow_redirects=True) as r:
            
            # Check for errors specifically
            if r.status_code == 404:
                print("Error 404: File not found. (It might have truly expired).")
                return
            elif r.status_code != 200:
                print(f"Error {r.status_code}: {r.text}")
                return
            
            total_size = 0
            with open(OUTPUT_FILENAME, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): 
                    f.write(chunk)
                    total_size += len(chunk)
                    # Visual progress indicator
                    if total_size % (1024*1024) < 8192:
                        print(".", end="", flush=True)

        print(f"\n\nSUCCESS! Download complete.")
        print(f"File size: {total_size / 1024 / 1024:.2f} MB")
        print(f"Saved to: {os.path.abspath(OUTPUT_FILENAME)}")

    except Exception as e:
        print(f"\nDownload Failed: {e}")

if __name__ == "__main__":
    main()
