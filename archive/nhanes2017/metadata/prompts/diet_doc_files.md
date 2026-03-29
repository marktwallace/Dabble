You are processing a list of NHANES 2017–2018 Doc Files from the Dietary Component.

You will be given a list of Doc Files with the following columns:

- Doc File Name (e.g., DR1IFF_J)
- File Title (e.g., Individual Foods, First Day)
- Date Published
- Description (text describing what the file contains)

Some Doc Files appear more than once. For each Doc File Code, keep only the row with the **most recent “Date Published”**.

Return a clean list with one row per Doc File. Each row should be tab-separated with the following format:

{Doc File Code} {Title} {Short Description}

Use only the description provided. Do not paraphrase or guess. Return only the cleaned TSV — no explanation.

Here is the input HTML table (from https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Dietary&CycleBeginYear=2017): 

Data File Name	Doc File	Data File	Date Published
Dietary Interview - Individual Foods, First Day	DR1IFF_J Doc	DR1IFF_J Data [XPT - 72.2 MB]	June 2020
Dietary Interview - Individual Foods, Second Day	DR2IFF_J Doc	DR2IFF_J Data [XPT - 59.9 MB]	June 2020
Dietary Interview - Total Nutrient Intakes, First Day	DR1TOT_J Doc	DR1TOT_J Data [XPT - 11.2 MB]	June 2020
Dietary Interview - Total Nutrient Intakes, Second Day	DR2TOT_J Doc	DR2TOT_J Data [XPT - 5.7 MB]	June 2020
Dietary Interview Technical Support File - Food Codes	DRXFCD_J Doc	DRXFCD_J Data [XPT - 2.8 MB]	June 2020
Dietary Supplement Database - Blend Information	DSBI Doc	DSBI Data [XPT - 8.8 MB]	Updated July 2022
Dietary Supplement Database - Blend Information	DSBI Doc	DSBI Data [XPT - 10 MB]	February 2025
Dietary Supplement Database - Ingredient Information	DSII Doc	DSII Data [XPT - 74 MB]	Updated July 2022
Dietary Supplement Database - Ingredient Information	DSII Doc	DSII Data [XPT - 82.4 MB]	February 2025
Dietary Supplement Database - Product Information	DSPI Doc	DSPI Data [XPT - 5.7 MB]	Updated July 2022
Dietary Supplement Database - Product Information	DSPI Doc	DSPI Data [XPT - 6.5 MB]	February 2025
Dietary Supplement Use 24-Hour - Individual Dietary Supplements, First Day	DS1IDS_J Doc	DS1IDS_J Data [XPT - 3.4 MB]	August 2020
Dietary Supplement Use 24-Hour - Individual Dietary Supplements, Second Day	DS2IDS_J Doc	DS2IDS_J Data [XPT - 3.2 MB]	August 2020
Dietary Supplement Use 24-Hour - Total Dietary Supplements, First Day	DS1TOT_J Doc	DS1TOT_J Data [XPT - 3.3 MB]	August 2020
Dietary Supplement Use 24-Hour - Total Dietary Supplements, Second Day	DS2TOT_J Doc	DS2TOT_J Data [XPT - 3.3 MB]	August 2020
Dietary Supplement Use 30-Day - Individual Dietary Supplements	DSQIDS_J Doc	DSQIDS_J Data [XPT - 8.5 MB]	August 2020
Dietary Supplement Use 30-Day - Total Dietary Supplements	DSQTOT_J Doc	DSQTOT_J Data [XPT - 2.8 MB]	August 2020
