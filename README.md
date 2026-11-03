# Stations-of-the-Second-Order-daily-tables
Data and code from Brotchie et al. (in prep.) Digitising historical climate data using the Google Gemini Large Language Model

The Step 1 script downloads the scanned archival documents as PDFs from their source https://digital.nmla.metoffice.gov.uk/SO_feb1a621-72a3-4501-a6d2-8af1a8abe545/ to the working directory.<br>
Step 3-7b cover the transcription of the data using Google Gemini 3.1 Pro Preview.<br>
Post-processing is conducted in Steps 8a-11 and 14.<br>
Finally, technical validation is handled by the scripts for Steps 12,13 and 15.<br>
The full pipeline is detailed in Brotchie et al. (in prep.).<br>

<img width="600" height="550" alt="Pipeline" src="https://github.com/user-attachments/assets/da3e17e5-c7e3-4f00-aabb-d4e598eb7b9a" />


The data are available in Station Exchange Format as TSV files and in CSV files that imitate the original tabular structure.<br>The Station Exchange Format documentation is available at https://datarescue.climate.copernicus.eu/station-exchange-format-sef
<br>The filename convention of the Station Exchange Format is STATIONNAME\_variablecode\_startdate\_enddate.tsv where the date format is YYYYMMDD. The variable codes are provided below.

Variable long name : SEF variable code<br>
Air pressure at station level : p<br>
Air pressure at mean sea level : mslp<br>
Air temperature : Ta<br>
Minimum temperature : Tn<br>
Maximum temperature : Tx<br>
Depression of wet-bulb temperature : dep\_wet<br>
Vapour pressure : e<br>
Relative humidity : rh<br>
Wind direction : dd<br>
Wind speed : w<br>
Cloud cover : n<br>
Sunshine duration : ss<br>
Minimum temperature on grass : TGn<br>


For the CSV files from the composite dataset, the filename convention is SSO_stationname_YYYY_MM_COMPOSITE.csv where SSO is 'Stations of the Second Order'.
