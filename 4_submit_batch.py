import os
from google import genai

API_KEY = ""
JSONL_FILENAME = ""
ID_OUTPUT_FILE = ""

client = genai.Client(api_key=API_KEY)

def main():
    print("Submitting Batch Job...")

    # 1. We must upload the JSONL file itself to the File API first
    batch_file = client.files.upload(
        file=JSONL_FILENAME,
        config={'mime_type': 'application/json'} 
    )
    
    print(f"Batch file uploaded: {batch_file.uri}")

    
    # 2. Create the Batch Job
    # We reference the uploaded JSONL file URI
    #NOTE: INSERT MODEL NAME
    job = client.batches.create(
        model="models/gemini-3.1-pro-preview",
        src=batch_file.name
    )

    print("\n------------------------------------------------")
    print("JOB SUBMITTED SUCCESSFULLY")
    print(f"Job Name (ID): {job.name}")
    print("------------------------------------------------")

    with open(ID_OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(job.name)
    print(f"Batch ID saved to: {ID_OUTPUT_FILE}")

if __name__ == "__main__":
    main()