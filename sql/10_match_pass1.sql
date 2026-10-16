-- Pass 1: switch <-> NPCI, exact on UPI_TXN_ID + amount.
-- Only NPCI rows from settlement files that had ARRIVED by the recon cut-off are visible (RAW holds only
-- arrived files; the pending file is ingested later by recon/pipeline.py ingest-pending).
CREATE OR REPLACE TABLE RECON.M1 AS
SELECT s."UPI_TXN_ID", s."RRN", s."TXN_TS" AS "SW_TS", s."AMOUNT_PAISE", s."STATUS" AS "SW_STATUS",
       s."RESP_CODE" AS "SW_RESP", n."STATUS" AS "NPCI_STATUS", n."RESP_CODE" AS "NPCI_RESP",
       n."TXN_TYPE", n."PAYEE_BANK", n."SETTLEMENT_DT", n."CYCLE_NO", 1 AS "MATCH_PASS"
FROM "RAW"."SWITCH_LOG" s
JOIN "RAW"."NPCI_SETTLEMENT" n
  ON n."UPI_TXN_ID" = s."UPI_TXN_ID" AND n."AMOUNT_PAISE" = s."AMOUNT_PAISE";
