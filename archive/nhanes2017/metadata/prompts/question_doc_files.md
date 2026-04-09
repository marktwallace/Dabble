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

Here is the input HTML table (from https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Questionnaire&Cycle=2017-2020): 

Years	Data File Name	Doc File	Data File	Date Published
2017-2020	Acculturation	P_ACQ Doc	P_ACQ Data [XPT - 664.8 KB]	September 2021
2017-2020	Alcohol Use	P_ALQ Doc	P_ALQ Data [XPT - 702.5 KB]	January 2022
2017-2020	Audiometry	P_AUQ Doc	P_AUQ Data [XPT - 6.6 MB]	September 2021
2017-2020	Blood Pressure & Cholesterol	P_BPQ Doc	P_BPQ Data [XPT - 878.4 KB]	May 2021
2017-2020	Cardiovascular Health	P_CDQ Doc	P_CDQ Data [XPT - 857.5 KB]	July 2021
2017-2020	Consumer Behavior Phone Follow-up Module - Adult	P_CBQPFA Doc	P_CBQPFA Data [XPT - 4.3 MB]	September 2022
2017-2020	Consumer Behavior Phone Follow-up Module – Child	P_CBQPFC Doc	P_CBQPFC Data [XPT - 2 MB]	September 2022
2017-2020	Current Health Status	P_HSQ Doc	P_HSQ Data [XPT - 148.6 KB]	July 2021
2017-2020	Dermatology	P_DEQ Doc	P_DEQ Data [XPT - 273.9 KB]	June 2021
2017-2020	Diabetes	P_DIQ Doc	P_DIQ Data [XPT - 3.2 MB]	May 2021
2017-2020	Diet Behavior & Nutrition	P_DBQ Doc	P_DBQ Data [XPT - 5.5 MB]	Updated December 2021
2017-2020	Early Childhood	P_ECQ Doc	P_ECQ Data [XPT - 421.2 KB]	July 2021
2017-2020	Food Security	P_FSQ Doc	P_FSQ Data [XPT - 2.4 MB]	February 2022
2017-2020	Health Insurance	P_HIQ Doc	P_HIQ Data [XPT - 1.7 MB]	June 2021
2017-2020	Hepatitis	P_HEQ Doc	P_HEQ Data [XPT - 517.7 KB]	September 2021
2017-2020	Hospital Utilization & Access to Care	P_HUQ Doc	P_HUQ Data [XPT - 852.7 KB]	September 2021
2017-2020	Immunization	P_IMQ Doc	P_IMQ Data [XPT - 1.3 MB]	September 2021
2017-2020	Income	P_INQ Doc	P_INQ Data [XPT - 365.9 KB]	December 2021
2017-2020	Kidney Conditions - Urology	P_KIQ_U Doc	P_KIQ_U Data [XPT - 1.1 MB]	August 2021
2017-2020	Medical Conditions	P_MCQ Doc	P_MCQ Data [XPT - 7.2 MB]	August 2021
2017-2020	Mental Health - Depression Screener	P_DPQ Doc	P_DPQ Data [XPT - 772.7 KB]	June 2021
2017-2020	Occupation	P_OCQ Doc	P_OCQ Data [XPT - 479.5 KB]	September 2021
2017-2020	Oral Health	P_OHQ Doc	P_OHQ Data [XPT - 4.5 MB]	May 2021
2017-2020	Osteoporosis	P_OSQ Doc	P_OSQ Data [XPT - 3.7 MB]	October 2021
2017-2020	Pesticide Use	P_PUQMEC Doc	P_PUQMEC Data [XPT - 287.1 KB]	June 2021
2017-2020	Physical Activity	P_PAQ Doc	P_PAQ Data [XPT - 1.3 MB]	June 2021
2017-2020	Physical Activity - Youth	P_PAQY Doc	P_PAQY Data [XPT - 76.2 KB]	June 2021
2017-2020	Prescription Medications	P_RXQ_RX Doc	P_RXQ_RX Data [XPT - 15.4 MB]	September 2021
1988-2020	Prescription Medications - Drug Information	RXQ_DRUG Doc	RXQ_DRUG Data [XPT - 3.2 MB]	Updated September 2021
2017-2020	Preventive Aspirin Use	P_RXQASA Doc	P_RXQASA Data [XPT - 202.3 KB]	June 2021
2017-2020	Reproductive Health	P_RHQ Doc	P_RHQ Data [XPT - 1.3 MB]	August 2021
2017-2020	Sleep Disorders	P_SLQ Doc	P_SLQ Data [XPT - 759 KB]	July 2021
2017-2020	Smoking - Cigarette Use	P_SMQ Doc	P_SMQ Data [XPT - 1.4 MB]	August 2021
2017-2020	Smoking - Household Smokers	P_SMQFAM Doc	P_SMQFAM Data [XPT - 365.9 KB]	December 2021
2017-2020	Smoking - Recent Tobacco Use	P_SMQRTU Doc	P_SMQRTU Data [XPT - 2 MB]	August 2021
2017-2020	Smoking - Secondhand Smoke Exposure	P_SMQSHS Doc	P_SMQSHS Data [XPT - 1.8 MB]	August 2021
2017-2020	Volatile Toxicant	P_VTQ Doc	P_VTQ Data [XPT - 937.6 KB]	November 2021
2017-2020	Weight History	P_WHQ Doc	P_WHQ Data [XPT - 2.7 MB]	November 2021
2017-2020	Weight History - Youth	P_WHQMEC Doc	P_WHQMEC Data [XPT - 70.4 KB]	November 2021