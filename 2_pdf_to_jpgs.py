import fitz  # PyMuPDF
import os
from pathlib import Path
import configparser
import re

def split_double_spread_pdf_with_custom_numbering(
    pdf_path,
    output_dir,
    dpi=300,
    image_format="jpg"
):
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Create folder per PDF
    pdf_output_dir = Path(output_dir) / pdf_path.stem
    pdf_output_dir.mkdir(parents=True, exist_ok=True)

    # Extract year once
    year_match = re.search(r"(18|19)\d{2}", pdf_path.stem)
    year = year_match.group() if year_match else "unknown"

    doc = fitz.open(pdf_path)
    print(f"Loaded PDF: {pdf_path.name} ({len(doc)} pages)")

    image_counter = 1

    #  split each pdf page in half vertically (for example a pdf scan of a double spread page in a book)
    for page in doc:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        rect = page.rect
        mid_x = rect.width / 2

        halves = [
            fitz.Rect(0, 0, mid_x, rect.height),
            fitz.Rect(mid_x, 0, rect.width, rect.height)
        ]

        for region in halves:
            pix = page.get_pixmap(matrix=mat, clip=region)

            final_name = f"p{image_counter}_{year}.{image_format.lower()}"
            final_path = pdf_output_dir / final_name

            pix.save(final_path)
            image_counter += 1

if __name__ == "__main__":
    config = configparser.ConfigParser()
    config.read("") #config with paths

    input_folder = Path(config["Paths"]["input_folder"])
    output_dir = Path(config["Paths"]["output_dir"])

    pdf_files = sorted(input_folder.glob("*.pdf"))
    if not pdf_files:
        print("No PDFs found")
    else:
        for pdf_path in pdf_files:
            split_double_spread_pdf_with_custom_numbering(pdf_path=pdf_path, output_dir=output_dir)