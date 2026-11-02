#!/usr/bin/env python

# Download archival documents from the Met Office National Met Archive

import os
import subprocess
import requests
from bs4 import BeautifulSoup

local_dir = "" #where the pdfs will go 

archive_dir = "https://digital.nmla.metoffice.gov.uk/download/file" #the pdf download url after which the IDs for each region go in a function later on

# Scrape page and get titles and IDs
# FOR BATCH PROCESSING need something like for url in urls... 
url = "https://digital.nmla.metoffice.gov.uk/SO_b08db4f8-6a00-487d-b911-d7f5ef52bcc5" #url of the folder on met archive
response = requests.get(url)
response.raise_for_status()
html = response.text
# getting titles for the pdfs and ids to insert into link to download to local directory
def create_titles_and_ids(html_text):
    soup = BeautifulSoup(html_text, "html.parser")

    # find divs that have exactly the classes you want
    def exact_class_divs(soup, tag="div", exact_classes=("archive_name", "col0")):
        desired = set(exact_classes)
        matches = []
        for el in soup.find_all(tag):
            classes = el.get("class")
            if not classes:
                continue
            if set(classes) == desired:  # exact match (no extra classes)
                matches.append(el)
        return matches

    # Now call it here (outside the helper function)
    divs = exact_class_divs(soup, "div", ("archive_name", "col0"))
    titles = [div.get_text(strip=True) for div in divs]

    # extract link IDs with only ids not whole download links e.g. from https onwards
    links = [a["href"] for a in soup.select("a.new-primary.new-primary-tint-hover.multiline")]
    ids = [href.rstrip("/").split("/")[-1] for href in links]

    return tuple(titles), tuple(ids)

titles, ids = create_titles_and_ids(html)


# ------------------------
# Download PDFs
# ------------------------
period = "1873-1880"
ldir = os.path.join(local_dir, period)
os.makedirs(ldir, exist_ok=True)

for id_, title in zip(ids, titles):
    target = os.path.join(ldir, f"{title}.pdf")  # matching title as filename
    # if os.path.exists(target):
    #     continue
        
    pdf_url = f"{archive_dir}/{id_}"  # direct URL
    print(f"Downloading {pdf_url} -> {target}")
    
    subprocess.call([
        "/usr/bin/wget",
        "--no-check-certificate",
        pdf_url,
        "-O",
        target
    ])

