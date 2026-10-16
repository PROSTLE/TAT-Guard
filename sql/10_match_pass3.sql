-- Pass 3: CBS narration -> reference via the Python UDF RECON.EXTRACT_REF, then exact join on RRN.
-- Credit rows are typed (REVERSAL / COMPENSATION) by the patterns in RECON.NARRATION_KIND (first match by priority).
-- Patterns are searched anywhere in the narration (like Python re.search in crosscheck/dual_impl.py), so we use
-- REGEXP_INSTR(...) > 0, documented as "If this is not contained, the value 0 is returned". The docs do not
-- state whether the REGEXP_LIKE predicate needs a whole-string match (its official example pads with .*), so we avoid it.
CREATE OR REPLACE TABLE RECON.CBS_REF AS
WITH p AS (SELECT "PARAM_VALUE" AS "PAT" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'ref_pattern')
SELECT c."CBS_ENTRY_ID", c."ACCOUNT_NO_MASKED", c."POST_TS", c."DR_CR", c."AMOUNT_PAISE", c."NARRATION",
       "RECON"."EXTRACT_REF"(c."NARRATION", p."PAT") AS "REF"
FROM "RAW"."CBS_LEDGER" c CROSS JOIN p;

CREATE OR REPLACE TABLE RECON.CBS_KIND AS
WITH k AS (
  SELECT r."CBS_ENTRY_ID", nk."KIND",
         ROW_NUMBER() OVER (PARTITION BY r."CBS_ENTRY_ID" ORDER BY nk."PRIORITY") AS "RN"
  FROM "RECON"."CBS_REF" r JOIN "RECON"."NARRATION_KIND" nk ON REGEXP_INSTR(r."NARRATION", nk."PATTERN") > 0
  WHERE r."DR_CR" = 'CR'
)
SELECT r."CBS_ENTRY_ID",
       CASE WHEN r."DR_CR" = 'DR' THEN 'DEBIT' ELSE COALESCE(k."KIND", 'OTHER_CREDIT') END AS "KIND"
FROM "RECON"."CBS_REF" r LEFT JOIN k ON k."CBS_ENTRY_ID" = r."CBS_ENTRY_ID" AND k."RN" = 1;

-- CBS entries matched to a transaction by extracted reference
CREATE OR REPLACE TABLE RECON.CBS_MATCH AS
SELECT r."CBS_ENTRY_ID", t."UPI_TXN_ID", t."RRN", k."KIND", r."AMOUNT_PAISE", r."POST_TS",
       3 AS "MATCH_PASS", CAST(1 AS DECIMAL(5,4)) AS "SCORE"
FROM "RECON"."CBS_REF" r
JOIN "RECON"."CBS_KIND" k ON k."CBS_ENTRY_ID" = r."CBS_ENTRY_ID"
JOIN "RECON"."TXN" t ON t."RRN" = r."REF";
