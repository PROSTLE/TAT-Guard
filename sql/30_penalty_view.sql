-- TAT clock and Rs penalty exposure for DEBIT_NO_CREDIT exceptions.
-- Rule (RBI/2019-20/67): "₹100/- per day if delay is beyond T + 1 day" (UPI P2P) / "beyond T + 5 days" (UPI P2M).
-- "T is the day of transaction and refers to the calendar date." "R is the day on which the reversal is concluded".
-- TAT days and paise/day come from RECON.TAT_RULES, which recon/pipeline.py loads from facts.yaml.
-- PENALTY_DAYS = max(0, (R or as-of date) - T - TAT). Must equal recon/penalty.py to the rupee.
CREATE OR REPLACE VIEW RECON.PENALTY_EXPOSURE AS
WITH a AS (SELECT CAST(CAST("PARAM_VALUE" AS TIMESTAMP) AS DATE) AS "AS_OF_DT" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of'),
b AS (
  SELECT e."EXC_ID", e."UPI_TXN_ID", e."RRN", e."TXN_TYPE", e."BANK", e."TXN_DT", e."AMOUNT_PAISE", e."STATUS",
         e."REVERSAL_DT", e."COMP_PAISE", r."CASE_NAME", r."TAT_DAYS", r."PAISE_PER_DAY",
         ADD_DAYS(e."TXN_DT", r."TAT_DAYS") AS "DEADLINE_DT", a."AS_OF_DT",
         COALESCE(e."REVERSAL_DT", a."AS_OF_DT") AS "END_DT"
  FROM "RECON"."EXCEPTIONS" e
  JOIN "RECON"."TAT_RULES" r ON r."TXN_TYPE" = e."TXN_TYPE"
  CROSS JOIN a
  WHERE e."CLASS" = 'DEBIT_NO_CREDIT'
),
d AS (
  SELECT b.*,
         GREATEST(0, DAYS_BETWEEN(b."END_DT", b."TXN_DT") - b."TAT_DAYS") AS "PENALTY_DAYS",
         CASE WHEN b."STATUS" = 'OPEN'
              THEN GREATEST(0, DAYS_BETWEEN(ADD_DAYS(b."AS_OF_DT", 1), b."TXN_DT") - b."TAT_DAYS")
              ELSE GREATEST(0, DAYS_BETWEEN(b."END_DT", b."TXN_DT") - b."TAT_DAYS") END AS "PENALTY_DAYS_NEXT_24H"
  FROM b
)
SELECT d.*,
       d."PENALTY_DAYS" * d."PAISE_PER_DAY" AS "PENALTY_PAISE",
       d."PENALTY_DAYS_NEXT_24H" * d."PAISE_PER_DAY" AS "EXPOSURE_NEXT_24H_PAISE",
       (d."PENALTY_DAYS_NEXT_24H" - d."PENALTY_DAYS") * d."PAISE_PER_DAY" AS "NEW_ACCRUAL_24H_PAISE",
       -- suo-moto compensation check: owed vs credited to the customer (CBS credits typed COMPENSATION)
       CASE WHEN d."PENALTY_DAYS" = 0 THEN 'NOT_DUE'
            WHEN d."STATUS" = 'OPEN' THEN 'ACCRUING'
            WHEN d."COMP_PAISE" >= d."PENALTY_DAYS" * d."PAISE_PER_DAY" THEN 'PAID'
            WHEN d."COMP_PAISE" > 0 THEN 'UNDERPAID'
            ELSE 'MISSING' END AS "COMP_STATUS",
       GREATEST(0, d."PENALTY_DAYS" * d."PAISE_PER_DAY" - d."COMP_PAISE") AS "COMP_GAP_PAISE"
FROM d;

-- Work queue: open exceptions, plus reversed cases whose suo-moto compensation is missing/short,
-- ranked by Rs exposure in the next 24 h, then amount (01 §Phase 3).
-- TAT_STATE (DESIGN, for the UI): OVERDUE = open and accruing; AT_RISK = open, starts accruing by tomorrow;
-- WITHIN_TAT = open, before its deadline; COMPENSATION_DUE = reversed, compensation missing/short;
-- NO_TAT_CLOCK = a break class the RBI TAT rule does not price (only DEBIT_NO_CREDIT has a penalty row).
CREATE OR REPLACE VIEW RECON.WORK_QUEUE AS
SELECT e."EXC_ID", e."CLASS", e."UPI_TXN_ID", e."RRN", e."CBS_ENTRY_ID", e."TXN_TYPE", e."BANK", e."TXN_DT",
       e."TXN_TS", e."AMOUNT_PAISE", e."STATUS",
       CASE WHEN p."EXC_ID" IS NULL THEN 'NO_TAT_CLOCK'
            WHEN e."STATUS" <> 'OPEN' THEN 'COMPENSATION_DUE'
            WHEN p."PENALTY_DAYS" > 0 THEN 'OVERDUE'
            WHEN p."PENALTY_DAYS_NEXT_24H" > 0 THEN 'AT_RISK'
            ELSE 'WITHIN_TAT' END AS "TAT_STATE",
       CASE WHEN e."STATUS" = 'OPEN' THEN 'RESOLVE_' || e."CLASS" ELSE 'PAY_COMPENSATION' END AS "ACTION_NEEDED",
       p."COMP_GAP_PAISE",
       p."DEADLINE_DT", p."PENALTY_PAISE", COALESCE(p."EXPOSURE_NEXT_24H_PAISE", 0) AS "EXPOSURE_NEXT_24H_PAISE",
       COALESCE(p."NEW_ACCRUAL_24H_PAISE", 0) AS "NEW_ACCRUAL_24H_PAISE", p."COMP_STATUS",
       ROW_NUMBER() OVER (ORDER BY COALESCE(p."EXPOSURE_NEXT_24H_PAISE", 0) DESC, e."AMOUNT_PAISE" DESC, e."EXC_ID") AS "QUEUE_RANK"
FROM "RECON"."EXCEPTIONS" e
LEFT JOIN "RECON"."PENALTY_EXPOSURE" p ON p."EXC_ID" = e."EXC_ID"
WHERE e."STATUS" = 'OPEN' OR p."COMP_STATUS" IN ('MISSING', 'UNDERPAID');
