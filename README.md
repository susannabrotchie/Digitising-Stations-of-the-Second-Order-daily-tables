# Stations-of-the-Second-Order-daily-tables
Data and code from Brotchie et al. (in review) *Digitising historical climate data using the Google Gemini Large Language Model*, which rescued over 6 million observations of key climate variables including of pressure, temperature, rainfall and wind. The dataset covers 1873-1921 across the United Kingdom, Republic of Ireland, Isle of Man and Jersey, Channel Islands.<br>

This repository is archived on Zenodo at https://doi.org/10.5281/zenodo.23955578<br>

The script for Step 1 downloads the scanned archival documents as PDFs from their source https://digital.nmla.metoffice.gov.uk/SO_feb1a621-72a3-4501-a6d2-8af1a8abe545/ to the working directory.<br>
Steps 3-7b cover the transcription of the data using Google Gemini 3.1 Pro Preview.<br>
Post-processing is conducted in Steps 8a-11 and 14.<br>
Finally, technical validation is handled by the scripts for Steps 12, 13 and 15.<br>
The full pipeline is detailed in Brotchie et al. (in prep.).<br>

<img width="600" height="550" alt="Pipeline" src="https://github.com/user-attachments/assets/da3e17e5-c7e3-4f00-aabb-d4e598eb7b9a" />

The data are available in Station Exchange Format as TSV files and in CSV files that imitate the original tabular structure.<br>
The Station Exchange Format documentation is available at https://datarescue.climate.copernicus.eu/station-exchange-format-sef
<br>The filename convention of the Station Exchange Format is STATIONNAME\_variablecode\_startdate\_enddate.tsv where the date format is YYYYMMDD. There are 65 folders, each containing the data for 1 station. The variable codes are provided below.

| Variable code  | Variable long name  |
| ------------- | ------------- |
| p  | Air pressure at station level   |
| mslp  | Air pressure at mean sea level  |
| Ta | Air temperature |
| Tx | Maximum temperature |
| Tn | Minimum temperature |
| dep\_wet | Depression of wet-bulb temperature |
| e | Vapour pressure |
| rh | Relative humidity |
| dd | Wind direction |
| w | Wind speed |
| n | Cloud cover |
| ss | Sunshine duration |
| TGn | Minimum temperature on grass |

For the CSV files from the composite dataset, the filename convention is SSO_stationname_YYYY_MM_COMPOSITE.csv where SSO is 'Stations of the Second Order'.<br>

We provide a manually transcribed ground truth dataset as a supplementary dataset. Each XLSX file contains all the daily tables for 1 month organised by station.
