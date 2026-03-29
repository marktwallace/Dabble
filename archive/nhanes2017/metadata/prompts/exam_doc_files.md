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

Here is the input HTML table (from https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Examination&Cycle=2017-2020): 

Years	Data File Name	Doc File	Data File	Date Published
2017-2020	Audiometry	P_AUX Doc	P_AUX Data [XPT - 3.5 MB]	March 2022
2017-2020	Audiometry - Acoustic Reflex	P_AUXAR Doc	P_AUXAR Data [XPT - 144 MB]	March 2022
2017-2020	Audiometry - Tympanometry	P_AUXTYM Doc	P_AUXTYM Data [XPT - 35 MB]	March 2022
2017-2020	Audiometry - Wideband Reflectance	P_AUXWBR Doc	P_AUXWBR Data [XPT - 22.8 MB]	March 2022
2017-2020	Blood Pressure - Oscillometric Measurement	P_BPXO Doc	P_BPXO Data [XPT - 1015.5 KB]	May 2021
2017-2020	Body Measures	P_BMX Doc	P_BMX Data [XPT - 2.4 MB]	May 2021
2017-2020	Dual-Energy X-ray Absorptiometry - Femur	P_DXXFEM Doc	P_DXXFEM Data [XPT - 721.1 KB]	September 2021
2017-2020	Dual-Energy X-ray Absorptiometry - Spine	P_DXXSPN Doc	P_DXXSPN Data [XPT - 865.2 KB]	September 2021
2017-2020	Liver Ultrasound Transient Elastography	P_LUX Doc	P_LUX Data [XPT - 1.1 MB]	January 2022
2017-2020	Oral Health - Dentition	P_OHXDEN Doc	P_OHXDEN Data [XPT - 14.7 MB]	Updated June 2021
2017-2020	Oral Health - Recommendation of Care	P_OHXREF Doc	P_OHXREF Data [XPT - 1.3 MB]	May 2021