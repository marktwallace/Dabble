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

Here is the input HTML table (from https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Laboratory&Cycle=2017-2020): 

Years	Data File Name	Doc File	Data File	Date Published
2017-2020	Albumin & Creatinine - Urine	P_ALB_CR Doc	P_ALB_CR Data [XPT - 816 KB]	August 2021
2017-2020	Alpha-1-Acid Glycoprotein - Serum (Surplus)	P_SSAGP Doc	P_SSAGP Data [XPT - 90.8 KB]	June 2024
2017-2020	Arsenic - Total - Urine	P_UTAS Doc	P_UTAS Data [XPT - 154.1 KB]	November 2021
2017-2020	Arsenics - Speciated - Urine	P_UAS Doc	P_UAS Data [XPT - 537.5 KB]	November 2021
2017-2020	Cholesterol - High - Density Lipoprotein (HDL)	P_HDL Doc	P_HDL Data [XPT - 287.1 KB]	August 2021
2017-2020	Cholesterol - Low-Density Lipoproteins (LDL) & Triglycerides	P_TRIGLY Doc	P_TRIGLY Data [XPT - 399.8 KB]	October 2021
2017-2020	Cholesterol - Total	P_TCHOL Doc	P_TCHOL Data [XPT - 287.1 KB]	August 2021
2017-2020	Chromium - Urine	P_UCM Doc	P_UCM Data [XPT - 154.1 KB]	November 2021
2017-2020	Chromium & Cobalt	P_CRCO Doc	P_CRCO Data [XPT - 327.1 KB]	November 2021
2017-2020	Complete Blood Count with 5-Part Differential in Whole Blood	P_CBC Doc	P_CBC Data [XPT - 2.3 MB]	June 2021
2017-2020	Cotinine and Hydroxycotinine - Serum	P_COT Doc	P_COT Data [XPT - 510.3 KB]	July 2022
2017-2020	Cytomegalovirus IgG & IgM Antibodies - Serum	P_CMV Doc	P_CMV Data [XPT - 50.5 KB]	August 2021
2017-2020	Ethylene Oxide	P_ETHOX Doc	P_ETHOX Data [XPT - 128.2 KB]	February 2023
2017-2020	Fasting Questionnaire	P_FASTQX Doc	P_FASTQX Data [XPT - 2 MB]	May 2021
2017-2020	Ferritin	P_FERTIN Doc	P_FERTIN Data [XPT - 282 KB]	July 2021
2017-2020	Flame Retardants - Urine	P_FR Doc	P_FR Data [XPT - 541.8 KB]	May 2023
2017-2020	Flame Retardants - Urine (Surplus)	P_SSFR Doc	P_SSFR Data [XPT - 232.7 KB]	January 2024
2017-2020	Folate - RBC	P_FOLATE Doc	P_FOLATE Data [XPT - 263.4 KB]	December 2021
2017-2020	Folate Forms - Total & Individual - Serum	P_FOLFMS Doc	P_FOLFMS Data [XPT - 1 MB]	December 2021
2017-2020	Glycohemoglobin	P_GHB Doc	P_GHB Data [XPT - 163.7 KB]	May 2021
2017-2020	Hepatitis A	P_HEPA Doc	P_HEPA Data [XPT - 210.6 KB]	August 2022
2017-2020	Hepatitis B Surface Antibody	P_HEPB_S Doc	P_HEPB_S Data [XPT - 210.6 KB]	August 2022
2017-2020	Hepatitis B: Core antibody, Surface antigen, and Hepatitis D antibody	P_HEPBD Doc	P_HEPBD Data [XPT - 382.5 KB]	August 2022
2017-2020	Hepatitis C: RNA (HCV-RNA), Confirmed Antibody (INNO-LIA), & Genotype	P_HEPC Doc	P_HEPC Data [XPT - 382.5 KB]	June 2022
2017-2020	Hepatitis E: IgG & IgM Antibodies	P_HEPE Doc	P_HEPE Data [XPT - 287.1 KB]	August 2022
2017-2020	High-Sensitivity C-Reactive Protein	P_HSCRP Doc	P_HSCRP Data [XPT - 324 KB]	August 2021
2017-2020	Inorganic, Ethyl and Methyl - Blood	P_IHGEM Doc	P_IHGEM Data [XPT - 1.1 MB]	November 2021
2017-2020	Insulin	P_INS Doc	P_INS Data [XPT - 200.2 KB]	August 2021
2017-2020	Iodine - Urine	P_UIO Doc	P_UIO Data [XPT - 154.1 KB]	November 2021
2017-2020	Iron Status - Serum	P_FETIB Doc	P_FETIB Data [XPT - 733.9 KB]	August 2021
2017-2020	Lead, Cadmium, Total Mercury, Selenium, & Manganese - Blood	P_PBCD Doc	P_PBCD Data [XPT - 1.7 MB]	November 2021
2017-2020	Mercury: Inorganic - Urine	P_UHG Doc	P_UHG Data [XPT - 154.1 KB]	November 2021
2017-2020	Metals - Urine	P_UM Doc	P_UM Data [XPT - 920.9 KB]	November 2021
2017-2020	Nickel - Urine	P_UNI Doc	P_UNI Data [XPT - 154.1 KB]	November 2021
2017-2020	Organophosphate Insecticides - Dialkyl Phosphate Metabolites - Urine	P_OPD Doc	P_OPD Data [XPT - 541.8 KB]	November 2023
2017-2020	Perchlorate, Nitrate & Thiocyanate - Urine	P_PERNT Doc	P_PERNT Data [XPT - 307.4 KB]	September 2023
2017-2020	Perfluoroalkyl and Polyfluoroalkyl Substances	P_PFAS Doc	P_PFAS Data [XPT - 544.1 KB]	May 2024
2017-2020	Plasma Fasting Glucose	P_GLU Doc	P_GLU Data [XPT - 160.3 KB]	May 2021
2017-2020	Sex Steroid Hormone Panel - Serum	P_TST Doc	P_TST Data [XPT - 2.7 MB]	December 2024
2017-2020	Standard Biochemistry Profile	P_BIOPRO Doc	P_BIOPRO Data [XPT - 3.3 MB]	August 2021
2017-2020	Transferrin Receptor	P_TFR Doc	P_TFR Data [XPT - 108.3 KB]	July 2022
2017-2020	Urine Flow Rate	P_UCFLOW Doc	P_UCFLOW Data [XPT - 1019.8 KB]	June 2021
2017-2020	Urine Pregnancy Test	P_UCPREG Doc	P_UCPREG Data [XPT - 28.4 KB]	June 2021
2017-2020	Volatile Organic Compound (VOC) Metabolites - Urine	P_UVOC Doc	P_UVOC Data [XPT - 1.6 MB]	September 2022
2017-2020	Volatile Organic Compound (VOC) Metabolites II - Urine	P_UVOC2 Doc	P_UVOC2 Data [XPT - 230.8 KB]	September 2022
2017-2020	Volatile Organic Compounds and Trihalomethanes/MTBE - Blood	P_VOCWB Doc	P_VOCWB Data [XPT - 3.3 MB]	November 2021