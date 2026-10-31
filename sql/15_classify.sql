-- Classify every transaction (and every orphan CBS debit) into an exception class, as of RECON.SETTINGS.as_of.
-- Class rules are our DESIGN, evaluated in this order:
--   NPCI_SUCCESS_NO_CBS : NPCI says SUCCESS, no CBS debit found
--   DEBIT_NO_CREDIT     : customer debited, NPCI says FAILED  -> reversal due, TAT clock runs (RBI/2019-20/67)
--                         (before DUPLICATE_POSTING: a double debit on a failed payment must keep its TAT clock)
--   DUPLICATE_POSTING   : two or more CBS debits for one transaction
--   AMOUNT_MISMATCH     : one debit, NPCI SUCCESS, debit amount <> transaction amount
--   LATE_FILE           : no NPCI record, the settlement file for that cycle is overdue (expected <= as_of, not arrived)
--   NPCI_MISSING        : no NPCI record although the cycle's file has arrived
--   UNMATCHED_CBS_DEBIT : CBS debit that no pass could tie to any transaction (needs a human)
CREATE OR REPLACE TABLE RECON.TXN_STATE AS
WITH a AS (SELECT CAST("PARAM_VALUE" AS TIMESTAMP) AS "AS_OF" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of'),
agg AS (
  SELECT "RRN",
         SUM(CASE WHEN "KIND" = 'DEBIT' THEN 1 ELSE 0 END) AS "DR_CNT",
         MAX(CASE WHEN "KIND" = 'DEBIT' THEN "AMOUNT_PAISE" END) AS "DR_AMT_MAX",
         MIN(CASE WHEN "KIND" = 'DEBIT' THEN "AMOUNT_PAISE" END) AS "DR_AMT_MIN",
         SUM(CASE WHEN "KIND" = 'DEBIT' THEN "AMOUNT_PAISE" ELSE 0 END) AS "DR_AMT_SUM",
         SUM(CASE WHEN "KIND" = 'REVERSAL' THEN 1 ELSE 0 END) AS "REV_CNT",
         SUM(CASE WHEN "KIND" = 'REVERSAL' THEN "AMOUNT_PAISE" ELSE 0 END) AS "REV_PAISE",
         MAX(CASE WHEN "KIND" = 'REVERSAL' THEN "POST_TS" END) AS "REV_TS",
         SUM(CASE WHEN "KIND" = 'COMPENSATION' THEN "AMOUNT_PAISE" ELSE 0 END) AS "COMP_PAISE",
         MAX("MATCH_PASS") AS "CBS_PASS"
  FROM "RECON"."CBS_MATCH" GROUP BY "RRN"
)
-- REVERSAL_DT is R, "the day on which the reversal is concluded" [RBI-TAT-R-DEF]: set only once reversals cover every
-- debit, to the latest reversal. A partial reversal leaves R empty, so the case stays OPEN and its clock keeps running.
SELECT t.*, COALESCE(g."DR_CNT", 0) AS "DR_CNT", g."DR_AMT_MAX", g."DR_AMT_MIN", COALESCE(g."DR_AMT_SUM", 0) AS "DR_AMT_SUM",
       COALESCE(g."REV_CNT", 0) AS "REV_CNT", COALESCE(g."REV_PAISE", 0) AS "REV_PAISE",
       CASE WHEN g."REV_PAISE" > 0 AND g."REV_PAISE" >= g."DR_AMT_SUM" THEN CAST(g."REV_TS" AS DATE) END AS "REVERSAL_DT",
       COALESCE(g."COMP_PAISE", 0) AS "COMP_PAISE", g."CBS_PASS",
       f."EXPECTED_TS" AS "FILE_EXPECTED_TS", f."ARRIVED_TS" AS "FILE_ARRIVED_TS",
       f."SETTLEMENT_DT" AS "FILE_SETTLEMENT_DT", f."CYCLE_NO" AS "FILE_CYCLE_NO", a."AS_OF"
FROM "RECON"."TXN" t
LEFT JOIN agg g ON g."RRN" = t."RRN"
LEFT JOIN "RAW"."SETTLEMENT_FILE_LOG" f ON t."SW_TS" >= f."CYCLE_START_TS" AND t."SW_TS" < f."CYCLE_END_TS"
CROSS JOIN a;

CREATE OR REPLACE TABLE RECON.EXCEPTIONS AS
WITH c AS (
  SELECT s.*,
         CASE
           WHEN s."NPCI_STATUS" = 'SUCCESS' AND s."DR_CNT" = 0 THEN 'NPCI_SUCCESS_NO_CBS'
           WHEN s."DR_CNT" >= 1 AND s."NPCI_STATUS" = 'FAILED' THEN 'DEBIT_NO_CREDIT'
           WHEN s."DR_CNT" >= 2 THEN 'DUPLICATE_POSTING'
           WHEN s."DR_CNT" = 1 AND s."NPCI_STATUS" = 'SUCCESS' AND s."DR_AMT_MAX" <> s."AMOUNT_PAISE" THEN 'AMOUNT_MISMATCH'
           WHEN s."NPCI_STATUS" IS NULL AND s."FILE_ARRIVED_TS" IS NULL AND s."FILE_EXPECTED_TS" <= s."AS_OF"
                AND (s."DR_CNT" >= 1 OR s."SW_STATUS" = 'SUCCESS') THEN 'LATE_FILE'
           WHEN s."NPCI_STATUS" IS NULL AND s."FILE_ARRIVED_TS" IS NOT NULL
                AND (s."DR_CNT" >= 1 OR s."SW_STATUS" = 'SUCCESS') THEN 'NPCI_MISSING'
         END AS "CLASS"
  FROM "RECON"."TXN_STATE" s
)
SELECT 'E' || COALESCE(c."UPI_TXN_ID", 'RRN' || c."RRN") AS "EXC_ID",
       c."UPI_TXN_ID", c."RRN", CAST(NULL AS VARCHAR(40)) AS "CBS_ENTRY_ID", c."CLASS",
       CAST(c."SW_TS" AS DATE) AS "TXN_DT", c."SW_TS" AS "TXN_TS", c."TXN_TYPE", c."AMOUNT_PAISE",
       c."PAYEE_BANK" AS "BANK", c."DR_CNT", c."DR_AMT_MAX" AS "DEBIT_AMOUNT_PAISE",
       c."DR_AMT_SUM" AS "DEBIT_TOTAL_PAISE", c."REV_PAISE" AS "REVERSED_PAISE", c."REVERSAL_DT", c."COMP_PAISE",
       c."FILE_SETTLEMENT_DT", c."FILE_CYCLE_NO", c."SW_RESP" AS "RESP_CODE", c."MATCH_PASS", c."CBS_PASS",
       c."AS_OF" AS "DETECTED_TS",
       CASE WHEN c."CLASS" = 'DEBIT_NO_CREDIT' AND c."REVERSAL_DT" IS NOT NULL THEN 'REVERSED' ELSE 'OPEN' END AS "STATUS"
FROM c WHERE c."CLASS" IS NOT NULL
UNION ALL
SELECT 'E' || r."CBS_ENTRY_ID", CAST(NULL AS VARCHAR(40)), r."REF", r."CBS_ENTRY_ID", 'UNMATCHED_CBS_DEBIT',
       CAST(r."POST_TS" AS DATE), r."POST_TS", CAST(NULL AS VARCHAR(10)), r."AMOUNT_PAISE",
       CAST(NULL AS VARCHAR(20)), 1, r."AMOUNT_PAISE", r."AMOUNT_PAISE", 0, CAST(NULL AS DATE), 0,
       CAST(NULL AS DATE), CAST(NULL AS DECIMAL(3,0)), CAST(NULL AS VARCHAR(10)), CAST(NULL AS DECIMAL(1,0)), CAST(NULL AS DECIMAL(1,0)),
       (SELECT CAST("PARAM_VALUE" AS TIMESTAMP) FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of'), 'OPEN'
FROM "RECON"."CBS_REF" r
WHERE r."DR_CR" = 'DR'
  AND NOT EXISTS (SELECT 1 FROM "RECON"."CBS_MATCH" m WHERE m."CBS_ENTRY_ID" = r."CBS_ENTRY_ID");
