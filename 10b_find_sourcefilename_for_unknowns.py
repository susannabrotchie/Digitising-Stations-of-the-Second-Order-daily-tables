import csv
import re
from pathlib import Path
from collections import defaultdict, Counter
import yaml

"""
about 10% of files came out of gemini 3.1 without a month
this script searches any file with "unknown" in it for its source filename
it formats this in a .yaml file so the user can go back to the source file and add the required info
prints how many files have an unknown station and/or date
.yaml eg:
    aberdeen:
    1919:
        p28_1919: 
        p56_1919: 
or 
    unknown_station:
    1873:
        p3_1873:
        month:
        location: 
"""

input_folder = Path("/home/users/brotchie/rescue/gemini/gemini3.1/G3.1_data_as_rescued/SSO_formatted/record4_testing_FAS_switchboard3_tidyupdates19/Daily")

existing_yamls = [
    Path("/home/users/brotchie/rescue/gemini/src/record2_tidy19_files_unknown_dates_config.yaml"),
    Path("/home/users/brotchie/rescue/gemini/src/record3_tidy19_files_unknown_dates_config.yaml")
]

output_yaml = Path("/home/users/brotchie/rescue/gemini/src/record4_tidy19_files_unknown_dates_config.yaml")


# Matches e.g. p46_1880.jpg
IMAGE_RE = re.compile(r"(p\d+)_([^.]+)\.jpg$", re.IGNORECASE)

# Extract location from filename
FILENAME_LOCATION_RE = re.compile(r"^sso_(.+?)_[^_]+_[^_]+(?:_\d+)?$", re.IGNORECASE)



def extract_location(csv_path: Path) -> str:
    """
    Prefer parent folder name.
    Fall back to parsing the filename.
    """
    parent = csv_path.parent.name.strip()
    if parent:
        return parent.lower()

    stem = csv_path.stem
    m = FILENAME_LOCATION_RE.match(stem)
    if m:
        return m.group(1).lower()

    return "unknown"


def page_sort_key(page_name):
    m = re.match(r"p(\d+)_", page_name)
    if m:
        return int(m.group(1))
    return 999999


def year_sort_key(year):
    if year.isdigit():
        return (0, int(year))
    return (1, year)


def find_source_filename(csv_path):
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "SOURCE_FILENAME" in line:
                print(line)  # remove later
                return line.split(",", 1)[1].strip().replace(".jpg", "")
    return None

def build_lookup(yaml_files):

    lookup = defaultdict(dict)

    for yaml_file in yaml_files:

        if not yaml_file.exists():
            print(f"Warning: {yaml_file} not found")
            continue

        with yaml_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Top level keys are now YEARS
        for year, pages in data.items():

            for page in pages:

                source = page["source_filename"]

                for loc in page.get("locations", []):

                    location = loc.get("location", "")
                    month = loc.get("month", "")

                    if location:
                        lookup[location][source] = month

    return lookup

def write_yaml(config, output_file): 
    with output_file.open("w", encoding="utf-8") as out: 
        
        for year in sorted(config, key=year_sort_key):

            out.write(f"{year}:\n")

            pages = sorted(
                config[year],
                key=lambda r: page_sort_key(r["source_filename"])
            )

            for page in pages:

                out.write(f"  - source_filename: {page['source_filename']}\n")
                out.write("    locations:\n")

                for loc in page["locations"]:

                    out.write(f"      - location: {loc['location']}\n")
                    out.write(f"        month: {loc['month']}\n")

            out.write("\n")

def main(): 
    lookup = build_lookup(existing_yamls)

    config = defaultdict(list)

    unknown_count = 0
    location_counts = Counter()
    matched_count = 0
    matched_existing = 0

    # Search /input_folder/*/*.csv
    for csv_file in input_folder.rglob("*.csv"):

        # Only process unknown files
        if "unknown" not in csv_file.name.lower():
            continue

        unknown_count += 1

        location = extract_location(csv_file)
        location_counts[location] += 1

        source = find_source_filename(csv_file)
        if source is None:
            continue

        matched_count += 1

        # Remove .jpg
        source = source.removesuffix(".jpg")

        # Extract year from p52_1877
        _, year = source.split("_", 1)

        month = lookup.get(location, {}).get(source, "")

        if month:
            matched_existing += 1

        # Find an existing record for this source filename
        record = None

        for r in config[year]:
            if r["source_filename"] == source:
                record = r
                break

        if record is None:
            record = {
                "source_filename": source,
                "locations": []
            }
            config[year].append(record)

        # Add another possible location
        if location == "unknown_station":
            record["locations"].append({
                "location": "",
                "month": ""
            })
        else:
            record["locations"].append({
                "location": location,
                "month": month
            })
                

    write_yaml(config, output_yaml)


    print(f"Wrote {output_yaml}")
    print(f"Found {unknown_count} CSV files with 'unknown' in the filename.")
    print(f"Matched existing YAML   : {matched_existing}")
    print("Breakdown by location:")
    for location, count in sorted(location_counts.items()):
        print(f"  {location:20} {count}")
    print(f"Missing metadata     : {unknown_count - matched_count}")


if __name__ == "__main__":
    main()